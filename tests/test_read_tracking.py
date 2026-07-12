from __future__ import annotations

import pytest

from graphobs.state.read_tracking import ReadTracker, ReadTrackingMapping


def test_getitem_records_path_and_wraps_nested_mappings() -> None:
    tracker = ReadTracker()
    wrapped = ReadTrackingMapping({"request": {"text": "hello"}}, tracker)

    nested = wrapped["request"]

    assert isinstance(nested, ReadTrackingMapping)
    assert nested["text"] == "hello"
    assert tracker.paths() == ("request", "request.text")


def test_get_records_attempted_read_and_returns_default_when_missing() -> None:
    tracker = ReadTracker()
    wrapped = ReadTrackingMapping({"present": 1}, tracker)

    assert wrapped.get("present") == 1
    assert wrapped.get("absent", "fallback") == "fallback"
    assert tracker.paths() == ("present", "absent")


def test_contains_records_the_probed_key() -> None:
    tracker = ReadTracker()
    wrapped = ReadTrackingMapping({"a": 1}, tracker)

    assert "a" in wrapped
    assert "b" not in wrapped
    assert tracker.paths() == ("a", "b")


def test_iteration_records_all_immediate_children() -> None:
    tracker = ReadTracker()
    wrapped = ReadTrackingMapping({"x": 1, "y": 2}, tracker)

    list(iter(wrapped))

    assert set(tracker.paths()) == {"x", "y"}


def test_len_records_all_immediate_children() -> None:
    tracker = ReadTracker()
    wrapped = ReadTrackingMapping({"x": 1, "y": 2}, tracker)

    assert len(wrapped) == 2
    assert set(tracker.paths()) == {"x", "y"}


def test_keys_records_all_children() -> None:
    tracker = ReadTracker()
    list(ReadTrackingMapping({"x": 1, "y": 2}, tracker).keys())
    assert set(tracker.paths()) == {"x", "y"}


def test_items_records_all_children() -> None:
    tracker = ReadTracker()
    list(ReadTrackingMapping({"x": 1, "y": 2}, tracker).items())
    assert set(tracker.paths()) == {"x", "y"}


def test_values_records_all_children() -> None:
    tracker = ReadTracker()
    list(ReadTrackingMapping({"x": 1, "y": 2}, tracker).values())
    assert set(tracker.paths()) == {"x", "y"}


def test_equality_is_inspection_and_records_nothing() -> None:
    tracker = ReadTracker()
    source = {"request": {"text": "hello"}}
    wrapped = ReadTrackingMapping(source, tracker)

    assert wrapped == source
    assert wrapped == ReadTrackingMapping(source, ReadTracker())
    assert wrapped != {"other": 1}
    assert tracker.paths() == ()


def test_read_tracking_mapping_is_unhashable_like_a_mapping() -> None:
    wrapped = ReadTrackingMapping({"a": 1}, ReadTracker())

    with pytest.raises(TypeError):
        hash(wrapped)


def test_tracker_records_first_seen_order_and_ignores_empty_paths() -> None:
    tracker = ReadTracker()

    tracker.record(("b",))
    tracker.record(("a",))
    tracker.record(("b",))
    tracker.record(())

    assert tracker.paths() == ("b", "a")


def test_record_children_records_each_child_under_prefix() -> None:
    tracker = ReadTracker()

    tracker.record_children(("request",), {"text": "hello", "raw": "hidden"})

    assert set(tracker.paths()) == {"request.text", "request.raw"}
