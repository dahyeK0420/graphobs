"""Runtime read-audit helpers for contract-wrapped LangGraph nodes."""

from __future__ import annotations

import logging

from graph_observability_kit.contracts.models import Contract
from graph_observability_kit.state.observed_access import ObservedStatePaths
from graph_observability_kit.state.read_tracking import ReadTracker

LOGGER = logging.getLogger("graph_observability_kit.langgraph")


def warn_undeclared_reads(
    contract: Contract,
    tracker: ReadTracker | None,
) -> None:
    """Logs observed state reads not declared by the contract."""
    if tracker is None:
        return

    undeclared_paths = undeclared_read_paths(contract, tracker.paths())
    if not undeclared_paths:
        return

    LOGGER.warning(
        "Contract %r read undeclared state paths: %s",
        contract.label,
        ", ".join(undeclared_paths),
    )


def undeclared_read_paths(
    contract: Contract,
    observed_paths: tuple[str, ...],
) -> tuple[str, ...]:
    """Returns observed paths outside a contract's declared read policies."""
    return ObservedStatePaths(observed_paths).undeclared_for(
        contract.execution_input_policies
    )


__all__ = ["undeclared_read_paths", "warn_undeclared_reads"]
