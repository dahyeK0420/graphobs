"""Public compact payload summary helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

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


__all__ = ["message_compact_summary", "shape_summary"]
