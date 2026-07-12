"""Contract update validation."""

from __future__ import annotations

import logging

from graphobs.contracts.conformance import (
    report_violation,
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


__all__ = ["validate_update"]
