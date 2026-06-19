"""Stable span display records for local demos."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from opentelemetry.sdk.trace import ReadableSpan
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

LOGGER = logging.getLogger("graph_observability_kit.demo")

_INSTALL_HINT = (
    'Install the demo dependencies first: pip install "graph-observability-kit[demo]"'
)


def span_records(exporter: InMemorySpanExporter) -> list[dict[str, object]]:
    """Returns all finished spans as stable dicts without IDs or timestamps.

    Args:
        exporter: The ``InMemorySpanExporter`` returned by
            ``configure_local_tracing()``.

    Returns:
        A list of span dicts with ``name``, ``kind``, ``status``, and optional
        ``input``, ``output``, and ``attributes`` keys. Suitable for display or
        assertion in notebooks and tests.
    """
    return [span_record(span) for span in exporter.get_finished_spans()]


def span_record(span: ReadableSpan) -> dict[str, object]:
    """Converts a single finished span into a compact, stable display dict.

    Strips span IDs, trace IDs, and timestamps so the output is deterministic
    and safe to log or display in a notebook.

    Args:
        span: A finished OpenTelemetry span from the in-memory exporter.

    Returns:
        A dict with ``name``, ``kind``, ``status``, and optionally ``input``,
        ``output``, and ``attributes``.
    """
    try:
        from openinference.semconv.trace import SpanAttributes
    except ImportError as exc:
        LOGGER.error(
            "span_record failed: openinference-semantic-conventions not installed. %s",
            _INSTALL_HINT,
        )
        raise ImportError(_INSTALL_HINT) from exc

    attributes = dict(span.attributes or {})
    record: dict[str, object] = {
        "name": span.name,
        "kind": attributes.get(SpanAttributes.OPENINFERENCE_SPAN_KIND),
        "status": span.status.status_code.name,
    }

    public_attributes = {
        key: attributes[key]
        for key in (
            "error.type",
            "graph.node",
            "graph.subgraph",
            "tool.iteration",
            "tool.name",
        )
        if key in attributes
    }
    if public_attributes:
        record["attributes"] = public_attributes

    input_value = _json_attribute(attributes, SpanAttributes.INPUT_VALUE)
    if input_value is not None:
        record["input"] = input_value

    output_value = _json_attribute(attributes, SpanAttributes.OUTPUT_VALUE)
    if output_value is not None:
        record["output"] = output_value

    return record


def _format_span_as_json_line(span: ReadableSpan) -> str:
    return f"{json.dumps(span_record(span), sort_keys=True)}\n"


def _json_attribute(
    attributes: Mapping[str, object],
    key: str,
) -> object | None:
    value = attributes.get(key)
    if not isinstance(value, str):
        return value
    try:
        return cast(object, json.loads(value))
    except json.JSONDecodeError as exc:
        LOGGER.warning(
            "span_record: could not parse JSON attribute %r: %s",
            key,
            exc,
        )
        return value


__all__ = ["span_record", "span_records"]
