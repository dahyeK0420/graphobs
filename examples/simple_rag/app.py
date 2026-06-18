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


class RagState(TypedDict, total=False):
    request: dict[str, object]
    classification: dict[str, object]
    documents: list[dict[str, object]]
    answer: dict[str, object]
    scratch: dict[str, object]


DOCUMENTS = [
    {
        "title": "Observability Notes",
        "summary": "Contracts keep trace payloads focused.",
        "body": "Synthetic document body for local examples only.",
    },
    {
        "title": "Graph Debugging",
        "summary": "Logs, traces, and state answer different questions.",
        "body": "Another invented document body.",
    },
]

INITIAL_STATE: RagState = {
    "request": {
        "text": "How do contracts improve graph traces?",
        "raw_notes": "raw request notes stay out of contract spans",
    },
    "scratch": {"draft_query": "contract graph trace payload boundaries"},
}


def classify_intent(state: MappingState) -> dict[str, object]:
    text = _request_text(state)
    intent = "question" if "?" in text else "statement"
    return {"classification": {"intent": intent}}


def retrieve_docs(state: MappingState) -> dict[str, object]:
    text = _request_text(state).lower()
    matching_docs = [
        {"title": doc["title"], "summary": doc["summary"]}
        for doc in DOCUMENTS
        if "trace" in text or "contract" in text
    ]
    return {"documents": matching_docs[:2]}


def answer_question(state: MappingState) -> dict[str, object]:
    documents = state.get("documents", [])
    if isinstance(documents, list) and documents:
        first = documents[0]
        summary = (
            first.get("summary", "No summary") if isinstance(first, Mapping) else ""
        )
    else:
        summary = "No matching documents"
    return {"answer": {"text": f"Answer from synthetic docs: {summary}"}}


def build_raw_graph() -> StateGraph[RagState, None, RagState, RagState]:
    graph = StateGraph(RagState)
    add_raw_node(graph, "classify_intent", classify_intent)
    add_raw_node(graph, "retrieve_docs", retrieve_docs)
    add_raw_node(graph, "answer_question", answer_question)
    graph.add_edge(START, "classify_intent")
    graph.add_edge("classify_intent", "retrieve_docs")
    graph.add_edge("retrieve_docs", "answer_question")
    graph.add_edge("answer_question", END)
    return graph


def build_contract_graph() -> StateGraph[RagState, None, RagState, RagState]:
    graph = StateGraph(RagState)
    add_contract_node(
        graph,
        NodeContract(
            name="classify_intent",
            reads=("request.text",),
            writes=("classification.intent",),
            span_kind="CHAIN",
        ),
        classify_intent,
    )
    add_contract_node(
        graph,
        NodeContract(
            name="retrieve_docs",
            reads=("request.text", "classification.intent"),
            writes=("documents",),
            span_kind="RETRIEVER",
        ),
        retrieve_docs,
    )
    add_contract_node(
        graph,
        NodeContract(
            name="answer_question",
            reads=("request.text", "documents"),
            writes=("answer.text",),
            span_kind="CHAIN",
        ),
        answer_question,
    )
    graph.add_edge(START, "classify_intent")
    graph.add_edge("classify_intent", "retrieve_docs")
    graph.add_edge("retrieve_docs", "answer_question")
    graph.add_edge("answer_question", END)
    return graph


def build_payload() -> dict[str, object]:
    exporter = configure_tracing()

    with start_graph_span(
        "raw_simple_rag",
        "CHAIN",
        input=INITIAL_STATE,
        mode=TracePayloadMode.FULL,
    ) as span:
        raw_result = (
            build_raw_graph().compile().invoke(cast(RagState, dict(INITIAL_STATE)))
        )
        set_span_output(span, raw_result, mode=TracePayloadMode.FULL)
    raw_spans = span_records(exporter)

    exporter.clear()
    contract_result = (
        build_contract_graph().compile().invoke(cast(RagState, dict(INITIAL_STATE)))
    )
    contract_spans = span_records(exporter)

    exporter.clear()
    validation_error = capture_validation_error(_run_bad_retriever)
    validation_spans = span_records(exporter)

    return {
        "example": "simple_rag",
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
            run_name="simple_rag_contract",
            input_value=INITIAL_STATE,
            output_value=contract_result,
        ),
    }


def main() -> None:
    print_json(build_payload())


def _run_bad_retriever() -> None:
    def bad_retriever(state: MappingState) -> dict[str, object]:
        return {"documents": [], "debug": {"query": "unexpected"}}

    wrapped = contract_node(
        bad_retriever,
        NodeContract(
            name="bad_retriever",
            reads=("request.text",),
            writes=("documents",),
            span_kind="RETRIEVER",
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
