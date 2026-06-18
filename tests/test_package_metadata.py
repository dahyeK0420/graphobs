from __future__ import annotations

from importlib.metadata import metadata, version


def test_distribution_metadata() -> None:
    package_metadata = metadata("graph-observability-kit")

    assert version("graph-observability-kit") == "0.1.0"
    assert package_metadata["Name"] == "graph-observability-kit"
    assert package_metadata["License-Expression"] == "Apache-2.0"
