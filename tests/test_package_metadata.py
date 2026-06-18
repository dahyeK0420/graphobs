from __future__ import annotations

from importlib.metadata import metadata, version
from importlib.resources import files


def test_distribution_metadata() -> None:
    package_metadata = metadata("graph-observability-kit")

    assert version("graph-observability-kit") == "0.2.0"
    assert package_metadata["Name"] == "graph-observability-kit"
    assert package_metadata["License-Expression"] == "Apache-2.0"


def test_package_ships_type_marker() -> None:
    assert files("graph_observability_kit").joinpath("py.typed").is_file()
