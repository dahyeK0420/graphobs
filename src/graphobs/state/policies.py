"""Shared dotted-path policy matching helpers."""

from __future__ import annotations

from typing import Protocol

from graphobs.state.observed_access import (
    paths_overlap,
    policy_allows_observed_read_path,
)
from graphobs.state.paths import Path, is_prefix, split_path


class PathPolicy(Protocol):
    """Minimal include/exclude policy shape for state path checks."""

    @property
    def include(self) -> tuple[str, ...] | None:
        """Dotted paths included by the policy, or all paths when omitted."""

    @property
    def exclude(self) -> tuple[str, ...]:
        """Dotted paths excluded by the policy."""


def policy_allows_write_path(path: Path, policy: PathPolicy) -> bool:
    """Returns whether a policy allows writing a concrete update path."""
    include_paths = _include_paths(policy)
    included = include_paths is None or any(
        is_prefix(allowed_path, path) for allowed_path in include_paths
    )
    return included and not _excluded(path, policy)


def policy_allows_read_path(path: Path, policy: PathPolicy) -> bool:
    """Returns whether a policy allows reading an observed state path."""
    return policy_allows_observed_read_path(path, policy)


def _include_paths(policy: PathPolicy) -> tuple[Path, ...] | None:
    if policy.include is None:
        return None
    return tuple(split_path(path_text) for path_text in policy.include)


def _excluded(path: Path, policy: PathPolicy) -> bool:
    exclude_paths = tuple(split_path(path_text) for path_text in policy.exclude)
    return any(paths_overlap(excluded_path, path) for excluded_path in exclude_paths)


__all__ = ["PathPolicy", "policy_allows_read_path", "policy_allows_write_path"]
