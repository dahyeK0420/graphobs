"""LangGraph invoke config helpers for structured lifecycle logging."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypedDict

from graphobs.logging.callback import GraphLogCallback
from graphobs.logging.context import (
    INTERNAL_LOGGER,
    CorrelationFields,
    LogContext,
    Metadata,
    reconcile_correlation,
)


class InvokeConfig(TypedDict):
    """LangGraph invoke config shape returned by ``build_invoke_config``."""

    callbacks: list[object]
    metadata: dict[str, object]


def build_invoke_config(
    log_context: LogContext,
    callbacks: Sequence[object] | None = None,
    metadata: Metadata | None = None,
    *,
    fields: CorrelationFields | None = None,
) -> InvokeConfig:
    """Builds LangGraph invoke configuration with logging correlation.

    Args:
        log_context: Correlation envelope to attach to callbacks and metadata.
        callbacks: Existing callbacks to preserve after the log callback.
        metadata: Existing invoke metadata.
        fields: Optional correlation field-name configuration.

    Returns:
        A LangGraph-compatible config dictionary containing ``callbacks`` and
        ``metadata``.

    Raises:
        ValueError: If metadata already contains a different correlation value.
    """
    active_fields = fields or CorrelationFields()
    merged_metadata = merge_metadata(log_context, active_fields, metadata or {})
    active_callbacks: list[object] = [
        GraphLogCallback(log_context, fields=active_fields),
    ]
    active_callbacks.extend(callbacks or ())
    return {"callbacks": active_callbacks, "metadata": merged_metadata}


def merge_metadata(
    log_context: LogContext,
    fields: CorrelationFields,
    metadata: Metadata,
) -> dict[str, object]:
    """Merges invoke metadata with correlation fields from the log context."""
    try:
        return reconcile_correlation(dict(metadata), log_context.as_metadata(fields))
    except ValueError as error:
        INTERNAL_LOGGER.error("Failed to build invoke config: %s", error)
        raise


__all__ = ["InvokeConfig", "build_invoke_config"]
