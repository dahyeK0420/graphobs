from __future__ import annotations

import pytest

from graph_observability_kit._shape_summary import shape_summary


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
