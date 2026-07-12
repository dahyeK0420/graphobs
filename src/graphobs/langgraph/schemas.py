"""LangGraph input schema helpers for contract adapters."""

from __future__ import annotations

import logging
import typing
from typing import Protocol, cast

from graphobs.contracts.models import Contract, ProjectionPolicy
from graphobs.state.paths import split_path

LOGGER = logging.getLogger("graphobs.langgraph")


class TypedDictFactory(Protocol):
    """Runtime callable shape for the functional ``TypedDict`` factory."""

    def __call__(
        self,
        typename: str,
        fields: dict[str, type[object]],
        *,
        total: bool,
    ) -> type[object]:
        """Creates a ``TypedDict`` class."""


def langgraph_input_schema(contract: Contract) -> type[object] | None:
    """Builds a best-effort LangGraph input schema from explicit contract keys.

    Args:
        contract: Contract that declares public and execution input policies.

    Returns:
        A dynamic ``TypedDict`` schema, or ``None`` when the contract cannot be
        safely narrowed.
    """
    try:
        fields = _top_level_fields(contract.execution_input_policies)
        typed_dict = cast(TypedDictFactory, typing.TypedDict)
        return typed_dict(f"{_schema_name(contract.label)}Input", fields, total=False)
    except ValueError as exc:
        LOGGER.warning(
            "Could not build LangGraph input schema for %s: %s",
            contract.label,
            exc,
        )
        return None


def _top_level_fields(
    policies: tuple[ProjectionPolicy, ...],
) -> dict[str, type[object]]:
    fields: dict[str, type[object]] = {}
    for policy in policies:
        if policy.include is None:
            raise ValueError("open-ended projection cannot be represented")
        for path_text in policy.include:
            key = split_path(path_text)[0]
            fields[key] = object
    return fields


def _schema_name(name: str) -> str:
    return "".join(part.capitalize() for part in name.replace("-", "_").split("_"))


__all__ = ["TypedDictFactory", "langgraph_input_schema"]
