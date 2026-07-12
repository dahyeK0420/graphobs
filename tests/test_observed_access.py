from __future__ import annotations

from graphobs.state.observed_access import (
    ObservedStatePaths,
    paths_overlap,
    policy_allows_observed_read_path,
    policy_allows_write_path,
)


class _Policy:
    def __init__(self, include: tuple[str, ...] | None) -> None:
        self.include = include


def test_observed_paths_classify_undeclared_reads_in_observed_order() -> None:
    observed = ObservedStatePaths(
        (
            "context",
            "request.text",
            "context.extra",
            "debug",
        )
    )

    assert observed.undeclared_for(
        (
            _Policy(("request.text",)),
            _Policy(("context.retrieved",)),
        )
    ) == ("context.extra", "debug")


def test_observed_read_policy_allows_overlapping_paths() -> None:
    policy = _Policy(include=("request.text",))

    assert policy_allows_observed_read_path(("request",), policy)
    assert policy_allows_observed_read_path(("request", "text", "normalized"), policy)
    assert not policy_allows_observed_read_path(("context",), policy)


def test_policy_allows_write_paths_only_under_declared_paths() -> None:
    policy = _Policy(include=("answer",))

    assert policy_allows_write_path(("answer", "text"), policy)
    assert policy_allows_write_path(("answer",), policy)
    assert not policy_allows_write_path(("metrics",), policy)


def test_paths_overlap_matches_ancestors_and_descendants() -> None:
    assert paths_overlap(("request",), ("request", "text"))
    assert paths_overlap(("request", "text"), ("request",))
    assert paths_overlap(("request", "text"), ("request", "text"))
    assert not paths_overlap(("request", "text"), ("request", "raw"))
