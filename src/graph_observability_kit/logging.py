"""Structured lifecycle logging helpers for graph runs."""

from __future__ import annotations

import logging as stdlib_logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from time import perf_counter_ns
from typing import TypedDict

from graph_observability_kit._shape_summary import shape_summary

CorrelationValue = str | int | float | bool
Metadata = Mapping[str, object]

DEFAULT_ERROR_MESSAGE_MAX_LENGTH = 512
EVENT_LOGGER_NAME = "graph_observability_kit.logs"
INTERNAL_LOGGER = stdlib_logging.getLogger(__name__)
NS_PER_MS = 1_000_000


class InvokeConfig(TypedDict):
    """LangGraph invoke config shape returned by ``build_invoke_config``."""

    callbacks: list[object]
    metadata: dict[str, object]


@dataclass(frozen=True, init=False)
class CorrelationFields:
    """Configures metadata field names used for log correlation.

    Args:
        session: Field name for the session identifier.
        conversation: Field name for the conversation identifier.
        turn: Field name for the turn identifier.
        request: Field name for the request identifier.
        trace: Field name for the trace identifier.
    """

    session: str
    conversation: str
    turn: str
    request: str
    trace: str

    def __init__(
        self,
        *,
        session: str = "session_id",
        conversation: str = "conversation_id",
        turn: str = "turn_id",
        request: str = "request_id",
        trace: str = "trace_id",
    ) -> None:
        """Creates correlation field names."""
        object.__setattr__(self, "session", _validate_field_name(session, "session"))
        object.__setattr__(
            self,
            "conversation",
            _validate_field_name(conversation, "conversation"),
        )
        object.__setattr__(self, "turn", _validate_field_name(turn, "turn"))
        object.__setattr__(self, "request", _validate_field_name(request, "request"))
        object.__setattr__(self, "trace", _validate_field_name(trace, "trace"))


@dataclass(frozen=True, init=False)
class LogContext:
    """Carries optional user-provided correlation identifiers for one run.

    Args:
        session_id: Stable session identifier.
        conversation_id: Conversation identifier.
        turn_id: Turn identifier.
        request_id: Request identifier.
        trace_id: Trace identifier shared with tracing attributes when desired.
    """

    session_id: CorrelationValue | None
    conversation_id: CorrelationValue | None
    turn_id: CorrelationValue | None
    request_id: CorrelationValue | None
    trace_id: CorrelationValue | None

    def __init__(
        self,
        *,
        session_id: CorrelationValue | None = None,
        conversation_id: CorrelationValue | None = None,
        turn_id: CorrelationValue | None = None,
        request_id: CorrelationValue | None = None,
        trace_id: CorrelationValue | None = None,
    ) -> None:
        """Creates a log correlation envelope."""
        object.__setattr__(
            self,
            "session_id",
            _validate_correlation_value(session_id, "session_id"),
        )
        object.__setattr__(
            self,
            "conversation_id",
            _validate_correlation_value(conversation_id, "conversation_id"),
        )
        object.__setattr__(
            self,
            "turn_id",
            _validate_correlation_value(turn_id, "turn_id"),
        )
        object.__setattr__(
            self,
            "request_id",
            _validate_correlation_value(request_id, "request_id"),
        )
        object.__setattr__(
            self,
            "trace_id",
            _validate_correlation_value(trace_id, "trace_id"),
        )

    def as_metadata(self, fields: CorrelationFields | None = None) -> dict[str, object]:
        """Returns correlation values using configurable metadata names.

        Args:
            fields: Optional field-name configuration.

        Returns:
            Metadata suitable for LangGraph invoke configuration.
        """
        return self.as_mapping(fields)

    def as_attributes(
        self,
        fields: CorrelationFields | None = None,
    ) -> dict[str, object]:
        """Returns correlation values suitable for span attributes.

        Args:
            fields: Optional field-name configuration.

        Returns:
            Flat attributes using the same field names as structured logs.
        """
        return self.as_mapping(fields)

    def as_mapping(self, fields: CorrelationFields | None = None) -> dict[str, object]:
        """Returns non-empty correlation values with configured field names.

        Args:
            fields: Optional field-name configuration.

        Returns:
            A dictionary containing only populated correlation identifiers.
        """
        active_fields = fields or CorrelationFields()
        values = {
            active_fields.session: self.session_id,
            active_fields.conversation: self.conversation_id,
            active_fields.turn: self.turn_id,
            active_fields.request: self.request_id,
            active_fields.trace: self.trace_id,
        }
        return {key: value for key, value in values.items() if value is not None}


class GraphLogCallback:
    """LangChain/LangGraph-compatible callback for structured lifecycle logs.

    The callback intentionally records lifecycle shape and correlation only. It
    summarizes inputs and outputs by type, size, and keys instead of storing
    full state values.
    """

    raise_error = True
    run_inline = False
    ignore_chain = False
    ignore_tool = False
    ignore_llm = True
    ignore_retry = True
    ignore_agent = True
    ignore_retriever = True
    ignore_chat_model = True
    ignore_custom_event = True

    def __init__(
        self,
        log_context: LogContext | None = None,
        *,
        fields: CorrelationFields | None = None,
        logger: stdlib_logging.Logger | None = None,
        error_message_max_length: int = DEFAULT_ERROR_MESSAGE_MAX_LENGTH,
    ) -> None:
        """Creates a structured log callback.

        Args:
            log_context: Optional default correlation envelope.
            fields: Optional correlation field-name configuration.
            logger: Optional stdlib logger. Applications configure handlers.
            error_message_max_length: Maximum stored error message length.

        Raises:
            ValueError: If ``error_message_max_length`` is too small.
        """
        if error_message_max_length < 4:
            raise ValueError("error_message_max_length must be at least 4")
        self.log_context = log_context or LogContext()
        self.fields = fields or CorrelationFields()
        self.logger = logger or stdlib_logging.getLogger(EVENT_LOGGER_NAME)
        self.error_message_max_length = error_message_max_length
        self._started_at_ns: dict[str, int] = {}
        self._metadata_by_run: dict[str, dict[str, object]] = {}

    def on_chain_start(
        self,
        serialized: Mapping[str, object] | None,
        inputs: Mapping[str, object],
        *,
        run_id: object,
        parent_run_id: object | None = None,
        tags: Sequence[str] | None = None,
        metadata: Metadata | None = None,
        **kwargs: object,
    ) -> None:
        """Logs a chain or graph-node start event."""
        self._start_run(
            "chain_start",
            "chain",
            serialized,
            inputs,
            run_id=run_id,
            parent_run_id=parent_run_id,
            tags=tags,
            metadata=metadata,
        )

    def on_chain_end(
        self,
        outputs: Mapping[str, object],
        *,
        run_id: object,
        parent_run_id: object | None = None,
        **kwargs: object,
    ) -> None:
        """Logs a chain or graph-node end event."""
        self._finish_run(
            "chain_end",
            "chain",
            outputs,
            run_id=run_id,
            parent_run_id=parent_run_id,
        )

    def on_chain_error(
        self,
        error: BaseException,
        *,
        run_id: object,
        parent_run_id: object | None = None,
        **kwargs: object,
    ) -> None:
        """Logs a chain or graph-node error event."""
        self._error_run(
            "chain_error",
            "chain",
            error,
            run_id=run_id,
            parent_run_id=parent_run_id,
        )

    def on_tool_start(
        self,
        serialized: Mapping[str, object] | None,
        input_str: str,
        *,
        run_id: object,
        parent_run_id: object | None = None,
        tags: Sequence[str] | None = None,
        metadata: Metadata | None = None,
        inputs: Mapping[str, object] | None = None,
        **kwargs: object,
    ) -> None:
        """Logs a tool start event without storing the tool input value."""
        payload_input: object = inputs if inputs is not None else input_str
        self._start_run(
            "tool_start",
            "tool",
            serialized,
            payload_input,
            run_id=run_id,
            parent_run_id=parent_run_id,
            tags=tags,
            metadata=metadata,
        )

    def on_tool_end(
        self,
        output: object,
        *,
        run_id: object,
        parent_run_id: object | None = None,
        **kwargs: object,
    ) -> None:
        """Logs a tool end event without storing the tool output value."""
        self._finish_run(
            "tool_end",
            "tool",
            output,
            run_id=run_id,
            parent_run_id=parent_run_id,
        )

    def on_tool_error(
        self,
        error: BaseException,
        *,
        run_id: object,
        parent_run_id: object | None = None,
        **kwargs: object,
    ) -> None:
        """Logs a tool error event."""
        self._error_run(
            "tool_error",
            "tool",
            error,
            run_id=run_id,
            parent_run_id=parent_run_id,
        )

    def _start_run(
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
        run_id_text = _stringify_id(run_id)
        metadata_values = dict(metadata or {})
        self._started_at_ns[run_id_text] = perf_counter_ns()
        self._metadata_by_run[run_id_text] = metadata_values
        payload = self._base_payload(
            event,
            run_kind,
            run_id=run_id,
            parent_run_id=parent_run_id,
            metadata=metadata_values,
        )
        payload.update(
            {
                "run_name": _run_name(serialized, metadata_values),
                "tags": tuple(tags or ()),
                "input_summary": shape_summary(value),
            }
        )
        self._emit(stdlib_logging.INFO, payload)

    def _finish_run(
        self,
        event: str,
        run_kind: str,
        value: object,
        *,
        run_id: object,
        parent_run_id: object | None,
    ) -> None:
        run_id_text = _stringify_id(run_id)
        metadata = self._metadata_by_run.pop(run_id_text, {})
        payload = self._base_payload(
            event,
            run_kind,
            run_id=run_id,
            parent_run_id=parent_run_id,
            metadata=metadata,
        )
        payload["duration_ms"] = self._duration_ms(run_id_text, event, run_kind)
        payload["output_summary"] = shape_summary(value)
        self._emit(stdlib_logging.INFO, payload)

    def _error_run(
        self,
        event: str,
        run_kind: str,
        error: BaseException,
        *,
        run_id: object,
        parent_run_id: object | None,
    ) -> None:
        run_id_text = _stringify_id(run_id)
        metadata = self._metadata_by_run.pop(run_id_text, {})
        error_message, truncated = _truncate_error_message(
            str(error),
            self.error_message_max_length,
        )
        payload = self._base_payload(
            event,
            run_kind,
            run_id=run_id,
            parent_run_id=parent_run_id,
            metadata=metadata,
        )
        payload.update(
            {
                "duration_ms": self._duration_ms(run_id_text, event, run_kind),
                "error_type": type(error).__name__,
                "error_message": error_message,
                "error_message_truncated": truncated,
            }
        )
        self._emit(stdlib_logging.ERROR, payload)

    def _base_payload(
        self,
        event: str,
        run_kind: str,
        *,
        run_id: object,
        parent_run_id: object | None,
        metadata: Metadata,
    ) -> dict[str, object]:
        correlation = _merge_correlation(
            self.log_context,
            self.fields,
            metadata,
        )
        payload: dict[str, object] = {
            "event": event,
            "run_kind": run_kind,
            "run_id": _stringify_id(run_id),
            "parent_run_id": (
                _stringify_id(parent_run_id) if parent_run_id is not None else None
            ),
            "metadata_keys": tuple(sorted(str(key) for key in metadata)),
        }
        payload.update(correlation)
        return payload

    def _duration_ms(
        self,
        run_id: str,
        event: str,
        run_kind: str,
    ) -> float | None:
        started_at_ns = self._started_at_ns.pop(run_id, None)
        if started_at_ns is None:
            warning = f"missing start time for run_id {run_id}"
            self._emit(
                stdlib_logging.WARNING,
                {
                    "event": "duration_missing",
                    "run_kind": run_kind,
                    "run_id": run_id,
                    "finished_event": event,
                    "warning": warning,
                },
            )
            return None
        return round((perf_counter_ns() - started_at_ns) / NS_PER_MS, 3)

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
    merged_metadata = _merge_metadata(log_context, active_fields, metadata or {})
    active_callbacks: list[object] = [
        GraphLogCallback(log_context, fields=active_fields),
    ]
    active_callbacks.extend(callbacks or ())
    return {"callbacks": active_callbacks, "metadata": merged_metadata}


def _validate_field_name(value: str, label: str) -> str:
    if not value.strip():
        raise ValueError(f"{label} correlation field name must not be blank")
    return value


def _validate_correlation_value(
    value: CorrelationValue | None,
    label: str,
) -> CorrelationValue | None:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        raise ValueError(f"{label} must not be blank")
    return value


def _merge_metadata(
    log_context: LogContext,
    fields: CorrelationFields,
    metadata: Metadata,
) -> dict[str, object]:
    merged = dict(metadata)
    for key, value in log_context.as_metadata(fields).items():
        existing = merged.get(key)
        if existing is not None and existing != value:
            error = ValueError(
                f"metadata correlation field {key!r} conflicts with LogContext"
            )
            INTERNAL_LOGGER.error("Failed to build invoke config: %s", error)
            raise error
        merged[key] = value
    return merged


def _merge_correlation(
    log_context: LogContext,
    fields: CorrelationFields,
    metadata: Metadata,
) -> dict[str, object]:
    correlation = log_context.as_mapping(fields)
    for key in _field_names(fields):
        metadata_value = metadata.get(key)
        if metadata_value is None:
            continue
        existing = correlation.get(key)
        if existing is not None and existing != metadata_value:
            error = ValueError(
                f"metadata correlation field {key!r} conflicts with LogContext"
            )
            INTERNAL_LOGGER.error("Failed to build graph log payload: %s", error)
            raise error
        correlation[key] = metadata_value
    return correlation


def _field_names(fields: CorrelationFields) -> tuple[str, ...]:
    return (
        fields.session,
        fields.conversation,
        fields.turn,
        fields.request,
        fields.trace,
    )


def _stringify_id(value: object) -> str:
    return str(value)


def _run_name(
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


def _truncate_error_message(message: str, max_length: int) -> tuple[str, bool]:
    if len(message) <= max_length:
        return message, False
    return f"{message[: max_length - 3]}...", True


__all__ = [
    "CorrelationFields",
    "GraphLogCallback",
    "LogContext",
    "build_invoke_config",
]
