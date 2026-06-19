from __future__ import annotations

import logging

import pytest

from graphobs.state.paths import (
    delete_path,
    get_path,
    is_prefix,
    iter_update_paths,
    join_path,
    normalize_optional_paths,
    normalize_paths,
    set_path,
    split_path,
    state_diff,
)
from graphobs.state.policies import (
    policy_allows_read_path,
    policy_allows_write_path,
)


class _Policy:
    def __init__(
        self,
        include: tuple[str, ...] | None,
        exclude: tuple[str, ...] = (),
    ) -> None:
        self.include = include
        self.exclude = exclude


def test_normalize_paths_trims_parts_and_removes_duplicates() -> None:
    assert normalize_paths((" request.text ", "request.text", "answer.text")) == (
        "request.text",
        "answer.text",
    )


def test_normalize_optional_paths_preserves_open_projection() -> None:
    assert normalize_optional_paths(None) is None


def test_split_path_rejects_blank_parts_with_error_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.ERROR, logger="graphobs.state.paths")

    with pytest.raises(
        ValueError,
        match=r"state path must not be blank: 'request\.\.text'",
    ):
        split_path("request..text")

    assert caplog.records[0].levelno == logging.ERROR
    assert caplog.messages == [
        "Failed to split state path: state path must not be blank: 'request..text'"
    ]


def test_join_path_returns_dotted_path() -> None:
    assert join_path(("request", "text")) == "request.text"


def test_get_path_reports_missing_without_mutating_state() -> None:
    state = {"request": {"text": "hello"}}

    assert get_path(state, ("request", "text")) == (True, "hello")
    assert get_path(state, ("request", "raw")) == (False, None)
    assert state == {"request": {"text": "hello"}}


def test_set_path_creates_nested_mappings() -> None:
    target: dict[str, object] = {}

    set_path(target, ("answer", "text"), "done")

    assert target == {"answer": {"text": "done"}}


def test_delete_path_prunes_empty_parent_mappings() -> None:
    target: dict[str, object] = {
        "answer": {"text": "done"},
        "request": {"text": "hello"},
    }

    assert delete_path(target, ("answer", "text")) is True
    assert delete_path(target, ("missing",)) is False
    assert target == {"request": {"text": "hello"}}


def test_state_diff_reports_changed_after_state_paths_only() -> None:
    assert state_diff(
        {"answer": {"text": "old", "score": 1}, "removed": "before"},
        {"answer": {"text": "new", "score": 1}, "added": "after"},
    ) == {"answer": {"text": "new"}, "added": "after"}


def test_iter_update_paths_returns_leaf_paths() -> None:
    assert tuple(
        iter_update_paths(
            {
                "answer": {"text": "done"},
                "empty_mapping": {},
                "temporary": None,
            }
        )
    ) == (("answer", "text"), ("empty_mapping",), ("temporary",))


def test_is_prefix_matches_ancestors_and_exact_paths() -> None:
    assert is_prefix(("answer",), ("answer", "text"))
    assert is_prefix(("answer", "text"), ("answer", "text"))
    assert not is_prefix(("answer", "text"), ("answer",))


def test_policy_allows_write_paths_only_under_declared_paths() -> None:
    policy = _Policy(include=("answer",))

    assert policy_allows_write_path(("answer", "text"), policy)
    assert policy_allows_write_path(("answer",), policy)
    assert not policy_allows_write_path(("metrics",), policy)


def test_policy_allows_read_paths_that_overlap_declared_paths() -> None:
    policy = _Policy(include=("request.text",))

    assert policy_allows_read_path(("request",), policy)
    assert policy_allows_read_path(("request", "text"), policy)
    assert policy_allows_read_path(("request", "text", "normalized"), policy)
    assert not policy_allows_read_path(("context",), policy)


def test_policy_excludes_overlapping_paths() -> None:
    policy = _Policy(include=None, exclude=("request.raw",))

    assert policy_allows_write_path(("request", "text"), policy)
    assert not policy_allows_write_path(("request",), policy)
    assert not policy_allows_write_path(("request", "raw"), policy)
    assert not policy_allows_read_path(("request", "raw"), policy)
    assert not policy_allows_read_path(("request", "raw", "value"), policy)
    assert not policy_allows_read_path(("request",), policy)
