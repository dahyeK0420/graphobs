"""Shared compact shape summaries for payload-safe observability."""

from __future__ import annotations

from collections.abc import Mapping, Sequence


def shape_summary(value: object) -> dict[str, object]:
    """Returns JSON-compatible metadata that describes a value's shape.

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
