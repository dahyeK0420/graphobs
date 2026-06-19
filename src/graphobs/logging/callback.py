"""LangChain/LangGraph callback adapter for structured lifecycle logs."""

from __future__ import annotations

import logging as stdlib_logging
from collections.abc import Mapping, Sequence

from graphobs.logging.context import (
    CorrelationFields,
    LogContext,
    Metadata,
)
from graphobs.logging.lifecycle import (
    DEFAULT_ERROR_MESSAGE_MAX_LENGTH,
    EVENT_LOGGER_NAME,
    LifecycleLogEmitter,
)


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
        self.log_context = log_context or LogContext()
        self.fields = fields or CorrelationFields()
        self.logger = logger or stdlib_logging.getLogger(EVENT_LOGGER_NAME)
        self.error_message_max_length = error_message_max_length
        self._lifecycle = LifecycleLogEmitter(
            self.log_context,
            self.fields,
            self.logger,
            error_message_max_length=error_message_max_length,
        )

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
        self._lifecycle.start(
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
        self._lifecycle.finish(
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
        self._lifecycle.error(
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
        self._lifecycle.start(
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
        self._lifecycle.finish(
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
        self._lifecycle.error(
            "tool_error",
            "tool",
            error,
            run_id=run_id,
            parent_run_id=parent_run_id,
        )


__all__ = ["GraphLogCallback"]
