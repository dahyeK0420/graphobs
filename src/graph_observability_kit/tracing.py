"""OpenTelemetry tracing helpers with OpenInference attributes."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from enum import StrEnum
from typing import Protocol, cast

from openinference.semconv.trace import SpanAttributes
from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.trace import Span, Status, StatusCode
from opentelemetry.util.types import AttributeValue

from graph_observability_kit._shape_summary import shape_summary

LOGGER = logging.getLogger(__name__)
TRACER_NAME = "graph_observability_kit"
JSON_MIME_TYPE = "application/json"


class TracePayloadMode(StrEnum):
    """Controls how input and output values are serialized into spans."""

    COMPACT = "compact"
    FULL = "full"


class PayloadSerializer(Protocol):
    """Callable interface for span payload serialization."""

    def __call__(
        self,
        value: object,
        *,
        mode: TracePayloadMode = TracePayloadMode.COMPACT,
    ) -> str:
        """Serializes a payload for an OpenInference span attribute.

        Args:
            value: Payload value to serialize.
            mode: Payload serialization mode.

        Returns:
            A JSON string suitable for an OpenTelemetry span attribute.
        """


def default_payload_serializer(
    value: object,
    *,
    mode: TracePayloadMode = TracePayloadMode.COMPACT,
) -> str:
    """Serializes a payload with the package default trace policy.

    Compact mode records structural summaries instead of arbitrary values.
    Full mode records complete JSON-compatible values and raises when the
    payload cannot be represented as JSON.

    Args:
        value: Payload value to serialize.
        mode: Payload serialization mode.

    Returns:
        A JSON string suitable for an OpenTelemetry span attribute.

    Raises:
        TypeError: If full mode receives a value that is not JSON serializable.
        ValueError: If ``mode`` is not supported.
    """
    prepared: object
    if mode is TracePayloadMode.COMPACT:
        prepared = shape_summary(value)
    elif mode is TracePayloadMode.FULL:
        prepared = value
    else:
        raise ValueError(f"unsupported trace payload mode: {mode!r}")

    return json.dumps(prepared, sort_keys=True, separators=(",", ":"))


@contextmanager
def start_graph_span(
    name: str,
    kind: str,
    input: object | None = None,
    output: object | None = None,
    attributes: Mapping[str, object] | None = None,
    context: otel_context.Context | None = None,
    *,
    mode: TracePayloadMode = TracePayloadMode.COMPACT,
    serializer: PayloadSerializer | None = None,
) -> Iterator[Span]:
    """Starts a graph span with OpenInference-compatible attributes.

    Exporter configuration remains outside this library. The active
    OpenTelemetry tracer provider decides where finished spans are sent.

    Args:
        name: Span name.
        kind: OpenInference span kind value.
        input: Optional input payload.
        output: Optional output payload.
        attributes: Optional flat or nested searchable attributes.
        context: Optional OpenTelemetry context.
        mode: Payload serialization mode.
        serializer: Optional payload serializer override.

    Yields:
        The active OpenTelemetry span.
    """
    active_serializer = serializer or default_payload_serializer
    tracer = trace.get_tracer(TRACER_NAME)

    with tracer.start_as_current_span(name, context=context) as span:
        set_span_attributes(span, {SpanAttributes.OPENINFERENCE_SPAN_KIND: kind})
        if attributes is not None:
            set_span_attributes(span, attributes)
        if input is not None:
            set_span_input(span, input, mode=mode, serializer=active_serializer)
        if output is not None:
            set_span_output(span, output, mode=mode, serializer=active_serializer)
        yield span


def set_span_input(
    span: Span,
    value: object,
    *,
    mode: TracePayloadMode = TracePayloadMode.COMPACT,
    serializer: PayloadSerializer | None = None,
) -> None:
    """Sets the OpenInference input payload attributes on a span.

    Args:
        span: OpenTelemetry span to update.
        value: Input payload value.
        mode: Payload serialization mode.
        serializer: Optional payload serializer override.
    """
    active_serializer = serializer or default_payload_serializer
    serialized = _serialize_payload(value, mode=mode, serializer=active_serializer)
    set_span_attributes(
        span,
        {
            SpanAttributes.INPUT_VALUE: serialized,
            SpanAttributes.INPUT_MIME_TYPE: JSON_MIME_TYPE,
        },
    )


def set_span_output(
    span: Span,
    value: object,
    *,
    mode: TracePayloadMode = TracePayloadMode.COMPACT,
    serializer: PayloadSerializer | None = None,
) -> None:
    """Sets the OpenInference output payload attributes on a span.

    Args:
        span: OpenTelemetry span to update.
        value: Output payload value.
        mode: Payload serialization mode.
        serializer: Optional payload serializer override.
    """
    active_serializer = serializer or default_payload_serializer
    serialized = _serialize_payload(value, mode=mode, serializer=active_serializer)
    set_span_attributes(
        span,
        {
            SpanAttributes.OUTPUT_VALUE: serialized,
            SpanAttributes.OUTPUT_MIME_TYPE: JSON_MIME_TYPE,
        },
    )


def set_span_attributes(span: Span, attributes: Mapping[str, object]) -> None:
    """Sets flat searchable attributes on a span.

    Nested mappings are flattened with dotted keys. Unsupported attribute values
    are skipped with a warning that includes the original error message.

    Args:
        span: OpenTelemetry span to update.
        attributes: Attributes to flatten and set.

    Raises:
        ValueError: If an attribute key is blank.
    """
    for key, value in _flatten_attributes(attributes):
        if value is None:
            continue
        try:
            span.set_attribute(key, value)
        except Exception as exc:
            LOGGER.error("Failed to set span attribute %s: %s", key, exc)
            raise


def mark_span_error(span: Span, exc: BaseException) -> None:
    """Marks a span as failed and records exception metadata.

    Args:
        span: OpenTelemetry span to update.
        exc: Exception that caused the span failure.
    """
    try:
        span.record_exception(exc)
        span.set_status(Status(StatusCode.ERROR, str(exc)))
        set_span_attributes(
            span,
            {
                "error.type": type(exc).__name__,
            },
        )
    except Exception as error:
        LOGGER.error("Failed to mark span error: %s", error)
        raise


def _serialize_payload(
    value: object,
    *,
    mode: TracePayloadMode,
    serializer: PayloadSerializer,
) -> str:
    try:
        return serializer(value, mode=mode)
    except Exception as exc:
        LOGGER.error("Failed to serialize trace payload: %s", exc)
        raise


def _flatten_attributes(
    attributes: Mapping[str, object],
    *,
    prefix: str = "",
) -> Iterator[tuple[str, AttributeValue | None]]:
    for raw_key, value in attributes.items():
        key = _attribute_key(raw_key, prefix=prefix)
        if isinstance(value, Mapping):
            yield from _flatten_attributes(value, prefix=key)
            continue
        yield key, _coerce_attribute_value(key, value)


def _attribute_key(raw_key: str, *, prefix: str) -> str:
    key = f"{prefix}.{raw_key}" if prefix else str(raw_key)
    if not key.strip():
        error = ValueError("span attribute key must not be blank")
        LOGGER.error("Failed to flatten span attributes: %s", error)
        raise error
    return key


def _coerce_attribute_value(key: str, value: object) -> AttributeValue | None:
    try:
        return _require_attribute_value(value)
    except TypeError as exc:
        LOGGER.warning("Could not set span attribute %s: %s", key, exc)
        return None


def _require_attribute_value(value: object) -> AttributeValue | None:
    if value is None:
        return None
    if isinstance(value, str | bool | int | float):
        return value
    if isinstance(value, Sequence) and not isinstance(
        value,
        str | bytes | bytearray,
    ):
        return _require_attribute_sequence(value)
    raise TypeError(f"unsupported attribute value type: {type(value).__name__}")


def _require_attribute_sequence(value: Sequence[object]) -> AttributeValue:
    if not value:
        return []

    if all(isinstance(item, str) for item in value):
        return cast(AttributeValue, list(value))
    if all(isinstance(item, bool) for item in value):
        return cast(AttributeValue, list(value))
    if all(isinstance(item, int) and not isinstance(item, bool) for item in value):
        return cast(AttributeValue, list(value))
    if all(isinstance(item, float) for item in value):
        return cast(AttributeValue, list(value))

    raise TypeError("attribute sequence values must be homogeneous primitives")


__all__ = [
    "PayloadSerializer",
    "TracePayloadMode",
    "default_payload_serializer",
    "mark_span_error",
    "set_span_attributes",
    "set_span_input",
    "set_span_output",
    "start_graph_span",
]
