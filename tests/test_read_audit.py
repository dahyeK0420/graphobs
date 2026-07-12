from __future__ import annotations

import logging

import pytest

from graphobs.contracts.models import (
    ContractViolationAction,
    NodeContract,
    StateContractError,
)
from graphobs.langgraph.read_audit import enforce_undeclared_reads
from graphobs.state.read_tracking import ReadTracker


def test_enforce_undeclared_reads_ignores_missing_tracker() -> None:
    contract = NodeContract(name="audited", reads=("request.text",), writes=())

    enforce_undeclared_reads(contract, None)


def test_enforce_undeclared_reads_raises_by_default() -> None:
    contract = NodeContract(name="audited", reads=("request.text",), writes=())
    tracker = ReadTracker()
    tracker.record(("context", "extra"))
    tracker.record(("request", "raw"))

    with pytest.raises(StateContractError) as error:
        enforce_undeclared_reads(contract, tracker)

    assert error.value.access == "read"
    assert error.value.undeclared_paths == ("context.extra", "request.raw")


def test_enforce_undeclared_reads_warns_and_continues(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="graphobs.langgraph")
    contract = NodeContract(name="audited", reads=("request.text",), writes=())
    tracker = ReadTracker()
    tracker.record(("context", "extra"))
    tracker.record(("request", "raw"))

    enforce_undeclared_reads(
        contract,
        tracker,
        on_violation=ContractViolationAction.WARN,
    )

    assert caplog.messages == [
        "Contract 'audited' read undeclared state paths: context.extra, request.raw"
    ]
