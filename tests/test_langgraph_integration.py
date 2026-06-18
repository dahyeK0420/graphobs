from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Mapping
from typing import TypedDict, cast

import pytest
from langgraph.graph import END, START, StateGraph
from openinference.semconv.trace import SpanAttributes
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from graph_observability_kit.contracts import (
    NodeContract,
    ProjectionPolicy,
    StateContractError,
    SubgraphContract,
)
from graph_observability_kit.langgraph import (
    InvokableGraph,
    add_contract_node,
    contract_node,
    contract_subgraph,
    langgraph_input_schema,
)


class ExampleState(TypedDict, total=False):
    request: dict[str, object]
    classification: dict[str, object]
    answer: dict[str, object]
    scratch: dict[str, object]
    unexpected: str


class AsyncOnlyCompiledGraph:
    async def ainvoke(self, input: MappingState) -> MappingState:
        await asyncio.sleep(0)
        assert input == {"request": {"text": "hello"}, "scratch": {"note": "local"}}
        return {
            "request": {"text": "hello"},
            "answer": {"text": "hello async"},
            "scratch": {"note": "complete"},
        }


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


def test_contract_node_invalid_call_logs_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.ERROR, logger="graph_observability_kit.langgraph")

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
    assert json.loads(output_value) == {
        "keys": ["answer"],
        "size": 1,
        "type": "mapping",
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


def test_contract_subgraph_missing_invoke_logs_original_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.ERROR, logger="graph_observability_kit.langgraph")
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
    caplog.set_level(logging.ERROR, logger="graph_observability_kit.langgraph")

    def classify(state: MappingState) -> MappingState:
        return {"unexpected": "nope"}

    contract = NodeContract(name="classify", reads=("request.text",), writes=())
    wrapped = contract_node(classify, contract)

    with pytest.raises(StateContractError):
        wrapped({"request": {"text": "hello"}})

    assert "Contract node classify failed" in caplog.text
    assert "wrote undeclared state paths" in caplog.text


def test_node_exception_logs_error_and_records_span_failure(
    caplog: pytest.LogCaptureFixture,
    span_exporter: InMemorySpanExporter,
) -> None:
    caplog.set_level(logging.ERROR, logger="graph_observability_kit.langgraph")

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
    caplog.set_level(logging.WARNING, logger="graph_observability_kit.langgraph")

    contract = NodeContract(name="open_reader", reads=ProjectionPolicy(), writes=())

    assert langgraph_input_schema(contract) is None
    assert caplog.records[0].levelno == logging.WARNING
    assert caplog.messages == [
        "Could not build LangGraph input schema for open_reader: "
        "open-ended projection cannot be represented"
    ]


MappingState = Mapping[str, object]
