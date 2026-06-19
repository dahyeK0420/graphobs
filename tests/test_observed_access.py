from __future__ import annotations

from graph_observability_kit.state.observed_access import (
    ObservedStatePaths,
    paths_overlap,
    policy_allows_observed_read_path,
)


class _Policy:
    def __init__(
        self,
        include: tuple[str, ...] | None,
        exclude: tuple[str, ...] = (),
    ) -> None:
        self.include = include
        self.exclude = exclude


def test_observed_paths_select_most_specific_reads_in_order() -> None:
    observed = ObservedStatePaths(
        (
            "request",
            "request.text",
            "context",
            "context.locale",
            "request.raw",
        )
    )

    assert observed.most_specific() == (
        "request.text",
        "request.raw",
        "context.locale",
    )


def test_observed_paths_partition_private_overlapping_paths() -> None:
    observed = ObservedStatePaths(
        (
            "request.text",
            "scratch.notes",
            "scratch.step",
            "scratch.step.detail",
        )
    )

    partition = observed.partition_private(("scratch",))

    assert partition.public == ("request.text",)
    assert partition.private == ("scratch",)


def test_observed_paths_partition_private_specific_override() -> None:
    observed = ObservedStatePaths(("request.text", "scratch.notes"))

    partition = observed.partition_private(("scratch.notes.detail",))

    assert partition.public == ("request.text",)
    assert partition.private == ("scratch.notes",)


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


def test_observed_read_policy_allows_overlapping_paths_and_excludes_overlap() -> None:
    policy = _Policy(include=("request.text",))
    excluding_policy = _Policy(include=("request.text",), exclude=("request.raw",))

    assert policy_allows_observed_read_path(("request",), policy)
    assert policy_allows_observed_read_path(("request", "text", "normalized"), policy)
    assert not policy_allows_observed_read_path(("request",), excluding_policy)
    assert not policy_allows_observed_read_path(("request", "raw"), excluding_policy)
    assert not policy_allows_observed_read_path(
        ("request", "raw", "value"),
        excluding_policy,
    )


def test_paths_overlap_matches_ancestors_and_descendants() -> None:
    assert paths_overlap(("request",), ("request", "text"))
    assert paths_overlap(("request", "text"), ("request",))
    assert paths_overlap(("request", "text"), ("request", "text"))
    assert not paths_overlap(("request", "text"), ("request", "raw"))
