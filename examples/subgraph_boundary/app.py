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
)
from graph_observability_kit.contracts.models import SubgraphContract
from graph_observability_kit.langgraph.subgraphs import contract_subgraph
from graph_observability_kit.tracing import (
    TracePayloadMode,
    set_span_output,
    start_graph_span,
)


class BoundaryState(TypedDict, total=False):
    request: dict[str, object]
    documents: list[dict[str, object]]
    answer: dict[str, object]
    scratch: dict[str, object]


INITIAL_STATE: BoundaryState = {
    "request": {
        "text": "Find notes about graph boundaries",
        "raw_notes": "raw parent request notes",
    },
    "scratch": {"query_plan": "draft retriever plan"},
}


def plan_query(state: MappingState) -> dict[str, object]:
    text = _request_text(state)
    terms = [word.lower() for word in text.split() if len(word) > 4]
    return {"scratch": {"terms": terms, "candidate_count": 2}}


def fetch_documents(state: MappingState) -> dict[str, object]:
    scratch = state.get("scratch", {})
    terms = scratch.get("terms", []) if isinstance(scratch, Mapping) else []
    return {
        "documents": [
            {
                "title": "Boundary Guide",
                "summary": f"Retriever terms: {', '.join(map(str, terms[:2]))}",
            }
        ],
        "scratch": {"terms": terms, "candidate_count": 1, "raw_rank_notes": "local"},
    }


def answer_from_documents(state: MappingState) -> dict[str, object]:
    documents = state.get("documents", [])
    if isinstance(documents, list) and documents:
        first = documents[0]
        title = first.get("title", "document") if isinstance(first, Mapping) else ""
    else:
        title = "no document"
    return {"answer": {"text": f"Answered from {title}"}}


def build_retriever_subgraph() -> StateGraph[
    BoundaryState, None, BoundaryState, BoundaryState
]:
    graph = StateGraph(BoundaryState)
    add_raw_node(graph, "plan_query", plan_query)
    add_raw_node(graph, "fetch_documents", fetch_documents)
    graph.add_edge(START, "plan_query")
    graph.add_edge("plan_query", "fetch_documents")
    graph.add_edge("fetch_documents", END)
    return graph


def build_raw_parent_graph() -> StateGraph[
    BoundaryState, None, BoundaryState, BoundaryState
]:
    retriever = build_retriever_subgraph().compile()

    def run_retriever(state: BoundaryState) -> BoundaryState:
        return cast(BoundaryState, dict(retriever.invoke(state)))

    graph = StateGraph(BoundaryState)
    add_raw_node(graph, "raw_retriever_subgraph", run_retriever)
    add_raw_node(graph, "answer_from_documents", answer_from_documents)
    graph.add_edge(START, "raw_retriever_subgraph")
    graph.add_edge("raw_retriever_subgraph", "answer_from_documents")
    graph.add_edge("answer_from_documents", END)
    return graph


def build_contract_parent_graph() -> StateGraph[
    BoundaryState, None, BoundaryState, BoundaryState
]:
    contract = SubgraphContract(
        parent_input=("request.text",),
        parent_output=("documents",),
        private_state_keys=("scratch",),
        owner_namespace="retriever_subgraph",
    )
    wrapped_retriever = contract_subgraph(
        build_retriever_subgraph().compile(), contract
    )

    graph = StateGraph(BoundaryState)
    add_raw_node(graph, "retriever_subgraph", wrapped_retriever)
    add_contract_node(
        graph,
        NodeContract(
            name="answer_from_documents",
            reads=("documents",),
            writes=("answer.text",),
            span_kind="CHAIN",
        ),
        answer_from_documents,
    )
    graph.add_edge(START, "retriever_subgraph")
    graph.add_edge("retriever_subgraph", "answer_from_documents")
    graph.add_edge("answer_from_documents", END)
    return graph


def build_payload() -> dict[str, object]:
    exporter = configure_tracing()

    with start_graph_span(
        "raw_subgraph_boundary",
        "CHAIN",
        input=INITIAL_STATE,
        mode=TracePayloadMode.FULL,
    ) as span:
        raw_result = (
            build_raw_parent_graph()
            .compile()
            .invoke(cast(BoundaryState, dict(INITIAL_STATE)))
        )
        set_span_output(span, raw_result, mode=TracePayloadMode.FULL)
    raw_spans = span_records(exporter)

    exporter.clear()
    contract_result = (
        build_contract_parent_graph()
        .compile()
        .invoke(cast(BoundaryState, dict(INITIAL_STATE)))
    )
    contract_spans = span_records(exporter)

    exporter.clear()
    validation_error = capture_validation_error(_run_bad_subgraph)
    validation_spans = span_records(exporter)

    return {
        "example": "subgraph_boundary",
        "raw": {
            "answer": raw_result["answer"],
            "scratch": raw_result["scratch"],
            "spans": raw_spans,
        },
        "contract_wrapped": {
            "answer": contract_result["answer"],
            "scratch": contract_result["scratch"],
            "spans": contract_spans,
        },
        "validation": {
            "error": validation_error,
            "spans": validation_spans,
        },
        "logs": lifecycle_log_records(
            run_name="subgraph_boundary_contract",
            input_value=INITIAL_STATE,
            output_value=contract_result,
        ),
    }


def main() -> None:
    print_json(build_payload())


def _run_bad_subgraph() -> None:
    class BadRetrieverGraph:
        def invoke(self, state: MappingState) -> MappingState:
            return {
                "request": state["request"],
                "documents": [],
                "scratch": state["scratch"],
                "metrics": {"candidate_count": 2},
            }

    wrapped = contract_subgraph(
        BadRetrieverGraph(),
        SubgraphContract(
            parent_input=("request.text",),
            parent_output=("documents",),
            private_state_keys=("scratch",),
            owner_namespace="bad_retriever_subgraph",
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
