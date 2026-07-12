from __future__ import annotations

from importlib.metadata import metadata, version
from importlib.resources import files


def test_distribution_metadata() -> None:
    package_metadata = metadata("graphobs")

    assert version("graphobs") == "0.3.1"
    assert package_metadata["Name"] == "graphobs"
    assert package_metadata["License-Expression"] == "Apache-2.0"


def test_package_ships_type_marker() -> None:
    assert files("graphobs").joinpath("py.typed").is_file()
