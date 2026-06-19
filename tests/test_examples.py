from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import cast

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = (
    "simple_rag",
    "subgraph_boundary",
    "tool_agent",
    "backend_export",
)
EXPECTED_CONTRACT_SPANS = {
    "simple_rag": ["classify_intent", "retrieve_docs", "answer_question"],
    "subgraph_boundary": ["retriever_subgraph", "answer_from_documents"],
    "tool_agent": ["decide_tool", "run_tool", "final_answer"],
    "backend_export": ["prepare_answer"],
}
RAW_MARKERS = {
    "simple_rag": "raw request notes stay out of contract spans",
    "subgraph_boundary": "raw_rank_notes",
    "tool_agent": "raw_payload",
    "backend_export": "raw exporter setup notes",
}
EXPECTED_ERROR_PATHS = {
    "simple_rag": ["debug.query"],
    "subgraph_boundary": ["metrics.candidate_count"],
    "tool_agent": ["debug.raw_tool_response"],
    "backend_export": ["transport.target"],
}


@pytest.mark.parametrize("example", EXAMPLES)
def test_contract_spans_are_clean_and_compact(example: str) -> None:
    payload = _run_example(example)
    contract_spans = _spans(payload, "contract_wrapped")

    assert [span["name"] for span in contract_spans] == EXPECTED_CONTRACT_SPANS[example]
    assert all(span["status"] == "UNSET" for span in contract_spans)
    assert all(isinstance(span["input"], dict) for span in contract_spans)
    assert RAW_MARKERS[example] in json.dumps(payload["raw"], sort_keys=True)
    assert RAW_MARKERS[example] not in json.dumps(contract_spans, sort_keys=True)


@pytest.mark.parametrize("example", EXAMPLES)
def test_examples_show_contract_validation_errors(example: str) -> None:
    payload = _run_example(example)
    validation = cast(dict[str, object], payload["validation"])
    error = cast(dict[str, object], validation["error"])
    spans = cast(list[dict[str, object]], validation["spans"])

    assert error["type"] == "StateContractError"
    assert error["paths"] == EXPECTED_ERROR_PATHS[example]
    assert spans[0]["status"] == "ERROR"
    assert (
        cast(dict[str, object], spans[0]["attributes"])["error.type"]
        == "StateContractError"
    )


@pytest.mark.parametrize("example", EXAMPLES)
def test_logs_stay_lifecycle_only(example: str) -> None:
    payload = _run_example(example)
    logs = cast(list[dict[str, object]], payload["logs"])
    logs_text = json.dumps(logs, sort_keys=True)

    assert [event["event"] for event in logs] == ["chain_start", "chain_end"]
    assert "input.value" not in logs_text
    assert "output.value" not in logs_text
    assert "input_summary" in logs[0]
    assert "output_summary" in logs[1]


def test_backend_export_uses_local_exporters_only() -> None:
    payload = _run_example("backend_export")
    setup = cast(dict[str, object], payload["backend_setup"])
    console_lines = cast(list[dict[str, object]], payload["console_exporter_lines"])

    assert setup["network"] == "none"
    assert setup["exporters"] == ["InMemorySpanExporter", "ConsoleSpanExporter"]
    assert [line["name"] for line in console_lines] == [
        "raw_backend_export",
        "prepare_answer",
    ]


def _run_example(example: str) -> dict[str, object]:
    result = subprocess.run(
        [sys.executable, "-m", f"examples.{example}.app"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return cast(dict[str, object], json.loads(result.stdout))


def _spans(payload: dict[str, object], section: str) -> list[dict[str, object]]:
    section_payload = cast(dict[str, object], payload[section])
    return cast(list[dict[str, object]], section_payload["spans"])
