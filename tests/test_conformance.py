from __future__ import annotations

import logging

import pytest

from graphobs.contracts.conformance import (
    enforce_undeclared_reads,
    report_violation,
    undeclared_read_paths,
    undeclared_write_paths,
)
from graphobs.contracts.models import (
    ContractViolationAction,
    NodeContract,
    StateContractError,
)
from graphobs.state.read_tracking import ReadTracker

CONFORMANCE_LOGGER = "graphobs.test-conformance"


def test_undeclared_read_paths_uses_shared_observed_access_classification() -> None:
    contract = NodeContract(
        name="audited",
        reads=("request.text", "context.retrieved"),
        writes=(),
        private_reads=("scratch.step",),
    )

    assert undeclared_read_paths(
        contract,
        (
            "request",
            "request.raw",
            "context.retrieved",
            "context.extra",
            "scratch.step",
            "scratch",
            "debug",
        ),
    ) == ("request.raw", "context.extra", "debug")


def test_undeclared_write_paths_rejects_paths_outside_write_policies() -> None:
    contract = NodeContract(
        name="answering",
        reads=(),
        writes=("answer.label",),
        private_writes=("scratch.step",),
    )

    assert undeclared_write_paths(
        contract,
        (
            ("answer", "label"),
            ("answer", "raw"),
            ("scratch", "step"),
            ("debug",),
        ),
    ) == ("answer.raw", "debug")


def test_report_violation_is_noop_for_no_undeclared_paths(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger=CONFORMANCE_LOGGER)

    report_violation(
        "answering",
        (),
        access="write",
        on_violation=ContractViolationAction.RAISE,
        logger=logging.getLogger(CONFORMANCE_LOGGER),
    )

    assert caplog.records == []


def test_report_violation_warns_and_continues(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger=CONFORMANCE_LOGGER)

    report_violation(
        "answering",
        ("answer.raw", "debug"),
        access="write",
        on_violation=ContractViolationAction.WARN,
        logger=logging.getLogger(CONFORMANCE_LOGGER),
    )

    assert caplog.records[0].levelno == logging.WARNING
    assert caplog.messages == [
        "Contract 'answering' wrote undeclared state paths: answer.raw, debug"
    ]


def test_report_violation_raises_and_logs_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.ERROR, logger=CONFORMANCE_LOGGER)

    with pytest.raises(StateContractError) as error:
        report_violation(
            "audited",
            ("context.extra", "request.raw"),
            access="read",
            on_violation=ContractViolationAction.RAISE,
            logger=logging.getLogger(CONFORMANCE_LOGGER),
        )

    assert error.value.access == "read"
    assert error.value.undeclared_paths == ("context.extra", "request.raw")
    assert caplog.records[0].levelno == logging.ERROR
    assert caplog.messages == [str(error.value)]


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
