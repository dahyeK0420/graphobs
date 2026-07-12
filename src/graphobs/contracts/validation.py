"""Runtime validation that a node's reads and writes match its contract."""

from __future__ import annotations

import logging

from graphobs.contracts.conformance import (
    report_violation,
    undeclared_read_paths,
    undeclared_write_paths,
)
from graphobs.contracts.models import (
    Contract,
    ContractViolationAction,
)
from graphobs.state.paths import (
    StateUpdate,
    iter_update_paths,
)
from graphobs.state.read_tracking import ReadTracker

LOGGER = logging.getLogger("graphobs.contracts")


def validate_update(
    contract: Contract,
    update: StateUpdate,
    *,
    on_violation: ContractViolationAction = ContractViolationAction.RAISE,
) -> None:
    """Validates that an update only writes declared paths.

    Args:
        contract: Contract that declares allowed public and private writes.
        update: State update returned by a node or subgraph.
        on_violation: Whether undeclared writes raise or log a warning.

    Raises:
        StateContractError: If any update path is not declared by the contract
            and ``on_violation`` is ``ContractViolationAction.RAISE``.
    """
    report_violation(
        contract.label,
        undeclared_write_paths(contract, iter_update_paths(update)),
        access="write",
        on_violation=on_violation,
        logger=LOGGER,
    )


def enforce_undeclared_reads(
    contract: Contract,
    tracker: ReadTracker | None,
    *,
    on_violation: ContractViolationAction = ContractViolationAction.RAISE,
) -> None:
    """Validates that observed reads only touch declared paths.

    The read-side counterpart to ``validate_update``: both compose the shared
    ``report_violation`` so reads and writes share one violation policy and one
    log channel. A ``None`` tracker means read auditing is off and the check is
    skipped.

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


__all__ = ["enforce_undeclared_reads", "validate_update"]
