from __future__ import annotations

from collections.abc import Mapping
from typing import TypedDict, cast

from langgraph.graph import END, START, StateGraph

from examples._support import (
    MappingState,
    add_raw_node,
    capture_validation_error,
    configure_tracing,
    lifecycle_log_records,
    print_json,
    span_records,
)
from graph_observability_kit import (
    NodeContract,
    add_contract_node,
    contract_node,
)
from graph_observability_kit.tracing import (
    TracePayloadMode,
    set_span_output,
    start_graph_span,
)


class ToolState(TypedDict, total=False):
    request: dict[str, object]
    tool_call: dict[str, object]
    tool_result: dict[str, object]
    answer: dict[str, object]
    scratch: dict[str, object]


class ToolArguments(TypedDict):
    term: str


class ToolCall(TypedDict):
    name: str
    arguments: ToolArguments


INITIAL_STATE: ToolState = {
    "request": {
        "text": "Look up the blue notebook",
        "raw_notes": "raw tool request notes",
    },
    "scratch": {"loop_step": 0},
}


def decide_tool(state: MappingState) -> dict[str, object]:
    text = _request_text(state)
    term = text.lower().replace("look up the", "").strip()
    return {
        "tool_call": {
            "name": "lookup_catalog",
            "arguments": {"term": term or "notebook"},
        },
        "scratch": {"loop_step": 1},
    }


def run_tool_raw(state: MappingState) -> dict[str, object]:
    tool_call = _tool_call(state)
    with start_graph_span(
        "raw_lookup_catalog",
        "TOOL",
        input=tool_call,
        attributes={"tool.name": "lookup_catalog", "tool.iteration": 1},
        mode=TracePayloadMode.FULL,
    ) as span:
        result = lookup_catalog(tool_call["arguments"]["term"])
        set_span_output(span, result, mode=TracePayloadMode.FULL)
    return {"tool_result": result, "scratch": {"loop_step": 2}}


def run_tool_contract(state: MappingState) -> dict[str, object]:
    tool_call = _tool_call(state)
    result = lookup_catalog(tool_call["arguments"]["term"])
    return {"tool_result": {"matches": result["matches"]}, "scratch": {"loop_step": 2}}


def final_answer(state: MappingState) -> dict[str, object]:
    tool_result = state.get("tool_result", {})
    matches = tool_result.get("matches", []) if isinstance(tool_result, Mapping) else []
    if isinstance(matches, list) and matches:
        first = matches[0]
        title = first.get("title", "item") if isinstance(first, Mapping) else "item"
    else:
        title = "item"
    return {"answer": {"text": f"Tool result selected: {title}"}}


def lookup_catalog(term: str) -> dict[str, object]:
    return {
        "matches": [
            {"title": "Blue Notebook", "sku": "demo-001"},
            {"title": "Graph Notebook", "sku": "demo-002"},
        ],
        "raw_payload": f"local catalog response for {term}",
    }


def build_raw_graph() -> StateGraph[ToolState, None, ToolState, ToolState]:
    graph = StateGraph(ToolState)
    add_raw_node(graph, "decide_tool", decide_tool)
    add_raw_node(graph, "run_tool", run_tool_raw)
    add_raw_node(graph, "final_answer", final_answer)
    graph.add_edge(START, "decide_tool")
    graph.add_edge("decide_tool", "run_tool")
    graph.add_edge("run_tool", "final_answer")
    graph.add_edge("final_answer", END)
    return graph


def build_contract_graph() -> StateGraph[ToolState, None, ToolState, ToolState]:
    graph = StateGraph(ToolState)
    add_contract_node(
        graph,
        NodeContract(
            name="decide_tool",
            reads=("request.text",),
            writes=("tool_call.name", "tool_call.arguments"),
            private_writes=("scratch.loop_step",),
            span_kind="CHAIN",
        ),
        decide_tool,
    )
    add_contract_node(
        graph,
        NodeContract(
            name="run_tool",
            reads=("tool_call.name", "tool_call.arguments"),
            writes=("tool_result.matches",),
            private_reads=("scratch.loop_step",),
            private_writes=("scratch.loop_step",),
            span_kind="TOOL",
            attributes={"tool.name": "lookup_catalog", "tool.iteration": 1},
        ),
        run_tool_contract,
    )
    add_contract_node(
        graph,
        NodeContract(
            name="final_answer",
            reads=("tool_result.matches",),
            writes=("answer.text",),
            span_kind="CHAIN",
        ),
        final_answer,
    )
    graph.add_edge(START, "decide_tool")
    graph.add_edge("decide_tool", "run_tool")
    graph.add_edge("run_tool", "final_answer")
    graph.add_edge("final_answer", END)
    return graph


def build_payload() -> dict[str, object]:
    exporter = configure_tracing()

    with start_graph_span(
        "raw_tool_agent",
        "CHAIN",
        input=INITIAL_STATE,
        mode=TracePayloadMode.FULL,
    ) as span:
        raw_result = (
            build_raw_graph().compile().invoke(cast(ToolState, dict(INITIAL_STATE)))
        )
        set_span_output(span, raw_result, mode=TracePayloadMode.FULL)
    raw_spans = span_records(exporter)

    exporter.clear()
    contract_result = (
        build_contract_graph().compile().invoke(cast(ToolState, dict(INITIAL_STATE)))
    )
    contract_spans = span_records(exporter)

    exporter.clear()
    validation_error = capture_validation_error(_run_bad_tool)
    validation_spans = span_records(exporter)

    return {
        "example": "tool_agent",
        "raw": {
            "answer": raw_result["answer"],
            "spans": raw_spans,
        },
        "contract_wrapped": {
            "answer": contract_result["answer"],
            "spans": contract_spans,
        },
        "validation": {
            "error": validation_error,
            "spans": validation_spans,
        },
        "logs": lifecycle_log_records(
            run_name="tool_agent_contract",
            input_value=INITIAL_STATE,
            output_value=contract_result,
        ),
    }


def main() -> None:
    print_json(build_payload())


def _run_bad_tool() -> None:
    def bad_tool(state: MappingState) -> dict[str, object]:
        return {
            "tool_result": {"matches": []},
            "debug": {"raw_tool_response": "unexpected"},
        }

    wrapped = contract_node(
        bad_tool,
        NodeContract(
            name="bad_tool",
            reads=("tool_call.name", "tool_call.arguments"),
            writes=("tool_result.matches",),
            span_kind="TOOL",
        ),
    )
    wrapped({"tool_call": {"name": "lookup_catalog", "arguments": {"term": "demo"}}})


def _request_text(state: MappingState) -> str:
    request = state.get("request", {})
    if isinstance(request, Mapping):
        return str(request.get("text", ""))
    return ""


def _tool_call(state: MappingState) -> ToolCall:
    tool_call = state.get("tool_call", {})
    if isinstance(tool_call, Mapping):
        arguments = tool_call.get("arguments", {})
        if isinstance(arguments, Mapping):
            return {
                "name": str(tool_call.get("name", "lookup_catalog")),
                "arguments": {"term": str(arguments.get("term", "notebook"))},
            }
    return {"name": "lookup_catalog", "arguments": {"term": "notebook"}}


if __name__ == "__main__":
    main()
