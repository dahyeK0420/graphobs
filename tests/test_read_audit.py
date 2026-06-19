from __future__ import annotations

import logging

import pytest

from graphobs.contracts.models import NodeContract
from graphobs.langgraph.read_audit import (
    undeclared_read_paths,
    warn_undeclared_reads,
)
from graphobs.state.read_tracking import ReadTracker


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


def test_warn_undeclared_reads_preserves_warning_text_and_order(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="graphobs.langgraph")
    contract = NodeContract(name="audited", reads=("request.text",), writes=())
    tracker = ReadTracker()
    tracker.record(("context", "extra"))
    tracker.record(("request", "raw"))

    warn_undeclared_reads(contract, tracker)

    assert caplog.messages == [
        "Contract 'audited' read undeclared state paths: context.extra, request.raw"
    ]
