"""Payload assembly helpers for structured graph lifecycle logs.

These functions build the structured log payloads a graph lifecycle event
records. They are pure: they hold no state and emit nothing. The stateful owner
that times runs, calls them, and emits the result is
``graphobs.logging.callback.GraphLogCallback``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from graphobs._observability.payload_policy import payload_summary
from graphobs.logging.context import (
    INTERNAL_LOGGER,
    CorrelationFields,
    LogContext,
    Metadata,
    field_names,
    reconcile_correlation,
)

DEFAULT_ERROR_MESSAGE_MAX_LENGTH = 512
EVENT_LOGGER_NAME = "graphobs.logs"
NS_PER_MS = 1_000_000


def build_start_payload(
    log_context: LogContext,
    fields: CorrelationFields,
    event: str,
    run_kind: str,
    serialized: Mapping[str, object] | None,
    value: object,
    *,
    run_id: object,
    parent_run_id: object | None,
    tags: Sequence[str] | None,
    metadata: Metadata,
) -> dict[str, object]:
    """Builds the structured payload for a run-start event.

    Extends the common base payload with the resolved run name, tags, and a
    projected summary of the run's input value.
    """
    payload = base_payload(
        log_context,
        fields,
        event,
        run_kind,
        run_id=run_id,
        parent_run_id=parent_run_id,
        metadata=metadata,
    )
    payload.update(
        {
            "run_name": run_name(serialized, metadata),
            "tags": tuple(tags or ()),
            "input_summary": payload_summary(value),
        }
    )
    return payload


def build_finish_payload(
    log_context: LogContext,
    fields: CorrelationFields,
    event: str,
    run_kind: str,
    value: object,
    *,
    run_id: object,
    parent_run_id: object | None,
    metadata: Metadata,
    duration_ms: float | None,
) -> dict[str, object]:
    """Builds the structured payload for a run-finish event.

    Extends the common base payload with the elapsed ``duration_ms`` and a
    projected summary of the run's output value.
    """
    payload = base_payload(
        log_context,
        fields,
        event,
        run_kind,
        run_id=run_id,
        parent_run_id=parent_run_id,
        metadata=metadata,
    )
    payload["duration_ms"] = duration_ms
    payload["output_summary"] = payload_summary(value)
    return payload


def build_error_payload(
    log_context: LogContext,
    fields: CorrelationFields,
    event: str,
    run_kind: str,
    error: BaseException,
    *,
    run_id: object,
    parent_run_id: object | None,
    metadata: Metadata,
    duration_ms: float | None,
    error_message_max_length: int,
) -> dict[str, object]:
    """Builds the structured payload for a run-error event.

    Extends the common base payload with the elapsed ``duration_ms``, the
    error's type name, and its message truncated to
    ``error_message_max_length`` (with a flag recording whether it was cut).
    """
    error_message, truncated = truncate_error_message(
        str(error),
        error_message_max_length,
    )
    payload = base_payload(
        log_context,
        fields,
        event,
        run_kind,
        run_id=run_id,
        parent_run_id=parent_run_id,
        metadata=metadata,
    )
    payload.update(
        {
            "duration_ms": duration_ms,
            "error_type": type(error).__name__,
            "error_message": error_message,
            "error_message_truncated": truncated,
        }
    )
    return payload


def base_payload(
    log_context: LogContext,
    fields: CorrelationFields,
    event: str,
    run_kind: str,
    *,
    run_id: object,
    parent_run_id: object | None,
    metadata: Metadata,
) -> dict[str, object]:
    """Builds the fields shared by every lifecycle event.

    Emits the event name, run kind, stringified run and parent-run ids, the
    sorted metadata keys, and the correlation fields reconciled from the log
    context and metadata overlay.
    """
    correlation = merge_correlation(
        log_context,
        fields,
        metadata,
    )
    payload: dict[str, object] = {
        "event": event,
        "run_kind": run_kind,
        "run_id": stringify_id(run_id),
        "parent_run_id": (
            stringify_id(parent_run_id) if parent_run_id is not None else None
        ),
        "metadata_keys": tuple(sorted(str(key) for key in metadata)),
    }
    payload.update(correlation)
    return payload


def duration_missing_payload(
    run_id: str,
    event: str,
    run_kind: str,
) -> dict[str, object]:
    """Builds a warning payload for a finish event with no recorded start time.

    Emitted in place of a duration when the matching start event was never
    seen, so no elapsed time can be computed.
    """
    warning = f"missing start time for run_id {run_id}"
    return {
        "event": "duration_missing",
        "run_kind": run_kind,
        "run_id": run_id,
        "finished_event": event,
        "warning": warning,
    }


def elapsed_duration_ms(started_at_ns: int, finished_at_ns: int) -> float:
    """Returns the elapsed milliseconds between two nanosecond timestamps.

    Rounded to three decimal places (microsecond resolution).
    """
    return round((finished_at_ns - started_at_ns) / NS_PER_MS, 3)


def merge_correlation(
    log_context: LogContext,
    fields: CorrelationFields,
    metadata: Metadata,
) -> dict[str, object]:
    """Reconciles correlation fields from the log context and run metadata.

    Metadata values for known correlation field names overlay the log
    context's values.

    Raises:
        ValueError: If the context and metadata disagree on a field. The
            conflict is logged before the error propagates.
    """
    overlay = {name: metadata[name] for name in field_names(fields) if name in metadata}
    try:
        return reconcile_correlation(log_context.as_mapping(fields), overlay)
    except ValueError as error:
        INTERNAL_LOGGER.error("Failed to build graph log payload: %s", error)
        raise


def stringify_id(value: object) -> str:
    """Returns the string form of a run identifier."""
    return str(value)


def run_name(
    serialized: Mapping[str, object] | None,
    metadata: Metadata,
) -> str | None:
    """Derives a human-readable run name.

    Prefers the ``langgraph_node`` then ``name`` metadata keys, falling back to
    the serialized payload's ``name``. Returns ``None`` when none is present.
    """
    for key in ("langgraph_node", "name"):
        value = metadata.get(key)
        if value is not None:
            return str(value)
    if serialized is None:
        return None
    serialized_name = serialized.get("name")
    return str(serialized_name) if serialized_name is not None else None


def truncate_error_message(message: str, max_length: int) -> tuple[str, bool]:
    """Truncates a message to ``max_length``, reporting whether it was cut.

    When truncation is needed the returned message ends in an ellipsis and its
    length still respects ``max_length``. Returns ``(message, was_truncated)``.
    """
    if len(message) <= max_length:
        return message, False
    return f"{message[: max_length - 3]}...", True
