from __future__ import annotations

import logging
from typing import Any, TypedDict, cast
from uuid import uuid4

import pytest
from langgraph.graph import END, START, StateGraph

from graphobs.logging.callback import GraphLogCallback
from graphobs.logging.context import (
    CorrelationFields,
    LogContext,
)
from graphobs.logging.invoke_config import build_invoke_config
from graphobs.tracing import (
    start_graph_span,
)

LARGE_VALUE = "do not store this full value " * 20


class ExampleState(TypedDict, total=False):
    request: dict[str, object]
    answer: dict[str, object]


def test_chain_lifecycle_log_shape(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="graphobs.logs")
    run_id = uuid4()
    context = LogContext(session_id="session-1", trace_id="trace-1")
    callback = GraphLogCallback(context)

    callback.on_chain_start(
        {"name": "answer"},
        {"request": {"text": LARGE_VALUE}},
        run_id=run_id,
        metadata=context.as_metadata(),
    )
    callback.on_chain_end({"answer": {"text": LARGE_VALUE}}, run_id=run_id)

    events = _graph_log_events(caplog)

    assert [event["event"] for event in events] == ["chain_start", "chain_end"]
    assert events[0]["run_kind"] == "chain"
    assert events[0]["session_id"] == "session-1"
    assert events[0]["trace_id"] == "trace-1"
    assert events[0]["input_summary"] == {
        "type": "mapping",
        "size": 1,
        "keys": ["request"],
    }
    assert isinstance(events[1]["duration_ms"], float)
    assert events[1]["output_summary"] == {
        "type": "mapping",
        "size": 1,
        "keys": ["answer"],
    }
    assert LARGE_VALUE not in str(events)
    assert LARGE_VALUE not in caplog.text


def test_langgraph_invoke_config_emits_node_like_events(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="graphobs.logs")

    def answer(state: ExampleState) -> ExampleState:
        return {"answer": {"text": f"hello {state['request']['text']}"}}

    graph = StateGraph(ExampleState)
    graph.add_node("answer", answer)
    graph.add_edge(START, "answer")
    graph.add_edge("answer", END)
    config = build_invoke_config(
        LogContext(session_id="session-2", request_id="request-2"),
        metadata={"example": "logging"},
    )

    result = graph.compile().invoke(
        {"request": {"text": "world", "raw": LARGE_VALUE}},
        config=cast(Any, config),
    )

    events = _graph_log_events(caplog)
    node_starts = [
        event
        for event in events
        if event["event"] == "chain_start" and event.get("run_name") == "answer"
    ]

    assert result["answer"] == {"text": "hello world"}
    assert node_starts
    assert node_starts[0]["session_id"] == "session-2"
    assert node_starts[0]["request_id"] == "request-2"
    metadata_keys = cast(tuple[str, ...], node_starts[0]["metadata_keys"])
    assert "langgraph_node" in metadata_keys
    assert LARGE_VALUE not in str(events)
    assert LARGE_VALUE not in caplog.text


def test_tool_lifecycle_log_shape(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="graphobs.logs")
    run_id = uuid4()
    callback = GraphLogCallback(LogContext(conversation_id="conversation-1"))

    callback.on_tool_start(
        {"name": "lookup"},
        LARGE_VALUE,
        run_id=run_id,
        inputs={"query": LARGE_VALUE},
    )
    callback.on_tool_end({"result": LARGE_VALUE}, run_id=run_id)

    events = _graph_log_events(caplog)

    assert [event["event"] for event in events] == ["tool_start", "tool_end"]
    assert events[0]["run_kind"] == "tool"
    assert events[0]["run_name"] == "lookup"
    assert events[0]["conversation_id"] == "conversation-1"
    input_summary = cast(dict[str, object], events[0]["input_summary"])
    output_summary = cast(dict[str, object], events[1]["output_summary"])
    assert input_summary["keys"] == ["query"]
    assert output_summary["keys"] == ["result"]
    assert LARGE_VALUE not in str(events)


def test_error_message_is_truncated_by_default(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.ERROR, logger="graphobs.logs")
    run_id = uuid4()
    callback = GraphLogCallback(error_message_max_length=32)
    callback.on_chain_start({"name": "failing"}, {}, run_id=run_id)

    callback.on_chain_error(RuntimeError(LARGE_VALUE), run_id=run_id)

    error_event = _graph_log_events(caplog)[0]

    assert error_event["event"] == "chain_error"
    assert error_event["error_type"] == "RuntimeError"
    assert error_event["error_message_truncated"] is True
    assert len(str(error_event["error_message"])) == 32
    assert LARGE_VALUE not in str(error_event)
    assert LARGE_VALUE not in caplog.text


def test_custom_correlation_fields_propagate_to_metadata_and_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="graphobs.logs")
    fields = CorrelationFields(
        session="session.id",
        conversation="conversation.id",
        turn="turn.id",
        request="request.id",
        trace="trace.id",
    )
    context = LogContext(
        session_id="session-3",
        conversation_id="conversation-3",
        turn_id="turn-3",
        request_id="request-3",
        trace_id="trace-3",
    )

    config = build_invoke_config(context, fields=fields)
    callback = config["callbacks"][0]
    assert isinstance(callback, GraphLogCallback)
    callback.on_chain_start(
        {"name": "correlated"},
        {},
        run_id=uuid4(),
        metadata=config["metadata"],
    )

    event = _graph_log_events(caplog)[0]

    assert config["metadata"] == context.as_metadata(fields)
    assert event["session.id"] == "session-3"
    assert event["conversation.id"] == "conversation-3"
    assert event["turn.id"] == "turn-3"
    assert event["request.id"] == "request-3"
    assert event["trace.id"] == "trace-3"


def test_metadata_conflict_raises_and_logs(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.ERROR, logger="graphobs.logging")
    expected_error = "metadata correlation field 'session_id' conflicts with LogContext"

    with pytest.raises(ValueError, match=expected_error):
        build_invoke_config(
            LogContext(session_id="session-4"),
            metadata={"session_id": "different"},
        )

    assert caplog.records[0].levelno == logging.ERROR
    assert caplog.messages == [f"Failed to build invoke config: {expected_error}"]


def test_missing_start_time_warns_and_still_emits_end(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="graphobs.logs")
    callback = GraphLogCallback()
    run_id = uuid4()

    callback.on_chain_end({"answer": "ok"}, run_id=run_id)

    events = _graph_log_events(caplog)
    expected_warning = f"missing start time for run_id {run_id}"

    assert [event["event"] for event in events] == [
        "duration_missing",
        "chain_end",
    ]
    assert caplog.records[0].levelno == logging.WARNING
    assert caplog.messages[0] == (
        f"graph lifecycle event: duration_missing: {expected_warning}"
    )
    assert events[1]["duration_ms"] is None
    output_summary = cast(dict[str, object], events[1]["output_summary"])
    assert output_summary["keys"] == ["answer"]


def test_callback_flags_match_langchain_expectations() -> None:
    assert GraphLogCallback.raise_error is True
    assert GraphLogCallback.run_inline is False
    assert GraphLogCallback.ignore_chain is False
    assert GraphLogCallback.ignore_tool is False
    assert GraphLogCallback.ignore_llm is True
    assert GraphLogCallback.ignore_retry is True
    assert GraphLogCallback.ignore_agent is True
    assert GraphLogCallback.ignore_retriever is True
    assert GraphLogCallback.ignore_chat_model is True
    assert GraphLogCallback.ignore_custom_event is True


def test_logger_injection_uses_custom_logger() -> None:
    logger = logging.getLogger("tests.graphobs.custom_logs")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.INFO)
    handler = _CollectingHandler()
    logger.addHandler(handler)
    run_id = uuid4()

    GraphLogCallback(LogContext(turn_id="turn-1"), logger=logger).on_chain_start(
        {"name": "custom"},
        {},
        run_id=run_id,
    )

    assert len(handler.records) == 1
    record_values = vars(handler.records[0])
    graph_log = cast(dict[str, object], record_values["graph_log"])
    assert record_values["graph_log_event"] == "chain_start"
    assert graph_log["event"] == "chain_start"
    assert graph_log["run_id"] == str(run_id)
    assert graph_log["parent_run_id"] is None
    assert graph_log["metadata_keys"] == ()
    assert graph_log["tags"] == ()
    assert graph_log["turn_id"] == "turn-1"


def test_logger_failure_logs_error_and_raises(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.ERROR, logger="graphobs.logging")
    logger = logging.getLogger("tests.graphobs.failing_logs")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.INFO)
    logger.addHandler(_FailingHandler())
    callback = GraphLogCallback(logger=logger)

    with pytest.raises(RuntimeError, match="export unavailable"):
        callback.on_chain_start({"name": "fail"}, {}, run_id=uuid4())

    assert caplog.records[0].levelno == logging.ERROR
    assert caplog.messages == [
        "Failed to emit graph log event chain_start: export unavailable"
    ]


def test_logs_and_spans_share_correlation_without_trace_payloads(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="graphobs.logs")
    context = LogContext(session_id="session-5", trace_id="trace-5")
    run_id = uuid4()
    callback = GraphLogCallback(context)

    with start_graph_span("answer", "CHAIN", attributes=context.as_metadata()):
        callback.on_chain_start(
            {"name": "answer"},
            {"request": {"text": LARGE_VALUE}},
            run_id=run_id,
        )
        callback.on_chain_end({"answer": {"text": LARGE_VALUE}}, run_id=run_id)

    events = _graph_log_events(caplog)

    assert events[0]["session_id"] == "session-5"
    assert events[0]["trace_id"] == "trace-5"
    assert "input.value" not in str(events)
    assert "output.value" not in str(events)
    assert LARGE_VALUE not in str(events)


def _graph_log_events(caplog: pytest.LogCaptureFixture) -> list[dict[str, object]]:
    return [
        cast(dict[str, object], record.graph_log)
        for record in caplog.records
        if hasattr(record, "graph_log")
    ]


class _CollectingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


class _FailingHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        raise RuntimeError("export unavailable")
