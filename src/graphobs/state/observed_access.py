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
    """Minimal include policy shape for state read and write checks."""

    @property
    def include(self) -> tuple[str, ...] | None:
        """Dotted paths included by the policy, or all paths when omitted."""


@dataclass(frozen=True, init=False)
class ObservedStatePaths:
    """Normalized observed dotted state paths and their shared classifications."""

    paths: tuple[str, ...]

    def __init__(self, paths: Iterable[str]) -> None:
        """Normalizes observed paths while preserving first-seen order."""
        object.__setattr__(self, "paths", normalize_paths(paths))

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
    either direction.
    """
    include_paths = _include_paths(policy)
    return include_paths is None or any(
        paths_overlap(allowed_path, path) for allowed_path in include_paths
    )


def policy_allows_write_path(path: Path, policy: PathPolicy) -> bool:
    """Returns whether a policy allows writing a concrete update path.

    A write is allowed when a declared include path is an ancestor of (or equal
    to) the update path. This is stricter than the read check: a write must fall
    under a declared path, not merely overlap one.
    """
    include_paths = _include_paths(policy)
    return include_paths is None or any(
        is_prefix(allowed_path, path) for allowed_path in include_paths
    )


def paths_overlap(left: Path, right: Path) -> bool:
    """Returns whether either path is an ancestor of the other."""
    return is_prefix(left, right) or is_prefix(right, left)


def _include_paths(policy: PathPolicy) -> tuple[Path, ...] | None:
    if policy.include is None:
        return None
    return tuple(split_path(path_text) for path_text in policy.include)


__all__ = [
    "ObservedStatePaths",
    "PathPolicy",
    "paths_overlap",
    "policy_allows_observed_read_path",
    "policy_allows_write_path",
]
