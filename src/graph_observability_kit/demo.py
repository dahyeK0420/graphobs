"""Lightweight display and exporter helpers for notebooks and local demos.

This module requires the ``demo`` optional dependencies::

    pip install "graph-observability-kit[demo]"

It is not imported by the core package. Production code should configure
OpenTelemetry exporters directly rather than depending on this module.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from opentelemetry.sdk.trace import ReadableSpan
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

LOGGER = logging.getLogger(__name__)

_INSTALL_HINT = (
    'Install the demo dependencies first: pip install "graph-observability-kit[demo]"'
)


def configure_local_tracing(*, console: bool = False) -> InMemorySpanExporter:
    """Configures an in-process tracer that captures spans in memory.

    Installs a global ``TracerProvider`` backed by an ``InMemorySpanExporter``
    so that spans emitted by the kit are captured without a running collector.
    Optionally mirrors every finished span to stdout as single-line JSON.

    This function is intended for notebooks and local demos only. Call it once
    before constructing or running any graph. Calling it a second time in the
    same process has no effect on the global provider (OpenTelemetry enforces
    set-once semantics) and will log a warning.

    Args:
        console: When ``True``, also prints each finished span as single-line
            JSON to stdout.

    Returns:
        The ``InMemorySpanExporter`` that accumulates finished spans. Pass it
        to ``span_records()`` to retrieve a stable list of span dicts.

    Raises:
        ImportError: If ``opentelemetry-sdk`` is not installed.
    """
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
            InMemorySpanExporter,
        )
    except ImportError as exc:
        LOGGER.error(
            "configure_local_tracing failed: opentelemetry-sdk is not installed. %s",
            _INSTALL_HINT,
        )
        raise ImportError(_INSTALL_HINT) from exc

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    if console:
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter

        provider.add_span_processor(
            SimpleSpanProcessor(
                ConsoleSpanExporter(formatter=_format_span_as_json_line)
            )
        )

    existing = trace.get_tracer_provider()
    # ProxyTracerProvider is the default no-op provider before any SDK is configured.
    if type(existing).__name__ != "ProxyTracerProvider":
        LOGGER.warning(
            "configure_local_tracing: a TracerProvider is already installed (%s). "
            "The new provider will not replace it; spans go to the existing provider.",
            type(existing).__name__,
        )
    else:
        trace.set_tracer_provider(provider)

    return exporter


def configure_phoenix_tracing(*, project_name: str = "default") -> None:
    """Registers an embedded Arize Phoenix tracer for notebook use.

    Delegates entirely to ``phoenix.otel.register()``, which installs a global
    ``TracerProvider`` that ships spans to the running Phoenix server. Start
    Phoenix before calling this function (e.g. ``px.launch_app()``).

    Args:
        project_name: Phoenix project name shown in the UI.

    Raises:
        ImportError: If ``arize-phoenix`` is not installed.
        RuntimeError: If Phoenix registration fails.
    """
    try:
        import phoenix as px  # type: ignore[import-not-found]
        from phoenix.otel import register  # type: ignore[import-not-found]
    except ImportError as exc:
        LOGGER.error(
            "configure_phoenix_tracing failed: arize-phoenix is not installed. %s",
            _INSTALL_HINT,
        )
        raise ImportError(_INSTALL_HINT) from exc

    try:
        px.launch_app()
        register(project_name=project_name)
        LOGGER.info(
            "configure_phoenix_tracing: Phoenix registered for project %r.",
            project_name,
        )
    except Exception as exc:
        LOGGER.error(
            "configure_phoenix_tracing: Phoenix registration failed: %s",
            exc,
        )
        raise RuntimeError(f"Phoenix registration failed: {exc}") from exc


def configure_otlp_tracing() -> bool:
    """Installs an OTLP HTTP exporter using standard OpenTelemetry env vars.

    Reads ``OTEL_EXPORTER_OTLP_ENDPOINT`` and ``OTEL_EXPORTER_OTLP_HEADERS``
    from the environment (populated by ``load_dotenv()`` or the shell). Returns
    ``False`` with a warning when the endpoint variable is absent so that
    notebook Act 2 cells self-skip cleanly without raising.

    Environment variables:

    - ``OTEL_EXPORTER_OTLP_ENDPOINT``: Required. Base URL of the OTLP receiver,
      e.g. ``https://app.phoenix.arize.com/v1/traces``.
    - ``OTEL_EXPORTER_OTLP_HEADERS``: Optional. Comma-separated ``key=value``
      pairs, e.g. ``api_key=<token>``.

    Returns:
        ``True`` if the provider was installed successfully, ``False`` if the
        endpoint variable is unset (caller should skip the cell).

    Raises:
        ImportError: If ``opentelemetry-sdk`` or the OTLP exporter are not
            installed.
        RuntimeError: If provider installation fails for any other reason.
    """
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        LOGGER.warning(
            "configure_otlp_tracing: OTEL_EXPORTER_OTLP_ENDPOINT is not set. "
            "Skipping OTLP provider installation. Set the variable in your .env "
            "and call load_dotenv() before this function."
        )
        return False

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (  # type: ignore[import-not-found]
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError as exc:
        LOGGER.error(
            "configure_otlp_tracing failed: OTLP exporter not installed. %s",
            _INSTALL_HINT,
        )
        raise ImportError(_INSTALL_HINT) from exc

    try:
        exporter = OTLPSpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(BatchSpanProcessor(exporter))

        existing = trace.get_tracer_provider()
        if type(existing).__name__ != "ProxyTracerProvider":
            LOGGER.warning(
                "configure_otlp_tracing: a TracerProvider is already installed (%s). "
                "The new OTLP provider will not replace it.",
                type(existing).__name__,
            )
            return False

        trace.set_tracer_provider(provider)
        LOGGER.info(
            "configure_otlp_tracing: OTLP provider installed, endpoint=%r.",
            endpoint,
        )
        return True
    except Exception as exc:
        LOGGER.error(
            "configure_otlp_tracing: provider installation failed: %s",
            exc,
        )
        raise RuntimeError(f"configure_otlp_tracing failed: {exc}") from exc


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


__all__ = [
    "configure_local_tracing",
    "configure_otlp_tracing",
    "configure_phoenix_tracing",
    "span_record",
    "span_records",
]
