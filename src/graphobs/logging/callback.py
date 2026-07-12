"""LangChain/LangGraph callback that emits structured lifecycle logs."""

from __future__ import annotations

import logging as stdlib_logging
from collections.abc import Mapping, Sequence
from time import perf_counter_ns

from graphobs.logging.context import (
    CorrelationFields,
    LogContext,
    Metadata,
)
from graphobs.logging.lifecycle import (
    DEFAULT_ERROR_MESSAGE_MAX_LENGTH,
    EVENT_LOGGER_NAME,
    INTERNAL_LOGGER,
    build_error_payload,
    build_finish_payload,
    build_start_payload,
    duration_missing_payload,
    elapsed_duration_ms,
    stringify_id,
)


class GraphLogCallback:
    """LangChain/LangGraph-compatible callback for structured lifecycle logs.

    Owns the lifecycle timing state, assembles each structured log payload
    through the ``graphobs.logging.lifecycle`` helpers, and emits it. The
    callback intentionally records lifecycle shape and correlation only: it
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
        self._start(
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
        self._finish(
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
        self._error(
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
        self._start(
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
        self._finish(
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
        self._error(
            "tool_error",
            "tool",
            error,
            run_id=run_id,
            parent_run_id=parent_run_id,
        )

    def _start(
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

    def _finish(
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

    def _error(
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


__all__ = ["GraphLogCallback"]
