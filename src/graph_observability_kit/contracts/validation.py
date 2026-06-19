"""Contract update validation."""

from __future__ import annotations

import logging

from graph_observability_kit.contracts.models import (
    Contract,
    ContractViolationAction,
    StateContractError,
)
from graph_observability_kit.state.paths import (
    StateUpdate,
    iter_update_paths,
    join_path,
)
from graph_observability_kit.state.policies import policy_allows_write_path

LOGGER = logging.getLogger("graph_observability_kit.contracts")


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
    undeclared = [
        join_path(path)
        for path in iter_update_paths(update)
        if not any(
            policy_allows_write_path(path, policy) for policy in contract.write_policies
        )
    ]
    if undeclared:
        error = StateContractError(contract.label, undeclared)
        if on_violation == ContractViolationAction.WARN:
            LOGGER.warning("%s", error)
            return
        LOGGER.error("%s", error)
        raise error


__all__ = ["validate_update"]
