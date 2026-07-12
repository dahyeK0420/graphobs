from __future__ import annotations

import asyncio
import json
import logging
import operator
from collections.abc import Mapping
from typing import Annotated, TypedDict, cast

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.runtime import Runtime
from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore
from openinference.semconv.trace import SpanAttributes
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from graphobs.contracts.models import (
    NodeContract,
    ProjectionPolicy,
    StateContractError,
    SubgraphContract,
)
from graphobs.langgraph.nodes import (
    NodeContractMode,
    add_contract_node,
    add_contract_nodes,
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
    wrapped = contract_node(classify, contract, mode=NodeContractMode.OBSERVE)

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
        mode=NodeContractMode.AUDIT,
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
        mode=NodeContractMode.AUDIT,
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
        mode=NodeContractMode.AUDIT,
    )

    async def invoke_wrapped() -> MappingState:
        return await wrapped({"request": {"text": "hello", "raw": "hidden"}})

    result = asyncio.run(invoke_wrapped())

    assert result == {"classification": {"label": "hello"}}
    assert caplog.messages == [
        "Contract 'async_passthrough_audit' read undeclared state paths: request.raw"
    ]


def test_contract_node_strict_mode_allows_declared_reads() -> None:
    def classify(state: MappingState) -> MappingState:
        request = state["request"]
        assert isinstance(request, Mapping)
        return {"classification": {"label": str(request["text"])}}

    contract = NodeContract(
        name="classify_declared",
        reads=("request.text",),
        writes=("classification.label",),
    )
    wrapped = contract_node(classify, contract)

    result = wrapped({"request": {"text": "hello", "raw": "hidden"}})

    assert result == {"classification": {"label": "hello"}}


def test_contract_node_strict_mode_raises_for_undeclared_read() -> None:
    def classify(state: MappingState) -> MappingState:
        # Reading a path the contract did not declare must not silently return
        # a default; strict execution should fail loudly instead.
        fallback = state.get("context", {})
        assert isinstance(fallback, Mapping)
        return {"classification": {"label": "greeting"}}

    contract = NodeContract(
        name="classify_strict_read",
        reads=("request.text",),
        writes=("classification.label",),
    )
    wrapped = contract_node(classify, contract)

    with pytest.raises(StateContractError) as error:
        wrapped({"request": {"text": "hello"}, "context": {"fallback": "x"}})

    assert error.value.access == "read"
    assert error.value.undeclared_paths == ("context",)


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


def test_contract_node_returns_raw_update_and_projects_span_output(
    span_exporter: InMemorySpanExporter,
) -> None:
    contract = NodeContract(
        name="spec_classify",
        reads=("request.text",),
        writes=("classification.label",),
        private_writes=("scratch.step",),
    )

    def classify(_state: MappingState) -> MappingState:
        return {"classification": {"label": "greeting"}, "scratch": {"step": 1}}

    wrapped = contract_node(classify, contract)
    result = wrapped({"request": {"text": "hello", "raw": "hidden"}})

    assert result == {"classification": {"label": "greeting"}, "scratch": {"step": 1}}
    span = span_exporter.get_finished_spans()[0]
    assert span.attributes is not None
    output_value = span.attributes[SpanAttributes.OUTPUT_VALUE]
    assert isinstance(output_value, str)
    assert json.loads(output_value) == {
        "classification": {"label": {"type": "str", "length": 8}},
    }


def test_contract_subgraph_returns_projected_parent_output(
    span_exporter: InMemorySpanExporter,
) -> None:
    contract = SubgraphContract(
        parent_input=("request.text",),
        parent_output=("answer.text",),
        private_state_keys=("scratch",),
        owner_namespace="spec_answer_subgraph",
    )

    class _Subgraph:
        def invoke(self, _input: MappingState) -> MappingState:
            return {
                "request": {"text": "hello"},
                "answer": {"text": "done"},
                "scratch": {"step": 2},
            }

    wrapped = contract_subgraph(cast(InvokableGraph, _Subgraph()), contract)
    result = wrapped(
        {"request": {"text": "hello", "raw": "hidden"}, "scratch": {"step": 1}}
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
        mode=NodeContractMode.OBSERVE,
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


def test_add_contract_node_omits_input_schema_for_observe_mode() -> None:
    def classify(state: MappingState) -> MappingState:
        return {"classification": {"label": str(state["request"])}}

    contract = NodeContract(
        name="classify_observe_schema",
        reads=("request.text",),
        writes=("classification.label",),
    )
    graph = _RecordingGraph()

    returned_graph = add_contract_node(
        graph,
        contract,
        classify,
        mode=NodeContractMode.OBSERVE,
    )

    assert returned_graph is graph
    assert len(graph.calls) == 1
    call = graph.calls[0]
    assert call["kwargs"] == {}
    args = cast(tuple[object, ...], call["args"])
    assert args[0] == "classify_observe_schema"
    assert callable(args[1])


def test_add_contract_nodes_registers_every_node_in_order() -> None:
    def classify(state: MappingState) -> MappingState:
        return {"classification": {"label": "greeting"}}

    def answer(state: MappingState) -> MappingState:
        return {"answer": {"text": "done"}}

    classify_contract = NodeContract(
        name="classify",
        reads=("request.text",),
        writes=("classification.label",),
    )
    answer_contract = NodeContract(
        name="answer",
        reads=("classification.label",),
        writes=("answer.text",),
    )
    graph = _RecordingGraph()

    results = add_contract_nodes(
        graph,
        [(classify_contract, classify), (answer_contract, answer)],
        mode=NodeContractMode.OBSERVE,
    )

    assert results == (graph, graph)
    registered_names = [
        cast(tuple[object, ...], call["args"])[0] for call in graph.calls
    ]
    assert registered_names == ["classify", "answer"]
    assert all(call["kwargs"] == {} for call in graph.calls)


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


class ReducerChatState(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], add_messages]


class AccumulatorState(TypedDict, total=False):
    events: Annotated[list[str], operator.add]


def _append_ai_turn(state: MappingState) -> MappingState:
    return {"messages": [AIMessage(content="assistant turn")]}


def _emit_event(state: AccumulatorState) -> AccumulatorState:
    return {"events": ["from_inner"]}


def test_contract_node_preserves_add_messages_reducer() -> None:
    graph = StateGraph(ReducerChatState)
    add_contract_node(
        graph,
        NodeContract(name="reply", reads=("messages",), writes=("messages",)),
        _append_ai_turn,
    )
    graph.add_edge(START, "reply")
    graph.add_edge("reply", END)

    result = graph.compile().invoke({"messages": [HumanMessage(content="hello")]})

    messages = result["messages"]
    assert [type(message).__name__ for message in messages] == [
        "HumanMessage",
        "AIMessage",
    ]
    assert [message.content for message in messages] == ["hello", "assistant turn"]


def test_contract_node_preserves_accumulating_reducer() -> None:
    graph = StateGraph(AccumulatorState)
    add_contract_node(
        graph,
        NodeContract(name="emit", reads=("events",), writes=("events",)),
        _emit_event,
    )
    graph.add_edge(START, "emit")
    graph.add_edge("emit", END)

    result = graph.compile().invoke({"events": ["seed"]})

    assert result["events"] == ["seed", "from_inner"]


def test_contract_subgraph_preserves_last_value_wins_channel() -> None:
    # Default (last-value-wins) channels are the supported subgraph case: the
    # wrapper returns the projected value and the parent overwrites it once.
    inner = StateGraph(ExampleState)
    inner.add_node("produce", lambda state: {"answer": {"text": "from subgraph"}})
    inner.add_edge(START, "produce")
    inner.add_edge("produce", END)

    subgraph = contract_subgraph(
        inner.compile(),
        SubgraphContract(
            parent_input=("request.text",),
            parent_output=("answer.text",),
            owner_namespace="worker",
        ),
    )

    result = subgraph({"request": {"text": "hello"}, "answer": {"text": "old"}})

    assert result == {"answer": {"text": "from subgraph"}}


def test_contract_subgraph_does_not_support_accumulating_reducers() -> None:
    # Documented limitation: contract_subgraph cannot see the parent graph's
    # channel reducers, so it returns the subgraph's full accumulated value.
    # Under a non-deduplicating accumulating reducer the parent re-applies it,
    # doubling the seeded input. Use a node-level contract for such channels.
    inner = StateGraph(AccumulatorState)
    inner.add_node("emit", _emit_event)
    inner.add_edge(START, "emit")
    inner.add_edge("emit", END)

    parent = StateGraph(AccumulatorState)
    parent.add_node(
        "worker",
        contract_subgraph(
            inner.compile(),
            SubgraphContract(
                parent_input=("events",),
                parent_output=("events",),
                owner_namespace="worker",
            ),
        ),
    )
    parent.add_edge(START, "worker")
    parent.add_edge("worker", END)

    result = parent.compile().invoke({"events": ["seed"]})

    # "seed" appears twice: once from the parent channel, once returned by the
    # subgraph. This pins the documented limitation, not desired behavior.
    assert result["events"] == ["seed", "seed", "from_inner"]


def test_contract_node_empty_reads_grants_no_public_state() -> None:
    # Omitting reads declares an empty boundary (not "all state"). A strict node
    # that then reads state fails loudly instead of silently seeing nothing.
    def classify(state: MappingState) -> MappingState:
        state.get("request")
        return {"classification": {"label": "greeting"}}

    contract = NodeContract(
        name="classify_no_reads",
        writes=("classification.label",),
    )
    wrapped = contract_node(classify, contract)

    with pytest.raises(StateContractError) as error:
        wrapped({"request": {"text": "hello"}})

    assert error.value.access == "read"
    assert error.value.undeclared_paths == ("request",)
