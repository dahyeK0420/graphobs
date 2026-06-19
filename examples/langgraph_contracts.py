from __future__ import annotations

from collections.abc import Mapping
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from graphobs import NodeContract, add_contract_node

MappingState = Mapping[str, object]


class AppState(TypedDict, total=False):
    request: dict[str, object]
    classification: dict[str, object]
    answer: dict[str, object]
    scratch: dict[str, object]


def classify(state: MappingState) -> dict[str, object]:
    request = state.get("request", {})
    text = request.get("text", "") if isinstance(request, dict) else ""
    label = "question" if "?" in str(text) else "statement"
    return {"classification": {"label": label}}


def answer(state: MappingState) -> dict[str, object]:
    classification = state.get("classification", {})
    label = (
        classification.get("label", "statement")
        if isinstance(classification, dict)
        else "statement"
    )
    return {"answer": {"text": f"handled {label}"}}


def build_graph() -> StateGraph[AppState, None, AppState, AppState]:
    graph = StateGraph(AppState)
    add_contract_node(
        graph,
        NodeContract(
            name="classify",
            reads=("request.text",),
            writes=("classification.label",),
        ),
        classify,
    )
    add_contract_node(
        graph,
        NodeContract(
            name="answer",
            reads=("classification.label",),
            writes=("answer.text",),
        ),
        answer,
    )
    graph.add_edge(START, "classify")
    graph.add_edge("classify", "answer")
    graph.add_edge("answer", END)
    return graph


def main() -> None:
    compiled = build_graph().compile()
    result = compiled.invoke({"request": {"text": "Can you help?"}})
    print(result["answer"])


if __name__ == "__main__":
    main()
