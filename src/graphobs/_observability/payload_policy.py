"""Shared observability payload policy helpers."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from typing import Literal

from graphobs.payloads import message_compact_summary, shape_summary

PayloadKind = Literal["input", "output"]


def prepare_trace_payload(value: object, *, mode: object) -> object:
    """Prepares a value according to the default trace payload mode."""
    mode_value = _mode_value(mode)
    if mode_value == "message_compact":
        return message_compact_summary(value)
    if mode_value == "compact":
        return shape_summary(value)
    if mode_value == "full":
        return value
    raise ValueError(f"unsupported trace payload mode: {mode!r}")


def serialize_trace_payload(value: object, *, mode: object) -> str:
    """Serializes a trace payload using the shared default payload policy."""
    prepared = prepare_trace_payload(value, mode=mode)
    return json.dumps(prepared, sort_keys=True, separators=(",", ":"))


def payload_summary(value: object) -> dict[str, object]:
    """Returns the canonical compact payload summary."""
    return shape_summary(value)


def summary_payload_field(kind: PayloadKind, value: object) -> dict[str, object]:
    """Builds an input/output summary payload field."""
    return {f"{kind}_summary": payload_summary(value)}


def project_contract_payload(
    *,
    contract_label: str,
    payload: Mapping[str, object],
    payload_kind: PayloadKind,
    project: Callable[[Mapping[str, object]], dict[str, object]],
    logger: logging.Logger,
    fallback_to_summary: bool,
    compact_projected: bool = False,
) -> dict[str, object]:
    """Projects a contract payload and applies fallback/compaction policy."""
    try:
        projected = project(payload)
    except Exception as exc:
        if not fallback_to_summary:
            raise
        logger.warning(
            "Could not project %s payload for contract %s; "
            "using compact summary after %s: %s",
            payload_kind,
            contract_label,
            type(exc).__name__,
            exc,
        )
        return summary_payload_field(payload_kind, payload)

    if compact_projected:
        compacted = message_compact_summary(projected)
        if isinstance(compacted, Mapping):
            return dict(compacted)
    return projected


def _mode_value(mode: object) -> object:
    return getattr(mode, "value", mode)


__all__ = [
    "PayloadKind",
    "payload_summary",
    "prepare_trace_payload",
    "project_contract_payload",
    "serialize_trace_payload",
    "summary_payload_field",
]
