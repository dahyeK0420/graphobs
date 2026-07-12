"""Shared contract conformance checks for reads, writes, and violations.

One place owns what every enforcement path asks — "which observed paths are
undeclared?" and "how is a violation reported?" — plus the two runtime entry
points built on them: ``validate_update`` (writes) and
``enforce_undeclared_reads`` (reads). Both report through ``report_violation``
so reads and writes share one violation policy.
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
from graphobs.state.paths import (
    Path,
    StateUpdate,
    iter_update_paths,
    join_path,
)
from graphobs.state.read_tracking import ReadTracker

# Reads surface through the LangGraph node wrapper; writes are a contract-level
# check. Both channels are preserved so existing log consumers keep working.
_READ_LOGGER = logging.getLogger("graphobs.langgraph")
_WRITE_LOGGER = logging.getLogger("graphobs.contracts")


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
        paths: Leaf update paths, for example from ``iter_update_paths``.

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
        logger=_WRITE_LOGGER,
    )


def enforce_undeclared_reads(
    contract: Contract,
    tracker: ReadTracker | None,
    *,
    on_violation: ContractViolationAction = ContractViolationAction.RAISE,
) -> None:
    """Raises or warns when observed reads fall outside a contract.

    Mirrors ``validate_update`` on the read side; both delegate to
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
        logger=_READ_LOGGER,
    )


__all__ = [
    "enforce_undeclared_reads",
    "report_violation",
    "undeclared_read_paths",
    "undeclared_write_paths",
    "validate_update",
]
