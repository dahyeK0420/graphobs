from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Mapping
from typing import TypedDict, cast

import pytest
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore
from openinference.semconv.trace import SpanAttributes
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from graphobs.contracts.models import (
    ContractViolationAction,
    NodeContract,
    ProjectionPolicy,
    StateContractError,
    SubgraphContract,
)
from graphobs.langgraph.execution import (
    instrument_contract_run,
    node_contract_run_spec,
    subgraph_contract_run_spec,
)
from graphobs.langgraph.nodes import (
    add_contract_node,
    contract_node,
)
from graphobs.langgraph.schemas import langgraph_input_schema
from graphobs.langgraph.subgraphs import (
    InvokableGraph,
    contract_subgraph,
)


class ExampleState(TypedDict, total=False):
    request: dict[str, object]
    classification: dict[str, object]
    answer: dict[str, object]
    scratch: dict[str, object]
    unexpected: str


class RuntimeContext(TypedDict):
    label: str


class AsyncOnlyCompiledGraph:
    async def ainvoke(self, input: MappingState) -> MappingState:
        await asyncio.sleep(0)
        assert input == {"request": {"text": "hello"}, "scratch": {"note": "local"}}
        return {
            "request": {"text": "hello"},
            "answer": {"text": "hello async"},
            "scratch": {"note": "complete"},
        }


class ConfigAwareCompiledGraph:
    def __init__(self) -> None:
        self.received_config: RunnableConfig | None = None

    def invoke(
        self,
        input: MappingState,
        config: RunnableConfig | None = None,
    ) -> MappingState:
        self.received_config = config
        assert input == {"request": {"text": "hello"}}
        return {"request": {"text": "hello"}, "answer": {"text": "configured"}}


class NoConfigCompiledGraph:
    def invoke(self, input: MappingState) -> MappingState:
        assert input == {"request": {"text": "hello"}}
        return {"request": {"text": "hello"}, "answer": {"text": "no config"}}


class AsyncConfigAwareCompiledGraph:
    def __init__(self) -> None:
        self.received_config: RunnableConfig | None = None

    async def ainvoke(
        self,
        input: MappingState,
        config: RunnableConfig | None = None,
    ) -> MappingState:
        await asyncio.sleep(0)
        self.received_config = config
        assert input == {"request": {"text": "hello"}}
        return {"request": {"text": "hello"}, "answer": {"text": "async config"}}


def test_contract_node_wraps_sync_langgraph_node(
    span_exporter: InMemorySpanExporter,
) -> None:
    def classify(state: MappingState) -> MappingState:
        assert state == {"request": {"text": "hello"}, "scratch": {"step": 1}}
        return {"classification": {"label": "greeting"}, "scratch": {"step": 2}}

    contract = NodeContract(
        name="classify",
        reads=("request.text",),
        writes=("classification.label",),
        private_reads=("scratch.step",),
        private_writes=("scratch.step",),
    )
    graph = StateGraph(ExampleState)
    add_contract_node(graph, contract, classify)
    graph.add_edge(START, "classify")
    graph.add_edge("classify", END)

    result = graph.compile().invoke(
        {"request": {"text": "hello", "raw": "hidden"}, "scratch": {"step": 1}}
    )

    assert result["classification"] == {"label": "greeting"}
    assert result["scratch"] == {"step": 2}
    span = span_exporter.get_finished_spans()[0]
    assert span.name == "classify"
    assert span.attributes is not None
    assert span.attributes["graph.node"] == "classify"
    input_value = span.attributes[SpanAttributes.INPUT_VALUE]
    assert isinstance(input_value, str)
    assert "hidden" not in input_value


def test_contract_node_wraps_async_node(
    span_exporter: InMemorySpanExporter,
) -> None:
    async def classify_async(state: MappingState) -> MappingState:
        await asyncio.sleep(0)
        assert state == {"request": {"text": "hello"}}
        return {"classification": {"label": "greeting"}}

    contract = NodeContract(
        name="classify_async",
        reads=("request.text",),
        writes=("classification.label",),
    )
    wrapped = contract_node(classify_async, contract)

    async def invoke_wrapped() -> MappingState:
        return await wrapped({"request": {"text": "hello", "raw": "hidden"}})

    result = asyncio.run(invoke_wrapped())

    assert result == {"classification": {"label": "greeting"}}
    span = span_exporter.get_finished_spans()[0]
    assert span.name == "classify_async"


def test_contract_node_can_pass_through_state_while_projecting_span(
    span_exporter: InMemorySpanExporter,
) -> None:
    def classify(state: MappingState) -> MappingState:
        assert state == {
            "request": {"text": "hello", "raw": "hidden"},
            "context": {"fallback": "available"},
        }
        context = state["context"]
        assert isinstance(context, Mapping)
        return {"classification": {"label": str(context["fallback"])}}

    contract = NodeContract(
        name="classify_passthrough",
        reads=("request.text",),
        writes=("classification.label",),
    )
    wrapped = contract_node(classify, contract, pass_through_state=True)

    result = wrapped(
        {
            "request": {"text": "hello", "raw": "hidden"},
            "context": {"fallback": "available"},
        }
    )

    assert result == {"classification": {"label": "available"}}
    span = span_exporter.get_finished_spans()[0]
    assert span.attributes is not None
    input_value = span.attributes[SpanAttributes.INPUT_VALUE]
    assert isinstance(input_value, str)
    assert "hidden" not in input_value
    assert "fallback" not in input_value


def test_contract_node_audit_reads_warns_for_undeclared_paths(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="graphobs.langgraph")

    def classify(state: MappingState) -> MappingState:
        request = state["request"]
        context = state.get("context", {})
        assert isinstance(request, Mapping)
        assert isinstance(context, Mapping)
        label = f"{request['text']} {context.get('retrieved', '')}"
        context.get("extra")
        return {"classification": {"label": label.strip()}}

    contract = NodeContract(
        name="classify_audited",
        reads=("request.text", "context.retrieved"),
        writes=("classification.label",),
    )
    wrapped = contract_node(
        classify,
        contract,
        pass_through_state=True,
        audit_reads=True,
    )

    result = wrapped(
        {
            "request": {"text": "hello"},
            "context": {"retrieved": "document", "extra": "not declared"},
        }
    )

    assert result == {"classification": {"label": "hello document"}}
    assert caplog.messages == [
        "Contract 'classify_audited' read undeclared state paths: context.extra"
    ]
    assert "not declared" not in caplog.text


def test_contract_node_audit_reads_allows_parent_read_policy(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="graphobs.langgraph")

    def classify(state: MappingState) -> MappingState:
        context = state["context"]
        assert isinstance(context, Mapping)
        return {"classification": {"label": str(context["extra"])}}

    contract = NodeContract(
        name="classify_parent_read",
        reads=("context",),
        writes=("classification.label",),
    )
    wrapped = contract_node(
        classify,
        contract,
        pass_through_state=True,
        audit_reads=True,
    )

    result = wrapped({"context": {"extra": "allowed"}})

    assert result == {"classification": {"label": "allowed"}}
    assert caplog.messages == []


def test_contract_node_pass_through_and_audit_support_async_nodes(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="graphobs.langgraph")

    async def classify_async(state: MappingState) -> MappingState:
        await asyncio.sleep(0)
        request = state["request"]
        assert isinstance(request, Mapping)
        request.get("raw")
        return {"classification": {"label": str(request["text"])}}

    contract = NodeContract(
        name="async_passthrough_audit",
        reads=("request.text",),
        writes=("classification.label",),
    )
    wrapped = contract_node(
        classify_async,
        contract,
        pass_through_state=True,
        audit_reads=True,
    )

    async def invoke_wrapped() -> MappingState:
        return await wrapped({"request": {"text": "hello", "raw": "hidden"}})

    result = asyncio.run(invoke_wrapped())

    assert result == {"classification": {"label": "hello"}}
    assert caplog.messages == [
        "Contract 'async_passthrough_audit' read undeclared state paths: request.raw"
    ]


def test_contract_node_forwards_langgraph_config() -> None:
    received_metadata: dict[str, object] = {}

    def classify(state: MappingState, config: RunnableConfig) -> MappingState:
        assert state == {"request": {"text": "hello"}}
        metadata = config.get("metadata")
        assert isinstance(metadata, dict)
        received_metadata.update(metadata)
        return {"classification": {"label": "greeting"}}

    contract = NodeContract(
        name="classify_with_config",
        reads=("request.text",),
        writes=("classification.label",),
    )
    graph = StateGraph(ExampleState)
    add_contract_node(graph, contract, classify)
    graph.add_edge(START, "classify_with_config")
    graph.add_edge("classify_with_config", END)
    config = cast(RunnableConfig, {"metadata": {"request_id": "request-1"}})

    result = graph.compile().invoke(
        {"request": {"text": "hello", "raw": "hidden"}},
        config=config,
    )

    assert result["classification"] == {"label": "greeting"}
    assert received_metadata["request_id"] == "request-1"
    assert received_metadata["langgraph_node"] == "classify_with_config"


def test_contract_node_forwards_runtime_and_store_kwargs() -> None:
    memory_store = InMemoryStore()
    received: dict[str, object] = {}

    def classify(
        state: MappingState,
        runtime: Runtime[RuntimeContext],
        store: BaseStore,
    ) -> MappingState:
        assert state == {"request": {"text": "hello"}}
        received["context"] = runtime.context
        received["store"] = store
        return {"classification": {"label": runtime.context["label"]}}

    contract = NodeContract(
        name="classify_with_runtime",
        reads=("request.text",),
        writes=("classification.label",),
    )
    graph = StateGraph(ExampleState, context_schema=RuntimeContext)
    add_contract_node(graph, contract, classify)
    graph.add_edge(START, "classify_with_runtime")
    graph.add_edge("classify_with_runtime", END)

    result = graph.compile(store=memory_store).invoke(
        {"request": {"text": "hello", "raw": "hidden"}},
        context={"label": "runtime-label"},
    )

    assert result["classification"] == {"label": "runtime-label"}
    assert received == {
        "context": {"label": "runtime-label"},
        "store": memory_store,
    }


def test_contract_node_decorator_wraps_sync_node(
    span_exporter: InMemorySpanExporter,
) -> None:
    contract = NodeContract(
        name="decorated_classify",
        reads=("request.text",),
        writes=("classification.label",),
    )

    @contract_node(contract)
    def classify(state: MappingState) -> MappingState:
        assert state == {"request": {"text": "hello"}}
        return {"classification": {"label": "greeting"}}

    result = classify({"request": {"text": "hello", "raw": "hidden"}})

    assert result == {"classification": {"label": "greeting"}}
    span = span_exporter.get_finished_spans()[0]
    assert span.name == "decorated_classify"
    assert span.attributes is not None
    input_value = span.attributes[SpanAttributes.INPUT_VALUE]
    assert isinstance(input_value, str)
    assert "hidden" not in input_value


def test_contract_node_decorator_wraps_async_node(
    span_exporter: InMemorySpanExporter,
) -> None:
    contract = NodeContract(
        name="decorated_async_classify",
        reads=("request.text",),
        writes=("classification.label",),
    )

    @contract_node(contract)
    async def classify_async(state: MappingState) -> MappingState:
        await asyncio.sleep(0)
        assert state == {"request": {"text": "hello"}}
        return {"classification": {"label": "greeting"}}

    async def invoke_wrapped() -> MappingState:
        return await classify_async({"request": {"text": "hello", "raw": "hidden"}})

    result = asyncio.run(invoke_wrapped())

    assert result == {"classification": {"label": "greeting"}}
    span = span_exporter.get_finished_spans()[0]
    assert span.name == "decorated_async_classify"


def test_node_contract_run_spec_returns_update_and_projects_span_output(
    span_exporter: InMemorySpanExporter,
) -> None:
    contract = NodeContract(
        name="spec_classify",
        reads=("request.text",),
        writes=("classification.label",),
        private_writes=("scratch.step",),
    )
    spec = node_contract_run_spec(
        contract,
        span_kind="CHAIN",
        attributes={"graph.node": contract.label},
        execution_input=lambda state: {"request": state["request"]},
        on_violation=ContractViolationAction.RAISE,
        logger=logging.getLogger("graphobs.langgraph"),
    )

    result = instrument_contract_run(
        spec,
        {"request": {"text": "hello", "raw": "hidden"}},
        execute=lambda _run_input: {
            "classification": {"label": "greeting"},
            "scratch": {"step": 1},
        },
    )

    assert result == {"classification": {"label": "greeting"}, "scratch": {"step": 1}}
    span = span_exporter.get_finished_spans()[0]
    assert span.attributes is not None
    output_value = span.attributes[SpanAttributes.OUTPUT_VALUE]
    assert isinstance(output_value, str)
    assert json.loads(output_value) == {
        "classification": {"label": {"type": "str", "length": 8}},
    }


def test_subgraph_contract_run_spec_returns_projected_parent_output(
    span_exporter: InMemorySpanExporter,
) -> None:
    contract = SubgraphContract(
        parent_input=("request.text",),
        parent_output=("answer.text",),
        private_state_keys=("scratch",),
        owner_namespace="spec_answer_subgraph",
    )
    spec = subgraph_contract_run_spec(
        contract,
        span_kind="CHAIN",
        attributes={"graph.subgraph": contract.label},
        on_violation=ContractViolationAction.RAISE,
        logger=logging.getLogger("graphobs.langgraph"),
    )

    result = instrument_contract_run(
        spec,
        {"request": {"text": "hello", "raw": "hidden"}, "scratch": {"step": 1}},
        execute=lambda _run_input: {
            "request": {"text": "hello"},
            "answer": {"text": "done"},
            "scratch": {"step": 2},
        },
    )

    assert result == {"answer": {"text": "done"}}
    span = span_exporter.get_finished_spans()[0]
    assert span.attributes is not None
    output_value = span.attributes[SpanAttributes.OUTPUT_VALUE]
    assert isinstance(output_value, str)
    assert json.loads(output_value) == {
        "answer": {"text": {"type": "str", "length": 4}},
    }


def test_contract_node_invalid_call_logs_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.ERROR, logger="graphobs.langgraph")

    with pytest.raises(TypeError) as error:
        contract_node(cast(NodeContract, object()))

    assert str(error.value) in caplog.text
    assert "Failed to prepare contract node wrapper" in caplog.text


def test_contract_subgraph_projects_parent_boundary(
    span_exporter: InMemorySpanExporter,
) -> None:
    def answer(state: ExampleState) -> ExampleState:
        assert state == {"request": {"text": "hello"}, "scratch": {"note": "local"}}
        return {
            "answer": {"text": "hello back"},
            "scratch": {"note": "complete"},
        }

    subgraph = StateGraph(ExampleState)
    subgraph.add_node("answer", answer)
    subgraph.add_edge(START, "answer")
    subgraph.add_edge("answer", END)

    contract = SubgraphContract(
        parent_input=("request.text",),
        parent_output=("answer.text",),
        private_state_keys=("scratch",),
        owner_namespace="answer_subgraph",
    )
    parent_graph = StateGraph(ExampleState)
    wrapped_subgraph = contract_subgraph(subgraph.compile(), contract)

    def run_subgraph(state: ExampleState) -> ExampleState:
        return cast(ExampleState, wrapped_subgraph(state))

    parent_graph.add_node("answer_subgraph", run_subgraph)
    parent_graph.add_edge(START, "answer_subgraph")
    parent_graph.add_edge("answer_subgraph", END)

    result = parent_graph.compile().invoke(
        {
            "request": {"text": "hello", "raw": "hidden"},
            "scratch": {"note": "local"},
            "unexpected": "parent-only",
        }
    )

    assert result["answer"] == {"text": "hello back"}
    assert result["scratch"] == {"note": "local"}
    span = span_exporter.get_finished_spans()[0]
    assert span.name == "answer_subgraph"
    assert span.attributes is not None
    output_value = span.attributes[SpanAttributes.OUTPUT_VALUE]
    assert isinstance(output_value, str)
    # MESSAGE_COMPACT recurses into mappings; scalar strings become shape summaries.
    assert json.loads(output_value) == {
        "answer": {"text": {"type": "str", "length": 10}},
    }


def test_contract_subgraph_supports_async_invocation(
    span_exporter: InMemorySpanExporter,
) -> None:
    contract = SubgraphContract(
        parent_input=("request.text",),
        parent_output=("answer.text",),
        private_state_keys=("scratch",),
        owner_namespace="async_answer_subgraph",
    )
    wrapped = contract_subgraph(AsyncOnlyCompiledGraph(), contract)

    async def invoke_wrapped() -> MappingState:
        return await wrapped(
            {
                "request": {"text": "hello", "raw": "hidden"},
                "scratch": {"note": "local"},
            }
        )

    result = asyncio.run(invoke_wrapped())

    assert result == {"answer": {"text": "hello async"}}
    span = span_exporter.get_finished_spans()[0]
    assert span.name == "async_answer_subgraph"


def test_contract_subgraph_forwards_config_when_supported() -> None:
    compiled_graph = ConfigAwareCompiledGraph()
    contract = SubgraphContract(
        parent_input=("request.text",),
        parent_output=("answer.text",),
        owner_namespace="configured_subgraph",
    )
    wrapped = contract_subgraph(compiled_graph, contract)
    config = cast(RunnableConfig, {"metadata": {"request_id": "request-1"}})

    result = wrapped(
        {"request": {"text": "hello", "raw": "hidden"}},
        config=config,
    )

    assert result == {"answer": {"text": "configured"}}
    assert compiled_graph.received_config is config


def test_contract_subgraph_ignores_config_when_not_supported() -> None:
    contract = SubgraphContract(
        parent_input=("request.text",),
        parent_output=("answer.text",),
        owner_namespace="no_config_subgraph",
    )
    wrapped = contract_subgraph(NoConfigCompiledGraph(), contract)
    config = cast(RunnableConfig, {"metadata": {"request_id": "request-1"}})

    result = wrapped(
        {"request": {"text": "hello", "raw": "hidden"}},
        config=config,
    )

    assert result == {"answer": {"text": "no config"}}


def test_contract_subgraph_forwards_config_when_async_supported() -> None:
    compiled_graph = AsyncConfigAwareCompiledGraph()
    contract = SubgraphContract(
        parent_input=("request.text",),
        parent_output=("answer.text",),
        owner_namespace="async_configured_subgraph",
    )
    wrapped = contract_subgraph(compiled_graph, contract)
    config = cast(RunnableConfig, {"metadata": {"request_id": "request-1"}})

    async def invoke_wrapped() -> MappingState:
        return await wrapped(
            {"request": {"text": "hello", "raw": "hidden"}},
            config=config,
        )

    result = asyncio.run(invoke_wrapped())

    assert result == {"answer": {"text": "async config"}}
    assert compiled_graph.received_config is config


def test_contract_subgraph_missing_invoke_logs_original_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.ERROR, logger="graphobs.langgraph")
    contract = SubgraphContract(
        parent_input=("request.text",),
        parent_output=("answer.text",),
        owner_namespace="broken_subgraph",
    )
    wrapped = contract_subgraph(cast(InvokableGraph, object()), contract)

    with pytest.raises(AttributeError) as error:
        wrapped({"request": {"text": "hello"}})

    assert str(error.value) in caplog.text
    assert "Contract subgraph broken_subgraph failed" in caplog.text


def test_undeclared_node_write_logs_error_and_raises(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.ERROR, logger="graphobs.langgraph")

    def classify(state: MappingState) -> MappingState:
        return {"unexpected": "nope"}

    contract = NodeContract(name="classify", reads=("request.text",), writes=())
    wrapped = contract_node(classify, contract)

    with pytest.raises(StateContractError):
        wrapped({"request": {"text": "hello"}})

    assert "Contract node classify failed" in caplog.text
    assert "wrote undeclared state paths" in caplog.text


def test_undeclared_node_write_can_warn_and_continue(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="graphobs.contracts")

    def classify(state: MappingState) -> MappingState:
        return {"unexpected": "nope"}

    contract = NodeContract(name="classify", reads=("request.text",), writes=())
    wrapped = contract_node(
        classify,
        contract,
        on_violation=ContractViolationAction.WARN,
    )

    result = wrapped({"request": {"text": "hello"}})

    assert result == {"unexpected": "nope"}
    assert caplog.messages == [
        "Contract 'classify' wrote undeclared state paths: unexpected"
    ]


def test_node_exception_logs_error_and_records_span_failure(
    caplog: pytest.LogCaptureFixture,
    span_exporter: InMemorySpanExporter,
) -> None:
    caplog.set_level(logging.ERROR, logger="graphobs.langgraph")

    def failing_node(state: MappingState) -> MappingState:
        raise RuntimeError("synthetic node failure")

    contract = NodeContract(name="failing_node", reads=("request.text",), writes=())
    wrapped = contract_node(failing_node, contract)

    with pytest.raises(RuntimeError, match="synthetic node failure"):
        wrapped({"request": {"text": "hello"}})

    assert "Contract node failing_node failed: synthetic node failure" in caplog.text
    span = span_exporter.get_finished_spans()[0]
    assert span.attributes is not None
    assert span.attributes["error.type"] == "RuntimeError"


def test_langgraph_input_schema_and_add_contract_node() -> None:
    def classify(state: MappingState) -> MappingState:
        return {"classification": {"label": "greeting"}}

    contract = NodeContract(
        name="classify",
        reads=("request.text",),
        writes=("classification.label",),
    )
    schema = langgraph_input_schema(contract)
    graph = StateGraph(ExampleState)

    assert schema is not None
    returned_graph = add_contract_node(graph, contract, classify)

    assert returned_graph is graph


def test_add_contract_node_omits_input_schema_for_pass_through_state() -> None:
    def classify(state: MappingState) -> MappingState:
        return {"classification": {"label": str(state["request"])}}

    contract = NodeContract(
        name="classify_passthrough_schema",
        reads=("request.text",),
        writes=("classification.label",),
    )
    graph = _RecordingGraph()

    returned_graph = add_contract_node(
        graph,
        contract,
        classify,
        pass_through_state=True,
    )

    assert returned_graph is graph
    assert len(graph.calls) == 1
    call = graph.calls[0]
    assert call["kwargs"] == {}
    args = cast(tuple[object, ...], call["args"])
    assert args[0] == "classify_passthrough_schema"
    assert callable(args[1])


def test_langgraph_input_schema_includes_subgraph_private_state() -> None:
    contract = SubgraphContract(
        parent_input=("request.text",),
        parent_output=("answer.text",),
        private_state_keys=("scratch",),
        owner_namespace="answer_subgraph",
    )

    schema = langgraph_input_schema(contract)

    assert schema is not None
    assert schema.__name__ == "AnswerSubgraphInput"
    assert schema.__annotations__ == {"request": object, "scratch": object}


def test_open_projection_schema_logs_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="graphobs.langgraph")

    contract = NodeContract(name="open_reader", reads=ProjectionPolicy(), writes=())

    assert langgraph_input_schema(contract) is None
    assert caplog.records[0].levelno == logging.WARNING
    assert caplog.messages == [
        "Could not build LangGraph input schema for open_reader: "
        "open-ended projection cannot be represented"
    ]


MappingState = Mapping[str, object]


class _RecordingGraph:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def add_node(self, *args: object, **kwargs: object) -> object:
        self.calls.append({"args": args, "kwargs": kwargs})
        return self
