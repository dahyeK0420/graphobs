from __future__ import annotations

import json
import logging

import pytest
from openinference.semconv.trace import SpanAttributes
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from opentelemetry.trace import StatusCode

from graph_observability_kit.tracing import (
    TracePayloadMode,
    default_payload_serializer,
    mark_span_error,
    set_span_attributes,
    set_span_input,
    start_graph_span,
)


def test_start_graph_span_emits_openinference_attributes(
    span_exporter: InMemorySpanExporter,
) -> None:
    with start_graph_span(
        "classify",
        "CHAIN",
        input={"request": {"text": "large input"}, "context": {"locale": "en"}},
        output={"classification": {"label": "question"}},
        attributes={
            "graph.node": "classify",
            "metrics": {"attempt": 1},
            "ignored": None,
        },
    ):
        pass

    span = span_exporter.get_finished_spans()[0]

    assert span.name == "classify"
    assert span.attributes is not None
    assert span.attributes[SpanAttributes.OPENINFERENCE_SPAN_KIND] == "CHAIN"
    assert span.attributes[SpanAttributes.INPUT_MIME_TYPE] == "application/json"
    assert span.attributes[SpanAttributes.OUTPUT_MIME_TYPE] == "application/json"
    assert span.attributes["graph.node"] == "classify"
    assert span.attributes["metrics.attempt"] == 1
    assert "ignored" not in span.attributes


def test_compact_mode_does_not_store_full_arbitrary_state(
    span_exporter: InMemorySpanExporter,
) -> None:
    with start_graph_span(
        "retrieve",
        "RETRIEVER",
        input={"request": {"text": "do not store this full value"}},
    ):
        pass

    span = span_exporter.get_finished_spans()[0]

    assert span.attributes is not None
    input_value = span.attributes[SpanAttributes.INPUT_VALUE]
    assert isinstance(input_value, str)
    assert "do not store this full value" not in input_value
    assert json.loads(input_value) == {
        "keys": ["request"],
        "size": 1,
        "type": "mapping",
    }


def test_full_mode_is_explicit(span_exporter: InMemorySpanExporter) -> None:
    payload = {"request": {"text": "explicit full payload"}}

    with start_graph_span(
        "answer",
        "CHAIN",
        input=payload,
        mode=TracePayloadMode.FULL,
    ):
        pass

    span = span_exporter.get_finished_spans()[0]

    assert span.attributes is not None
    input_value = span.attributes[SpanAttributes.INPUT_VALUE]
    assert isinstance(input_value, str)
    assert json.loads(input_value) == payload


def test_set_span_input_accepts_custom_serializer(
    span_exporter: InMemorySpanExporter,
) -> None:
    def fixed_serializer(
        value: object,
        *,
        mode: TracePayloadMode = TracePayloadMode.COMPACT,
    ) -> str:
        return json.dumps(
            {"custom": type(value).__name__, "mode": mode.value},
            sort_keys=True,
            separators=(",", ":"),
        )

    with start_graph_span("custom", "CHAIN") as span:
        set_span_input(span, {"payload": "value"}, serializer=fixed_serializer)

    finished_span = span_exporter.get_finished_spans()[0]

    assert finished_span.attributes is not None
    input_value = finished_span.attributes[SpanAttributes.INPUT_VALUE]
    assert isinstance(input_value, str)
    assert json.loads(input_value) == {"custom": "dict", "mode": "compact"}


def test_custom_serializer_can_redact_compact_payloads(
    span_exporter: InMemorySpanExporter,
) -> None:
    def redacting_serializer(
        value: object,
        *,
        mode: TracePayloadMode = TracePayloadMode.COMPACT,
    ) -> str:
        if mode is TracePayloadMode.COMPACT and isinstance(value, dict):
            return json.dumps(
                {"type": "mapping", "redacted": "secret" in value},
                sort_keys=True,
                separators=(",", ":"),
            )
        return default_payload_serializer(value, mode=mode)

    with start_graph_span(
        "redacted",
        "CHAIN",
        input={"secret": "synthetic"},
        serializer=redacting_serializer,
    ):
        pass

    finished_span = span_exporter.get_finished_spans()[0]

    assert finished_span.attributes is not None
    input_value = finished_span.attributes[SpanAttributes.INPUT_VALUE]
    assert isinstance(input_value, str)
    assert json.loads(input_value) == {"redacted": True, "type": "mapping"}


def test_unsupported_attribute_value_logs_warning(
    caplog: pytest.LogCaptureFixture,
    span_exporter: InMemorySpanExporter,
) -> None:
    caplog.set_level(logging.WARNING, logger="graph_observability_kit.tracing")

    with start_graph_span("attributes", "CHAIN") as span:
        set_span_attributes(span, {"bad": object(), "good": True})

    finished_span = span_exporter.get_finished_spans()[0]

    assert finished_span.attributes is not None
    assert finished_span.attributes["good"] is True
    assert "bad" not in finished_span.attributes
    assert caplog.records[0].levelno == logging.WARNING
    assert caplog.messages == [
        "Could not set span attribute bad: unsupported attribute value type: object"
    ]


def test_full_mode_serialization_error_logs_and_raises(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.ERROR, logger="graph_observability_kit.tracing")

    with (
        pytest.raises(TypeError),
        start_graph_span(
            "bad-payload",
            "CHAIN",
            input=object(),
            mode=TracePayloadMode.FULL,
        ),
    ):
        pass

    assert caplog.records[0].levelno == logging.ERROR
    assert caplog.messages == [
        "Failed to serialize trace payload: "
        "Object of type object is not JSON serializable"
    ]


def test_mark_span_error_sets_error_status_and_type(
    span_exporter: InMemorySpanExporter,
) -> None:
    with start_graph_span("failing", "CHAIN") as span:
        try:
            raise RuntimeError("synthetic failure")
        except RuntimeError as exc:
            mark_span_error(span, exc)

    finished_span = span_exporter.get_finished_spans()[0]

    assert finished_span.status.status_code is StatusCode.ERROR
    assert finished_span.attributes is not None
    assert finished_span.attributes["error.type"] == "RuntimeError"
