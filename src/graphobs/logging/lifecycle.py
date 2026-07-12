"""Lifecycle log assembly and emission for structured graph logs."""

from __future__ import annotations

import logging as stdlib_logging
from collections.abc import Mapping, Sequence
from time import perf_counter_ns

from graphobs.logging.context import (
    CorrelationFields,
    LogContext,
    Metadata,
    field_names,
)
from graphobs.payloads import shape_summary

DEFAULT_ERROR_MESSAGE_MAX_LENGTH = 512
EVENT_LOGGER_NAME = "graphobs.logs"
INTERNAL_LOGGER = stdlib_logging.getLogger("graphobs.logging")
NS_PER_MS = 1_000_000


class LifecycleLogEmitter:
    """Owns structured graph lifecycle log state, payloads, and emission."""

    def __init__(
        self,
        log_context: LogContext,
        fields: CorrelationFields,
        logger: stdlib_logging.Logger,
        *,
        error_message_max_length: int = DEFAULT_ERROR_MESSAGE_MAX_LENGTH,
    ) -> None:
        if error_message_max_length < 4:
            raise ValueError("error_message_max_length must be at least 4")
        self.log_context = log_context
        self.fields = fields
        self.logger = logger
        self.error_message_max_length = error_message_max_length
        self._started_at_ns: dict[str, int] = {}
        self._metadata_by_run: dict[str, dict[str, object]] = {}

    def start(
        self,
        event: str,
        run_kind: str,
        serialized: Mapping[str, object] | None,
        value: object,
        *,
        run_id: object,
        parent_run_id: object | None,
        tags: Sequence[str] | None,
        metadata: Metadata | None,
    ) -> None:
        run_id_text = stringify_id(run_id)
        metadata_values = dict(metadata or {})
        self._started_at_ns[run_id_text] = perf_counter_ns()
        self._metadata_by_run[run_id_text] = metadata_values
        payload = build_start_payload(
            self.log_context,
            self.fields,
            event,
            run_kind,
            serialized,
            value,
            run_id=run_id,
            parent_run_id=parent_run_id,
            tags=tags,
            metadata=metadata_values,
        )
        self._emit(stdlib_logging.INFO, payload)

    def finish(
        self,
        event: str,
        run_kind: str,
        value: object,
        *,
        run_id: object,
        parent_run_id: object | None,
    ) -> None:
        run_id_text = stringify_id(run_id)
        metadata = self._metadata_by_run.pop(run_id_text, {})
        payload = build_finish_payload(
            self.log_context,
            self.fields,
            event,
            run_kind,
            value,
            run_id=run_id,
            parent_run_id=parent_run_id,
            metadata=metadata,
            duration_ms=self._duration_ms(run_id_text, event, run_kind),
        )
        self._emit(stdlib_logging.INFO, payload)

    def error(
        self,
        event: str,
        run_kind: str,
        error: BaseException,
        *,
        run_id: object,
        parent_run_id: object | None,
    ) -> None:
        run_id_text = stringify_id(run_id)
        metadata = self._metadata_by_run.pop(run_id_text, {})
        payload = build_error_payload(
            self.log_context,
            self.fields,
            event,
            run_kind,
            error,
            run_id=run_id,
            parent_run_id=parent_run_id,
            metadata=metadata,
            duration_ms=self._duration_ms(run_id_text, event, run_kind),
            error_message_max_length=self.error_message_max_length,
        )
        self._emit(stdlib_logging.ERROR, payload)

    def _duration_ms(
        self,
        run_id: str,
        event: str,
        run_kind: str,
    ) -> float | None:
        started_at_ns = self._started_at_ns.pop(run_id, None)
        if started_at_ns is None:
            self._emit(
                stdlib_logging.WARNING,
                duration_missing_payload(run_id, event, run_kind),
            )
            return None
        return elapsed_duration_ms(started_at_ns, perf_counter_ns())

    def _emit(self, level: int, payload: Mapping[str, object]) -> None:
        event = str(payload.get("event", "unknown"))
        detail = payload.get("warning")
        message = (
            "graph lifecycle event: %s"
            if detail is None
            else "graph lifecycle event: %s: %s"
        )
        args = (event,) if detail is None else (event, detail)
        try:
            self.logger.log(
                level,
                message,
                *args,
                extra={"graph_log": dict(payload), "graph_log_event": event},
            )
        except Exception as exc:
            INTERNAL_LOGGER.error("Failed to emit graph log event %s: %s", event, exc)
            raise


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
            "input_summary": shape_summary(value),
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
    payload["output_summary"] = shape_summary(value)
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
    warning = f"missing start time for run_id {run_id}"
    return {
        "event": "duration_missing",
        "run_kind": run_kind,
        "run_id": run_id,
        "finished_event": event,
        "warning": warning,
    }


def elapsed_duration_ms(started_at_ns: int, finished_at_ns: int) -> float:
    return round((finished_at_ns - started_at_ns) / NS_PER_MS, 3)


def reject_correlation_conflict(
    key: str,
    existing: object,
    incoming: object,
    *,
    failure_context: str,
) -> None:
    """Raises when an existing value disagrees with an incoming correlation value.

    Shared by invoke-config assembly and per-event payload assembly so both
    report a correlation conflict identically. Does nothing when there is no
    existing value or the values agree.

    Args:
        key: Correlation field name being merged.
        existing: Value already present for the field, if any.
        incoming: Value being merged in.
        failure_context: Human-readable prefix for the failure log.

    Raises:
        ValueError: If ``existing`` is not ``None`` and differs from ``incoming``.
    """
    if existing is None or existing == incoming:
        return
    error = ValueError(f"metadata correlation field {key!r} conflicts with LogContext")
    INTERNAL_LOGGER.error("%s: %s", failure_context, error)
    raise error


def merge_correlation(
    log_context: LogContext,
    fields: CorrelationFields,
    metadata: Metadata,
) -> dict[str, object]:
    correlation = log_context.as_mapping(fields)
    for key in field_names(fields):
        metadata_value = metadata.get(key)
        if metadata_value is None:
            continue
        reject_correlation_conflict(
            key,
            correlation.get(key),
            metadata_value,
            failure_context="Failed to build graph log payload",
        )
        correlation[key] = metadata_value
    return correlation


def stringify_id(value: object) -> str:
    return str(value)


def run_name(
    serialized: Mapping[str, object] | None,
    metadata: Metadata,
) -> str | None:
    for key in ("langgraph_node", "name"):
        value = metadata.get(key)
        if value is not None:
            return str(value)
    if serialized is None:
        return None
    serialized_name = serialized.get("name")
    return str(serialized_name) if serialized_name is not None else None


def truncate_error_message(message: str, max_length: int) -> tuple[str, bool]:
    if len(message) <= max_length:
        return message, False
    return f"{message[: max_length - 3]}...", True
