from __future__ import annotations

from collections.abc import Iterator

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

SPAN_EXPORTER = InMemorySpanExporter()
TRACER_PROVIDER = TracerProvider()
TRACER_PROVIDER.add_span_processor(SimpleSpanProcessor(SPAN_EXPORTER))
trace.set_tracer_provider(TRACER_PROVIDER)


@pytest.fixture(autouse=True)
def clear_spans() -> Iterator[InMemorySpanExporter]:
    SPAN_EXPORTER.clear()
    yield SPAN_EXPORTER
    SPAN_EXPORTER.clear()


@pytest.fixture
def span_exporter() -> InMemorySpanExporter:
    return SPAN_EXPORTER
