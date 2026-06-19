from __future__ import annotations

import builtins
from collections.abc import Mapping
from typing import Any, cast

import pytest

from graph_observability_kit.demo.span_records import span_record
from graph_observability_kit.demo.tracing_setup import (
    configure_local_tracing,
    configure_otlp_tracing,
    configure_phoenix_tracing,
)

INSTALL_HINT = (
    'Install the demo dependencies first: pip install "graph-observability-kit[demo]"'
)


def test_configure_local_tracing_fails_lazily_with_install_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _block_imports(monkeypatch, ("opentelemetry.sdk",))

    with pytest.raises(ImportError, match=_install_hint_regex()):
        configure_local_tracing()


def test_configure_phoenix_tracing_fails_lazily_with_install_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _block_imports(monkeypatch, ("phoenix",))

    with pytest.raises(ImportError, match=_install_hint_regex()):
        configure_phoenix_tracing()


def test_configure_otlp_tracing_fails_lazily_with_install_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
    _block_imports(monkeypatch, ("opentelemetry.exporter.otlp",))

    with pytest.raises(ImportError, match=_install_hint_regex()):
        configure_otlp_tracing()


def test_span_record_fails_lazily_with_install_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _block_imports(monkeypatch, ("openinference.semconv.trace",))

    with pytest.raises(ImportError, match=_install_hint_regex()):
        span_record(cast(Any, _Span()))


def _block_imports(
    monkeypatch: pytest.MonkeyPatch,
    prefixes: tuple[str, ...],
) -> None:
    original_import = builtins.__import__

    def blocked_import(
        name: str,
        globals: Mapping[str, object] | None = None,
        locals: Mapping[str, object] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> object:
        if any(name == prefix or name.startswith(f"{prefix}.") for prefix in prefixes):
            raise ImportError(f"blocked import for test: {name}")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", blocked_import)


def _install_hint_regex() -> str:
    return (
        r"Install the demo dependencies first: pip install "
        r'"graph-observability-kit\[demo\]"'
    )


class _StatusCode:
    name = "UNSET"


class _Status:
    status_code = _StatusCode()


class _Span:
    def __init__(self) -> None:
        self.name = "demo"
        self.attributes: dict[str, object] = {}
        self.status = _Status()
