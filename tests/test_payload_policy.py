from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence

import pytest

from graph_observability_kit._observability.payload_policy import (
    payload_summary,
    prepare_trace_payload,
    project_contract_payload,
    serialize_trace_payload,
)
from graph_observability_kit.contracts.models import NodeContract
from graph_observability_kit.langgraph.callbacks import project_callback_payloads
from graph_observability_kit.logging.context import (
    CorrelationFields,
    LogContext,
)
from graph_observability_kit.logging.lifecycle import (
    build_finish_payload,
    build_start_payload,
)
from graph_observability_kit.payloads import message_compact_summary, shape_summary
from graph_observability_kit.tracing import (
    TracePayloadMode,
    default_payload_serializer,
)

LARGE_VALUE = "do not expose this full payload value " * 20


def test_trace_serializer_delegates_to_payload_policy() -> None:
    payload = {"request": {"text": LARGE_VALUE}}

    assert prepare_trace_payload(
        payload,
        mode=TracePayloadMode.MESSAGE_COMPACT,
    ) == message_compact_summary(payload)
    assert prepare_trace_payload(payload, mode=TracePayloadMode.COMPACT) == (
        shape_summary(payload)
    )
    assert prepare_trace_payload(payload, mode=TracePayloadMode.FULL) is payload

    for mode in TracePayloadMode:
        serialized = serialize_trace_payload(
            payload,
            mode=mode,
        )
        assert default_payload_serializer(payload, mode=mode) == serialized

    assert LARGE_VALUE not in serialize_trace_payload(
        payload,
        mode=TracePayloadMode.MESSAGE_COMPACT,
    )
    assert (
        json.loads(serialize_trace_payload(payload, mode=TracePayloadMode.FULL))
        == payload
    )


def test_projection_fallback_uses_policy_summary_and_safe_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="graph_observability_kit.contracts")
    logger = logging.getLogger("graph_observability_kit.contracts")
    payload = {"request": {"text": LARGE_VALUE}}

    def failing_project(state: Mapping[str, object]) -> dict[str, object]:
        raise RuntimeError("synthetic projection failure")

    result = project_contract_payload(
        contract_label="failing",
        payload=payload,
        payload_kind="input",
        project=failing_project,
        logger=logger,
        fallback_to_summary=True,
    )

    assert result == {"input_summary": payload_summary(payload)}
    assert caplog.messages == [
        "Could not project input payload for contract failing; "
        "using compact summary after RuntimeError: synthetic projection failure"
    ]
    assert LARGE_VALUE not in caplog.text


def test_callback_projection_uses_message_compact_policy() -> None:
    callback = _RecordingCallback()
    contract = NodeContract(name="chat", reads=("messages",), writes=("messages",))
    wrapper = project_callback_payloads(callback, [contract])
    messages = [_Message("human", "hello"), _Message("ai", "world")]

    wrapper.on_chain_start(
        {"name": "chat"},
        {"messages": messages, "raw": LARGE_VALUE},
        run_id="chat-run",
        metadata={"langgraph_node": "chat"},
    )

    assert callback.events == [
        {
            "messages": [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "world"},
            ]
        }
    ]
    assert LARGE_VALUE not in str(callback.events)


def test_lifecycle_payload_summaries_use_shared_policy() -> None:
    log_context = LogContext(session_id="session-1")
    fields = CorrelationFields()
    input_payload = {"request": {"text": LARGE_VALUE}}
    output_payload = {"answer": {"text": LARGE_VALUE}}

    start_payload = build_start_payload(
        log_context,
        fields,
        "chain_start",
        "chain",
        {"name": "answer"},
        input_payload,
        run_id="run-1",
        parent_run_id=None,
        tags=None,
        metadata={},
    )
    finish_payload = build_finish_payload(
        log_context,
        fields,
        "chain_end",
        "chain",
        output_payload,
        run_id="run-1",
        parent_run_id=None,
        metadata={},
        duration_ms=1.0,
    )

    assert start_payload["input_summary"] == payload_summary(input_payload)
    assert finish_payload["output_summary"] == payload_summary(output_payload)
    assert LARGE_VALUE not in str(start_payload)
    assert LARGE_VALUE not in str(finish_payload)


class _Message:
    def __init__(self, msg_type: str, content: str) -> None:
        self.type = msg_type
        self.content = content


class _RecordingCallback:
    def __init__(self) -> None:
        self.events: list[object] = []

    def on_chain_start(
        self,
        serialized: Mapping[str, object] | None,
        inputs: object,
        *,
        run_id: object,
        parent_run_id: object | None = None,
        tags: Sequence[str] | None = None,
        metadata: Mapping[str, object] | None = None,
        **kwargs: object,
    ) -> None:
        self.events.append(inputs)
