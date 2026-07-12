"""Shared interpretation of observed dotted state path access."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from graphobs.state.paths import (
    Path,
    is_prefix,
    normalize_paths,
    split_path,
)


class PathPolicy(Protocol):
    """Minimal include/exclude policy shape for state read and write checks."""

    @property
    def include(self) -> tuple[str, ...] | None:
        """Dotted paths included by the policy, or all paths when omitted."""

    @property
    def exclude(self) -> tuple[str, ...]:
        """Dotted paths excluded by the policy."""


@dataclass(frozen=True)
class PrivatePathPartition:
    """Public and private path groups after applying private overrides."""

    public: tuple[str, ...]
    private: tuple[str, ...]


@dataclass(frozen=True, init=False)
class ObservedStatePaths:
    """Normalized observed dotted state paths and their shared classifications."""

    paths: tuple[str, ...]

    def __init__(self, paths: Iterable[str]) -> None:
        """Normalizes observed paths while preserving first-seen order."""
        object.__setattr__(self, "paths", normalize_paths(paths))

    def most_specific(self) -> tuple[str, ...]:
        """Returns the most specific observed paths in deterministic order."""
        parsed = _parsed_paths(self.paths)
        specific = {
            path_text
            for path_text, path in parsed
            if not any(
                path != other_path and is_prefix(path, other_path)
                for _, other_path in parsed
            )
        }
        result: list[str] = []
        emitted: set[str] = set()

        for path_text, path in parsed:
            if path_text in emitted:
                continue

            descendants = tuple(
                other_text
                for other_text, other_path in parsed
                if other_text in specific
                and path != other_path
                and is_prefix(path, other_path)
            )
            if descendants:
                for descendant in descendants:
                    if descendant not in emitted:
                        result.append(descendant)
                        emitted.add(descendant)
            elif path_text in specific:
                result.append(path_text)
                emitted.add(path_text)

        return tuple(result)

    def partition_private(
        self,
        private_overrides: Iterable[str],
    ) -> PrivatePathPartition:
        """Splits observed paths into public paths and broad private paths."""
        override_paths = normalize_paths(private_overrides)
        parsed_overrides = tuple(split_path(path_text) for path_text in override_paths)

        if not parsed_overrides:
            return PrivatePathPartition(public=self.paths, private=())

        public_paths: list[str] = []
        private_paths: list[str] = []
        for path_text in self.paths:
            path = split_path(path_text)
            if any(
                paths_overlap(path, private_path) for private_path in parsed_overrides
            ):
                private_paths.append(path_text)
            else:
                public_paths.append(path_text)

        return PrivatePathPartition(
            public=tuple(public_paths),
            private=_broad_paths((*private_paths, *override_paths)),
        )

    def undeclared_for(
        self,
        policies: Iterable[PathPolicy],
    ) -> tuple[str, ...]:
        """Returns observed paths not allowed by any read policy."""
        policy_tuple = tuple(policies)
        return tuple(
            path_text
            for path_text in self.paths
            if not any(
                policy_allows_observed_read_path(split_path(path_text), policy)
                for policy in policy_tuple
            )
        )


def policy_allows_observed_read_path(
    path: Path,
    policy: PathPolicy,
) -> bool:
    """Returns whether a policy allows an observed state read path.

    A read is allowed when a declared include path overlaps the observed path in
    either direction, and no exclude path overlaps it.
    """
    include_paths = _include_paths(policy)
    included = include_paths is None or any(
        paths_overlap(allowed_path, path) for allowed_path in include_paths
    )
    return included and not _excluded(path, policy)


def policy_allows_write_path(path: Path, policy: PathPolicy) -> bool:
    """Returns whether a policy allows writing a concrete update path.

    A write is allowed when a declared include path is an ancestor of (or equal
    to) the update path, and no exclude path overlaps it. This is stricter than
    the read check: a write must fall under a declared path, not merely overlap
    one.
    """
    include_paths = _include_paths(policy)
    included = include_paths is None or any(
        is_prefix(allowed_path, path) for allowed_path in include_paths
    )
    return included and not _excluded(path, policy)


def paths_overlap(left: Path, right: Path) -> bool:
    """Returns whether either path is an ancestor of the other."""
    return is_prefix(left, right) or is_prefix(right, left)


def _include_paths(policy: PathPolicy) -> tuple[Path, ...] | None:
    if policy.include is None:
        return None
    return tuple(split_path(path_text) for path_text in policy.include)


def _excluded(path: Path, policy: PathPolicy) -> bool:
    exclude_paths = tuple(split_path(path_text) for path_text in policy.exclude)
    return any(paths_overlap(excluded_path, path) for excluded_path in exclude_paths)


def _broad_paths(paths: Iterable[str]) -> tuple[str, ...]:
    parsed = _parsed_paths(normalize_paths(paths))
    return tuple(
        path_text
        for path_text, path in parsed
        if not any(
            path != other_path and is_prefix(other_path, path)
            for _, other_path in parsed
        )
    )


def _parsed_paths(paths: Iterable[str]) -> tuple[tuple[str, Path], ...]:
    return tuple((path_text, split_path(path_text)) for path_text in paths)


__all__ = [
    "ObservedStatePaths",
    "PathPolicy",
    "PrivatePathPartition",
    "paths_overlap",
    "policy_allows_observed_read_path",
    "policy_allows_write_path",
]
