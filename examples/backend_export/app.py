from __future__ import annotations

import io
import json
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
from graphobs import (
    NodeContract,
    add_contract_node,
    contract_node,
)
from graphobs.tracing import (
    TracePayloadMode,
    set_span_output,
    start_graph_span,
)


class ExportState(TypedDict, total=False):
    request: dict[str, object]
    answer: dict[str, object]
    scratch: dict[str, object]


INITIAL_STATE: ExportState = {
    "request": {
        "text": "Show a local exporter",
        "raw_notes": "raw exporter setup notes",
    },
    "scratch": {"preview": "console exporter dry run"},
}


def prepare_answer(state: MappingState) -> dict[str, object]:
    text = _request_text(state)
    return {"answer": {"text": f"Local export prepared for: {text}"}}


def build_raw_graph() -> StateGraph[ExportState, None, ExportState, ExportState]:
    graph = StateGraph(ExportState)
    add_raw_node(graph, "prepare_answer", prepare_answer)
    graph.add_edge(START, "prepare_answer")
    graph.add_edge("prepare_answer", END)
    return graph


def build_contract_graph() -> StateGraph[ExportState, None, ExportState, ExportState]:
    graph = StateGraph(ExportState)
    add_contract_node(
        graph,
        NodeContract(
            name="prepare_answer",
            reads=("request.text",),
            writes=("answer.text",),
            span_kind="CHAIN",
        ),
        prepare_answer,
    )
    graph.add_edge(START, "prepare_answer")
    graph.add_edge("prepare_answer", END)
    return graph


def build_payload() -> dict[str, object]:
    console_stream = io.StringIO()
    exporter = configure_tracing(console_stream=console_stream)

    with start_graph_span(
        "raw_backend_export",
        "CHAIN",
        input=INITIAL_STATE,
        mode=TracePayloadMode.FULL,
    ) as span:
        raw_result = (
            build_raw_graph().compile().invoke(cast(ExportState, dict(INITIAL_STATE)))
        )
        set_span_output(span, raw_result, mode=TracePayloadMode.FULL)
    raw_spans = span_records(exporter)

    exporter.clear()
    contract_result = (
        build_contract_graph().compile().invoke(cast(ExportState, dict(INITIAL_STATE)))
    )
    contract_spans = span_records(exporter)
    console_lines = cast(
        list[dict[str, object]],
        [json.loads(line) for line in console_stream.getvalue().splitlines()],
    )

    exporter.clear()
    validation_error = capture_validation_error(_run_bad_export_node)
    validation_spans = span_records(exporter)

    return {
        "example": "backend_export",
        "backend_setup": {
            "exporters": ["InMemorySpanExporter", "ConsoleSpanExporter"],
            "span_processor": "SimpleSpanProcessor",
            "network": "none",
        },
        "raw": {
            "answer": raw_result["answer"],
            "spans": raw_spans,
        },
        "contract_wrapped": {
            "answer": contract_result["answer"],
            "spans": contract_spans,
        },
        "console_exporter_lines": console_lines,
        "validation": {
            "error": validation_error,
            "spans": validation_spans,
        },
        "logs": lifecycle_log_records(
            run_name="backend_export_contract",
            input_value=INITIAL_STATE,
            output_value=contract_result,
        ),
    }


def main() -> None:
    print_json(build_payload())


def _run_bad_export_node() -> None:
    def bad_export_node(state: MappingState) -> dict[str, object]:
        return {"answer": {"text": "ok"}, "transport": {"target": "unexpected"}}

    wrapped = contract_node(
        bad_export_node,
        NodeContract(
            name="bad_export_node",
            reads=("request.text",),
            writes=("answer.text",),
            span_kind="CHAIN",
        ),
    )
    wrapped(INITIAL_STATE)


def _request_text(state: MappingState) -> str:
    request = state.get("request", {})
    if isinstance(request, Mapping):
        return str(request.get("text", ""))
    return ""


if __name__ == "__main__":
    main()
