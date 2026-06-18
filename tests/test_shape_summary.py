from __future__ import annotations

import pytest

from graph_observability_kit.payloads import message_compact_summary, shape_summary


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (
            {"beta": 1, "alpha": 2, 3: "number key"},
            {"type": "mapping", "size": 3, "keys": ["3", "alpha", "beta"]},
        ),
        ("hello", {"type": "str", "length": 5}),
        (b"hello", {"type": "bytes", "length": 5}),
        (bytearray(b"hello"), {"type": "bytes", "length": 5}),
        ([1, 2, 3], {"type": "sequence", "size": 3}),
        ((1, 2), {"type": "sequence", "size": 2}),
        (None, {"type": "none"}),
        (True, {"type": "bool"}),
        (3, {"type": "int"}),
        (1.5, {"type": "float"}),
    ],
)
def test_shape_summary_returns_canonical_metadata(
    value: object,
    expected: dict[str, object],
) -> None:
    assert shape_summary(value) == expected


def test_shape_summary_reports_unknown_objects_by_type_name() -> None:
    class SyntheticPayload:
        pass

    assert shape_summary(SyntheticPayload()) == {"type": "SyntheticPayload"}


# --- message_compact_summary ---


class _FakeMessage:
    def __init__(self, msg_type: str, content: str) -> None:
        self.type = msg_type
        self.content = content


@pytest.mark.parametrize(
    ("msg_type", "expected_role"),
    [
        ("human", "user"),
        ("ai", "assistant"),
        ("system", "system"),
        ("tool", "tool"),
        ("unknown_type", "unknown_type"),
    ],
)
def test_message_compact_summary_maps_basemessage_roles(
    msg_type: str,
    expected_role: str,
) -> None:
    msg = _FakeMessage(msg_type, "hello")
    result = message_compact_summary(msg)
    assert result == {"role": expected_role, "content": "hello"}


def test_message_compact_summary_truncates_long_content() -> None:
    long_content = "x" * 5000
    msg = _FakeMessage("human", long_content)
    result = message_compact_summary(msg)
    assert isinstance(result, dict)
    content = result["content"]
    assert isinstance(content, str)
    assert content.endswith("…(+1000 chars)")
    assert len(content) < len(long_content)


def test_message_compact_summary_handles_role_content_dict() -> None:
    msg = {"role": "user", "content": "hello", "additional_kwargs": {"junk": True}}
    result = message_compact_summary(msg)
    assert result == {"role": "user", "content": "hello"}


def test_message_compact_summary_handles_type_content_dict() -> None:
    msg = {"type": "ai", "content": "response", "usage_metadata": {"tokens": 100}}
    result = message_compact_summary(msg)
    assert result == {"role": "assistant", "content": "response"}


def test_message_compact_summary_recurses_list_of_messages() -> None:
    messages = [
        _FakeMessage("human", "hi"),
        _FakeMessage("ai", "hello"),
    ]
    result = message_compact_summary(messages)
    assert result == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]


def test_message_compact_summary_handles_list_of_lists() -> None:
    messages = [
        [_FakeMessage("human", "hi")],
        [_FakeMessage("ai", "hello")],
    ]
    result = message_compact_summary(messages)
    assert result == [
        [{"role": "user", "content": "hi"}],
        [{"role": "assistant", "content": "hello"}],
    ]


def test_message_compact_summary_summarizes_non_message_scalars() -> None:
    result = message_compact_summary({"knowledge": [1, 2, 3], "count": 42})
    assert isinstance(result, dict)
    # Lists are recursed; each non-message integer becomes a shape summary.
    assert result["knowledge"] == [{"type": "int"}, {"type": "int"}, {"type": "int"}]
    # Non-message scalars at leaf level become shape summaries.
    assert result["count"] == {"type": "int"}


def test_message_compact_summary_respects_custom_content_limit() -> None:
    msg = _FakeMessage("human", "x" * 100)
    result = message_compact_summary(msg, content_limit=50)
    assert isinstance(result, dict)
    content = result["content"]
    assert isinstance(content, str)
    assert content.endswith("…(+50 chars)")


def test_message_compact_summary_compacts_declared_messages_in_mapping() -> None:
    state = {
        "messages": [_FakeMessage("human", "hi"), _FakeMessage("ai", "hello")],
        "count": 2,
    }
    result = message_compact_summary(state)
    assert isinstance(result, dict)
    messages = result["messages"]
    assert messages == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    count = result["count"]
    assert isinstance(count, dict)
    assert count["type"] == "int"
