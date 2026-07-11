"""Runtime read enforcement for contract-wrapped LangGraph nodes."""

from __future__ import annotations

import logging

from graphobs.contracts.models import (
    Contract,
    ContractViolationAction,
    StateContractError,
)
from graphobs.state.observed_access import ObservedStatePaths
from graphobs.state.read_tracking import ReadTracker

LOGGER = logging.getLogger("graphobs.langgraph")


def enforce_undeclared_reads(
    contract: Contract,
    tracker: ReadTracker | None,
    *,
    on_violation: ContractViolationAction = ContractViolationAction.RAISE,
) -> None:
    """Raises or warns when observed reads fall outside a contract.

    Mirrors ``validate_update`` on the write side so reads and writes share one
    violation policy.

    Args:
        contract: Contract that declares allowed public and private reads.
        tracker: Recorder of observed reads, or ``None`` when auditing is off.
        on_violation: Whether undeclared reads raise or log a warning.

    Raises:
        StateContractError: If any observed read path is not declared by the
            contract and ``on_violation`` is ``ContractViolationAction.RAISE``.
    """
    if tracker is None:
        return

    undeclared = undeclared_read_paths(contract, tracker.paths())
    if not undeclared:
        return

    error = StateContractError(contract.label, undeclared, access="read")
    if on_violation == ContractViolationAction.WARN:
        LOGGER.warning("%s", error)
        return
    LOGGER.error("%s", error)
    raise error


def undeclared_read_paths(
    contract: Contract,
    observed_paths: tuple[str, ...],
) -> tuple[str, ...]:
    """Returns observed paths outside a contract's declared read policies."""
    return ObservedStatePaths(observed_paths).undeclared_for(
        contract.execution_input_policies
    )


__all__ = ["enforce_undeclared_reads", "undeclared_read_paths"]
