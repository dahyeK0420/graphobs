from __future__ import annotations

import logging
from typing import cast

import pytest

from graphobs.logging.context import (
    CorrelationFields,
    LogContext,
)
from graphobs.logging.lifecycle import (
    EVENT_LOGGER_NAME,
    LifecycleLogEmitter,
)

LARGE_VALUE = "do not store this full lifecycle value " * 20


def test_lifecycle_emitter_logs_start_finish_and_error_payloads(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=EVENT_LOGGER_NAME)
    emitter = LifecycleLogEmitter(
        LogContext(session_id="session-1"),
        CorrelationFields(),
        logging.getLogger(EVENT_LOGGER_NAME),
        error_message_max_length=32,
    )

    emitter.start(
        "chain_start",
        "chain",
        {"name": "answer"},
        {"request": {"text": LARGE_VALUE}},
        run_id="run-1",
        parent_run_id=None,
        tags=("contracted",),
        metadata={"request_id": "request-1"},
    )
    emitter.finish(
        "chain_end",
        "chain",
        {"answer": {"text": LARGE_VALUE}},
        run_id="run-1",
        parent_run_id=None,
    )
    emitter.start(
        "tool_start",
        "tool",
        {"name": "lookup"},
        {"query": LARGE_VALUE},
        run_id="run-2",
        parent_run_id="run-1",
        tags=None,
        metadata={},
    )
    emitter.error(
        "tool_error",
        "tool",
        RuntimeError(LARGE_VALUE),
        run_id="run-2",
        parent_run_id="run-1",
    )

    events = _graph_log_events(caplog)

    assert [event["event"] for event in events] == [
        "chain_start",
        "chain_end",
        "tool_start",
        "tool_error",
    ]
    assert events[0]["run_name"] == "answer"
    assert events[0]["tags"] == ("contracted",)
    assert events[0]["session_id"] == "session-1"
    assert events[0]["request_id"] == "request-1"
    assert events[0]["metadata_keys"] == ("request_id",)
    assert events[1]["duration_ms"] is not None
    assert events[2]["parent_run_id"] == "run-1"
    assert events[3]["error_type"] == "RuntimeError"
    assert events[3]["error_message_truncated"] is True
    assert LARGE_VALUE not in str(events)
    assert LARGE_VALUE not in caplog.text


def test_lifecycle_emitter_warns_when_duration_is_missing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=EVENT_LOGGER_NAME)
    emitter = LifecycleLogEmitter(
        LogContext(),
        CorrelationFields(),
        logging.getLogger(EVENT_LOGGER_NAME),
    )

    emitter.finish(
        "chain_end",
        "chain",
        {"answer": "ok"},
        run_id="missing-run",
        parent_run_id=None,
    )

    events = _graph_log_events(caplog)

    assert [event["event"] for event in events] == [
        "duration_missing",
        "chain_end",
    ]
    assert events[0]["warning"] == "missing start time for run_id missing-run"
    assert events[1]["duration_ms"] is None
    assert caplog.records[0].levelno == logging.WARNING


def test_lifecycle_emitter_logs_correlation_conflicts(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.ERROR, logger="graphobs.logging")
    emitter = LifecycleLogEmitter(
        LogContext(session_id="session-1"),
        CorrelationFields(),
        logging.getLogger(EVENT_LOGGER_NAME),
    )
    expected_error = "metadata correlation field 'session_id' conflicts with LogContext"

    with pytest.raises(ValueError, match=expected_error):
        emitter.start(
            "chain_start",
            "chain",
            {"name": "conflict"},
            {},
            run_id="conflict-run",
            parent_run_id=None,
            tags=None,
            metadata={"session_id": "different"},
        )

    assert caplog.messages == [f"Failed to build graph log payload: {expected_error}"]


def test_lifecycle_emitter_logger_failure_logs_error_and_raises(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.ERROR, logger="graphobs.logging")
    logger = logging.getLogger("tests.graphobs.lifecycle_failing_logs")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.INFO)
    logger.addHandler(_FailingHandler())
    emitter = LifecycleLogEmitter(LogContext(), CorrelationFields(), logger)

    with pytest.raises(RuntimeError, match="export unavailable"):
        emitter.start(
            "chain_start",
            "chain",
            {"name": "fail"},
            {},
            run_id="run-1",
            parent_run_id=None,
            tags=None,
            metadata=None,
        )

    assert caplog.messages == [
        "Failed to emit graph log event chain_start: export unavailable"
    ]


def _graph_log_events(caplog: pytest.LogCaptureFixture) -> list[dict[str, object]]:
    return [
        cast(dict[str, object], record.graph_log)
        for record in caplog.records
        if hasattr(record, "graph_log")
    ]


class _FailingHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        raise RuntimeError("export unavailable")
