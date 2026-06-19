from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from typing import IO, Protocol, cast

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from graph_observability_kit.contracts.models import StateContractError
from graph_observability_kit.demo.span_records import span_record as span_record
from graph_observability_kit.demo.span_records import span_records as span_records
from graph_observability_kit.demo.tracing_setup import configure_local_tracing
from graph_observability_kit.logging.callback import GraphLogCallback
from graph_observability_kit.logging.context import LogContext

MappingState = Mapping[str, object]


class RawGraphBuilder(Protocol):
    def add_node(self, name: str, fn: object) -> object: ...


def add_raw_node(graph: object, name: str, fn: object) -> None:
    """Adds an unwrapped example node without depending on LangGraph internals."""
    cast(RawGraphBuilder, graph).add_node(name, fn)


def configure_tracing(
    *,
    console_stream: IO[str] | None = None,
) -> InMemorySpanExporter:
    """Configures local in-memory tracing for a standalone example process.

    When ``console_stream`` is provided, finished spans are also written as
    single-line JSON to that stream via a ``ConsoleSpanExporter``. This is
    used by the ``backend_export`` example to capture console output for
    testing. For new code, prefer ``configure_local_tracing(console=True)``.
    """
    if console_stream is None:
        return configure_local_tracing()

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    provider.add_span_processor(
        SimpleSpanProcessor(
            ConsoleSpanExporter(
                out=console_stream,
                formatter=lambda s: f"{json.dumps(span_record(s), sort_keys=True)}\n",
            )
        )
    )
    existing = trace.get_tracer_provider()
    if type(existing).__name__ != "ProxyTracerProvider":
        logging.getLogger(__name__).warning(
            "configure_tracing: a TracerProvider is already installed (%s). "
            "The new provider will not replace it.",
            type(existing).__name__,
        )
    else:
        trace.set_tracer_provider(provider)
    return exporter


def capture_validation_error(action: Callable[[], object]) -> dict[str, object]:
    """Runs an action that is expected to fail contract validation."""
    try:
        action()
    except StateContractError as exc:
        return {
            "type": type(exc).__name__,
            "contract": exc.contract_name,
            "paths": list(exc.undeclared_paths),
            "message": str(exc),
        }
    raise AssertionError("expected StateContractError")


def lifecycle_log_records(
    *,
    run_name: str,
    input_value: Mapping[str, object],
    output_value: Mapping[str, object],
) -> list[dict[str, object]]:
    """Creates deterministic lifecycle log records for docs examples."""
    logger = logging.getLogger(f"examples.graph_observability_kit.{run_name}")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.INFO)
    handler = _CollectingHandler()
    logger.addHandler(handler)

    context = LogContext(session_id="example-session", request_id="request-1")
    callback = GraphLogCallback(context, logger=logger)
    run_id = f"{run_name}-run"
    callback.on_chain_start(
        {"name": run_name},
        input_value,
        run_id=run_id,
        metadata=context.as_metadata(),
    )
    callback.on_chain_end(output_value, run_id=run_id)

    return [_normalize_log_record(record) for record in handler.records]


def print_json(payload: Mapping[str, object]) -> None:
    """Prints stable JSON for example commands and snippet files."""
    print(json.dumps(payload, indent=2, sort_keys=True))


def _normalize_log_record(record: logging.LogRecord) -> dict[str, object]:
    graph_log = cast(dict[str, object], vars(record)["graph_log"])
    normalized = {
        "event": graph_log["event"],
        "run_kind": graph_log["run_kind"],
        "run_name": graph_log.get("run_name"),
        "session_id": graph_log.get("session_id"),
        "request_id": graph_log.get("request_id"),
    }
    for key in ("input_summary", "output_summary"):
        if key in graph_log:
            normalized[key] = graph_log[key]
    return normalized


class _CollectingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)
