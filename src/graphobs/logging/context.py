"""Correlation context models for structured graph lifecycle logs."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TypeAlias

CorrelationValue: TypeAlias = str | int | float | bool
Metadata: TypeAlias = Mapping[str, object]

# Package-internal diagnostic channel shared by the logging modules to report
# their own failures (payload assembly, invoke-config build, event emit). This
# is distinct from the event log channel (``EVENT_LOGGER_NAME``) that carries
# lifecycle events. Intentionally not part of ``__all__``: it is internal.
INTERNAL_LOGGER = logging.getLogger("graphobs.logging")


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


def field_names(fields: CorrelationFields) -> tuple[str, ...]:
    """Returns the configured correlation field names in stable order."""
    return (
        fields.session,
        fields.conversation,
        fields.turn,
        fields.request,
        fields.trace,
    )


def reconcile_correlation(
    base: Mapping[str, object],
    overlay: Mapping[str, object],
) -> dict[str, object]:
    """Merges two sources of correlation values, rejecting conflicts.

    A correlation field may be set by both a ``LogContext`` and invoke
    metadata. Setting the same field to two different non-empty values is a
    caller error and raises; ``None`` overlay values are ignored. This is the
    single rule shared by invoke-config assembly (a ``LogContext`` overlaid on
    caller metadata) and per-event log assembly (event metadata overlaid on a
    ``LogContext``); callers add their own failure context.

    Args:
        base: Correlation values to start from.
        overlay: Correlation values to merge in, ignoring ``None`` values.

    Returns:
        The merged correlation values.

    Raises:
        ValueError: If ``base`` and ``overlay`` set one field to different
            non-empty values.
    """
    merged = dict(base)
    for key, value in overlay.items():
        if value is None:
            continue
        existing = merged.get(key)
        if existing is not None and existing != value:
            raise ValueError(
                f"metadata correlation field {key!r} conflicts with LogContext"
            )
        merged[key] = value
    return merged


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


__all__ = [
    "CorrelationFields",
    "CorrelationValue",
    "LogContext",
    "Metadata",
    "field_names",
    "reconcile_correlation",
]
