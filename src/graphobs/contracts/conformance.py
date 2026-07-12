"""Shared contract conformance checks for reads, writes, and violations.

One place owns the two questions every enforcement path asks — "which observed
paths are undeclared?" and "how is a violation reported?" — so runtime write
validation, runtime read enforcement, and sample-based drift checks stay
consistent instead of re-deriving the same rules.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from graphobs.contracts.models import (
    Contract,
    ContractViolationAction,
    StateAccess,
    StateContractError,
)
from graphobs.state.observed_access import (
    ObservedStatePaths,
    policy_allows_write_path,
)
from graphobs.state.paths import Path, join_path


def undeclared_read_paths(
    contract: Contract,
    observed_paths: Iterable[str],
) -> tuple[str, ...]:
    """Returns observed read paths outside a contract's declared read policies.

    Args:
        contract: Contract that declares allowed public and private reads.
        observed_paths: Dotted paths observed as reads during execution or a
            sample run.

    Returns:
        The observed paths not allowed by any read policy, in first-seen order.
    """
    return ObservedStatePaths(observed_paths).undeclared_for(
        contract.execution_input_policies
    )


def undeclared_write_paths(
    contract: Contract,
    paths: Iterable[Path],
) -> tuple[str, ...]:
    """Returns the write paths not allowed by any of a contract's write policies.

    Args:
        contract: Contract that declares allowed public and private writes.
        paths: Leaf update paths, for example from ``iter_update_paths`` or a
            discovered contract's write paths.

    Returns:
        The dotted paths not allowed by any write policy, in the given order.
    """
    return tuple(
        join_path(path)
        for path in paths
        if not any(
            policy_allows_write_path(path, policy) for policy in contract.write_policies
        )
    )


def report_violation(
    contract_label: str,
    undeclared: tuple[str, ...],
    *,
    access: StateAccess,
    on_violation: ContractViolationAction,
    logger: logging.Logger,
) -> None:
    """Raises or warns for undeclared paths under one violation policy.

    Shared by runtime read enforcement and write validation so both sides report
    a ``StateContractError`` the same way. Callers pass their own module logger
    so the log channel stays with the reporting layer. Does nothing when no
    paths are undeclared.

    Args:
        contract_label: Human-readable contract label used in the error.
        undeclared: Dotted paths that the contract did not declare.
        access: Whether the undeclared paths were read or written.
        on_violation: Whether undeclared paths raise or log a warning.
        logger: Logger that records the violation.

    Raises:
        StateContractError: If ``undeclared`` is non-empty and ``on_violation``
            is ``ContractViolationAction.RAISE``.
    """
    if not undeclared:
        return
    error = StateContractError(contract_label, undeclared, access=access)
    if on_violation == ContractViolationAction.WARN:
        logger.warning("%s", error)
        return
    logger.error("%s", error)
    raise error


__all__ = [
    "report_violation",
    "undeclared_read_paths",
    "undeclared_write_paths",
]
