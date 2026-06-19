"""Shared mapping read tracking for discovery and runtime audits."""

from __future__ import annotations

from collections.abc import ItemsView, Iterator, KeysView, Mapping, ValuesView
from typing import cast

from graphobs.state.paths import Path, join_path


class ReadTracker:
    """Records dotted paths read through a ``ReadTrackingMapping``."""

    def __init__(self) -> None:
        self._paths: dict[str, None] = {}

    def record(self, path: Path) -> None:
        """Records one non-empty state path."""
        if path:
            self._paths[join_path(path)] = None

    def record_children(self, prefix: Path, source: Mapping[str, object]) -> None:
        """Records all immediate children under ``prefix``."""
        for key in source:
            self.record((*prefix, str(key)))

    def paths(self) -> tuple[str, ...]:
        """Returns observed paths in first-seen order."""
        return tuple(self._paths)


class ReadTrackingMapping(Mapping[str, object]):
    """Mapping wrapper that records key and nested mapping reads."""

    def __init__(
        self,
        source: Mapping[str, object],
        tracker: ReadTracker,
        prefix: Path = (),
    ) -> None:
        self._source = source
        self._tracker = tracker
        self._prefix = prefix

    def __getitem__(self, key: str) -> object:
        path = (*self._prefix, str(key))
        self._tracker.record(path)
        return self._wrap_value(path, self._source[key])

    def __iter__(self) -> Iterator[str]:
        self._tracker.record_children(self._prefix, self._source)
        return iter(self._source)

    def __len__(self) -> int:
        self._tracker.record_children(self._prefix, self._source)
        return len(self._source)

    def __contains__(self, key: object) -> bool:
        path = (*self._prefix, str(key))
        self._tracker.record(path)
        return key in self._source

    def get(self, key: str, default: object = None) -> object:
        """Returns a value while recording the attempted read."""
        path = (*self._prefix, str(key))
        self._tracker.record(path)
        if key not in self._source:
            return default
        return self._wrap_value(path, self._source[key])

    def keys(self) -> KeysView[str]:
        self._tracker.record_children(self._prefix, self._source)
        return super().keys()

    def items(self) -> ItemsView[str, object]:
        self._tracker.record_children(self._prefix, self._source)
        return super().items()

    def values(self) -> ValuesView[object]:
        self._tracker.record_children(self._prefix, self._source)
        return super().values()

    def _wrap_value(self, path: Path, value: object) -> object:
        if isinstance(value, Mapping):
            return ReadTrackingMapping(
                cast(Mapping[str, object], value),
                self._tracker,
                path,
            )
        return value


__all__ = ["ReadTracker", "ReadTrackingMapping"]
