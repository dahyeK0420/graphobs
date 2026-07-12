"""Runtime read enforcement for contract-wrapped LangGraph nodes."""

from __future__ import annotations

import logging

from graphobs.contracts.conformance import (
    report_violation,
    undeclared_read_paths,
)
from graphobs.contracts.models import (
    Contract,
    ContractViolationAction,
)
from graphobs.state.read_tracking import ReadTracker

LOGGER = logging.getLogger("graphobs.langgraph")


def enforce_undeclared_reads(
    contract: Contract,
    tracker: ReadTracker | None,
    *,
    on_violation: ContractViolationAction = ContractViolationAction.RAISE,
) -> None:
    """Raises or warns when observed reads fall outside a contract.

    Mirrors ``validate_update`` on the write side; both delegate to the shared
    ``report_violation`` so reads and writes share one violation policy.

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

    report_violation(
        contract.label,
        undeclared_read_paths(contract, tracker.paths()),
        access="read",
        on_violation=on_violation,
        logger=LOGGER,
    )


__all__ = ["enforce_undeclared_reads"]
