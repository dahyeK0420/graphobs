"""Compact payload summaries and the shared trace payload policy.

Structural summary helpers (``shape_summary``, ``message_compact_summary``) are
the public surface. The trace payload mode dispatch, JSON serialization, and
contract projection fallback policy live here too so compact-by-default
behavior is defined exactly once and reused by contracts, tracing, and logging.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping, Sequence
from typing import Literal

_DEFAULT_CONTENT_LIMIT = 4000

_ROLE_MAP: dict[str, str] = {
    "human": "user",
    "ai": "assistant",
    "system": "system",
    "tool": "tool",
}

_BULKY_MESSAGE_KEYS: frozenset[str] = frozenset(
    {
        "additional_kwargs",
        "response_metadata",
        "usage_metadata",
        "tool_calls",
        "tool_call_chunks",
    }
)

PayloadKind = Literal["input", "output"]


def shape_summary(value: object) -> dict[str, object]:
    """Returns JSON-compatible metadata that describes a value's shape.

    The summary is intended for compact observability payloads. It reports
    structural metadata such as mapping keys, collection sizes, and scalar
    lengths without storing arbitrary nested values.

    Args:
        value: Value to summarize without storing arbitrary contents.

    Returns:
        A compact summary containing type, size, keys, or length metadata.
    """
    if isinstance(value, Mapping):
        return {
            "type": "mapping",
            "size": len(value),
            "keys": sorted(str(key) for key in value),
        }
    if isinstance(value, str):
        return {"type": "str", "length": len(value)}
    if isinstance(value, bytes | bytearray):
        return {"type": "bytes", "length": len(value)}
    if isinstance(value, Sequence) and not isinstance(
        value,
        str | bytes | bytearray,
    ):
        return {"type": "sequence", "size": len(value)}
    if value is None:
        return {"type": "none"}
    return {"type": type(value).__name__}


def message_compact_summary(
    value: object,
    *,
    content_limit: int = _DEFAULT_CONTENT_LIMIT,
) -> object:
    """Recursively compacts message-shaped values, summarizing everything else.

    Message-shaped values (LangChain ``BaseMessage`` duck-typed objects or
    ``{role/type, content}`` dicts) are reduced to ``{"role": …, "content":
    truncate(…)}``, dropping bulky metadata fields. Non-message values fall
    back to ``shape_summary``. Sequences and mappings are recursed so nested
    ``messages`` lists are handled automatically.

    Detection is purely structural — no hard ``langchain`` import — so the
    function works with any message-compatible object.

    Args:
        value: Value to compact.
        content_limit: Maximum character length for message content. Content
            exceeding this limit is truncated with a suffix indicating how
            many characters were dropped.

    Returns:
        A compacted representation: ``{"role": …, "content": …}`` for
        messages, a recursed structure for sequences/mappings containing
        messages, or a ``shape_summary`` dict for everything else.
    """
    if _is_message(value):
        return _compact_message(value, content_limit=content_limit)
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [
            message_compact_summary(item, content_limit=content_limit) for item in value
        ]
    if isinstance(value, Mapping):
        return {
            k: message_compact_summary(v, content_limit=content_limit)
            for k, v in value.items()
        }
    return shape_summary(value)


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


def summary_payload_field(kind: PayloadKind, value: object) -> dict[str, object]:
    """Builds an input/output summary payload field."""
    return {f"{kind}_summary": shape_summary(value)}


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


def _is_message(value: object) -> bool:
    if isinstance(value, Mapping):
        return "content" in value and ("role" in value or "type" in value)
    return hasattr(value, "type") and hasattr(value, "content")


def _compact_message(value: object, *, content_limit: int) -> dict[str, object]:
    if isinstance(value, Mapping):
        type_str = str(value.get("type", ""))
        raw_role = value.get("role") or _ROLE_MAP.get(type_str, type_str)
        content = value.get("content", "")
    else:
        raw_type = getattr(value, "type", "")
        raw_role = _ROLE_MAP.get(str(raw_type), str(raw_type))
        content = getattr(value, "content", "")
    return {
        "role": str(raw_role),
        "content": _truncate(content, content_limit),
    }


def _truncate(content: object, limit: int) -> object:
    if isinstance(content, str) and len(content) > limit:
        overflow = len(content) - limit
        return f"{content[:limit]}…(+{overflow} chars)"
    return content


def _mode_value(mode: object) -> object:
    return getattr(mode, "value", mode)


__all__ = ["message_compact_summary", "shape_summary"]
