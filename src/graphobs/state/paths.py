"""Shared dotted state path operations for contract projections."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, MutableMapping
from typing import TypeAlias, cast

LOGGER = logging.getLogger(__name__)

Path: TypeAlias = tuple[str, ...]
StateMapping: TypeAlias = Mapping[str, object]
StateUpdate: TypeAlias = Mapping[str, object]


def normalize_optional_paths(paths: Iterable[str] | None) -> tuple[str, ...] | None:
    """Normalizes optional dotted paths while preserving omitted includes."""
    if paths is None:
        return None
    return normalize_paths(paths)


def normalize_paths(paths: Iterable[str]) -> tuple[str, ...]:
    """Normalizes dotted paths and removes duplicates in first-seen order."""
    return tuple(dict.fromkeys(join_path(split_path(path)) for path in paths))


def split_path(path: str) -> Path:
    """Splits a dotted state path into non-blank parts.

    Raises:
        ValueError: If the path or any path part is blank.
    """
    parts = tuple(part.strip() for part in path.split("."))
    if not parts or any(part == "" for part in parts):
        error = ValueError(f"state path must not be blank: {path!r}")
        LOGGER.error("Failed to split state path: %s", error)
        raise error
    return parts


def join_path(path: Path) -> str:
    """Joins normalized path parts into dotted state path notation."""
    return ".".join(path)


def get_path(state: Mapping[str, object], path: Path) -> tuple[bool, object]:
    """Returns whether a path exists and the value found at that path."""
    current: object = state
    for part in path:
        if not isinstance(current, Mapping) or part not in current:
            return False, None
        current = current[part]
    return True, current


def set_path(target: MutableMapping[str, object], path: Path, value: object) -> None:
    """Sets a nested value at a normalized path, creating mappings as needed."""
    current = target
    for part in path[:-1]:
        existing = current.get(part)
        if not isinstance(existing, MutableMapping):
            existing = {}
            current[part] = existing
        current = cast(MutableMapping[str, object], existing)
    current[path[-1]] = value


class _Missing:
    pass


_MISSING = _Missing()


def state_diff(
    before_state: StateMapping,
    after_state: StateMapping,
) -> dict[str, object]:
    """Returns changed paths present in ``after_state``."""
    diff: dict[str, object] = {}
    for key, after_value in after_state.items():
        before_value = before_state.get(key, _MISSING)
        child_diff = _diff_value(before_value, after_value)
        if child_diff is not _MISSING:
            diff[key] = child_diff
    return diff


def _diff_value(before: object, after: object) -> object:
    if before == after:
        return _MISSING
    if isinstance(before, Mapping) and isinstance(after, Mapping):
        diff: dict[str, object] = {}
        for key, after_value in after.items():
            before_value = before.get(key, _MISSING)
            child_diff = _diff_value(before_value, after_value)
            if child_diff is not _MISSING:
                diff[str(key)] = child_diff
        return diff if diff else _MISSING
    return after


def iter_update_paths(update: StateUpdate, prefix: Path = ()) -> Iterable[Path]:
    """Yields leaf paths represented by a nested state update."""
    for key, value in update.items():
        path = (*prefix, key)
        if isinstance(value, Mapping) and value:
            yield from iter_update_paths(value, path)
        else:
            yield path


def is_prefix(prefix: Path, path: Path) -> bool:
    """Returns whether ``prefix`` is an ancestor or exact match for ``path``."""
    return len(prefix) <= len(path) and path[: len(prefix)] == prefix


__all__ = [
    "Path",
    "StateMapping",
    "StateUpdate",
    "get_path",
    "is_prefix",
    "iter_update_paths",
    "join_path",
    "normalize_optional_paths",
    "normalize_paths",
    "set_path",
    "split_path",
    "state_diff",
]
