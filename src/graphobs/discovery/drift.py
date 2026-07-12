"""Contract drift checks comparing a declared contract against sample runs."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping

from graphobs.contracts.conformance import (
    undeclared_read_paths,
    undeclared_write_paths,
)
from graphobs.contracts.models import ContractViolationAction, NodeContract
from graphobs.discovery.draft import DiscoveredContract
from graphobs.discovery.runner import (
    AsyncDiscoveryNode,
    SyncDiscoveryNode,
    adiscover_contract,
    discover_contract,
)
from graphobs.state.paths import StateMapping, split_path

LOGGER = logging.getLogger("graphobs.discovery")


class ContractDriftError(AssertionError):
    """Raised when sample runs read or write paths a contract does not declare.

    The error records only dotted state paths, never sampled state values, so
    drift diagnostics stay safe to log. It subclasses ``AssertionError`` so a
    drift check reads as a failed assertion in tests and CI.

    Attributes:
        node_name: Human-readable node name that was checked.
        undeclared_reads: Observed read paths outside the contract's read
            policies.
        undeclared_writes: Observed write paths outside the contract's write
            policies.
    """

    node_name: str
    undeclared_reads: tuple[str, ...]
    undeclared_writes: tuple[str, ...]

    def __init__(
        self,
        node_name: str,
        undeclared_reads: Iterable[str],
        undeclared_writes: Iterable[str],
    ) -> None:
        """Creates a drift error from the undeclared paths observed in samples.

        Args:
            node_name: Human-readable node name that was checked.
            undeclared_reads: Observed read paths the contract did not declare.
            undeclared_writes: Observed write paths the contract did not declare.
        """
        self.node_name = node_name
        self.undeclared_reads = tuple(undeclared_reads)
        self.undeclared_writes = tuple(undeclared_writes)
        details = _drift_details(self.undeclared_reads, self.undeclared_writes)
        message = (
            f"Contract {node_name!r} drifted from sample runs: undeclared "
            f"{'; '.join(details)}"
        )
        super().__init__(message)


def assert_contract_matches(
    node: SyncDiscoveryNode,
    contract: NodeContract,
    samples: Iterable[StateMapping],
    *,
    node_kwargs: Mapping[str, object] | None = None,
    on_drift: ContractViolationAction = ContractViolationAction.WARN,
) -> DiscoveredContract:
    """Checks whether a node's sample reads or writes stay within its contract.

    Runs the raw node against synthetic samples, then compares the observed
    reads and writes with the contract's read and write policies. Drift is
    advisory by default: it is logged as a warning and the discovered draft is
    still returned. Pass ``on_drift=ContractViolationAction.RAISE`` (for example
    in a CI test) to turn drift into a raised ``ContractDriftError`` instead.

    Args:
        node: Synchronous node callable that accepts a state mapping.
        contract: Declared node contract the samples are compared against.
        samples: Synthetic sample states to execute sequentially.
        node_kwargs: Optional keyword arguments forwarded to every sample run.
        on_drift: Whether undeclared sample reads or writes log a warning
            (default) or raise ``ContractDriftError``.

    Returns:
        The draft contract discovered from the samples, for inspection.

    Raises:
        ContractDriftError: If any sample read or write is undeclared and
            ``on_drift`` is ``ContractViolationAction.RAISE``.
        ContractDiscoveryError: If any sample execution fails.
    """
    discovered = discover_contract(
        node,
        samples,
        name=contract.name,
        node_kwargs=node_kwargs,
    )
    _report_drift(contract, discovered, on_drift=on_drift)
    return discovered


async def assert_contract_amatches(
    node: AsyncDiscoveryNode,
    contract: NodeContract,
    samples: Iterable[StateMapping],
    *,
    node_kwargs: Mapping[str, object] | None = None,
    on_drift: ContractViolationAction = ContractViolationAction.WARN,
) -> DiscoveredContract:
    """Checks whether an async node's sample reads or writes stay within contract.

    Asynchronous counterpart to ``assert_contract_matches``. Drift is advisory
    by default (logged as a warning); pass
    ``on_drift=ContractViolationAction.RAISE`` to raise ``ContractDriftError``.

    Args:
        node: Asynchronous node callable that accepts a state mapping.
        contract: Declared node contract the samples are compared against.
        samples: Synthetic sample states to execute sequentially.
        node_kwargs: Optional keyword arguments forwarded to every sample run.
        on_drift: Whether undeclared sample reads or writes log a warning
            (default) or raise ``ContractDriftError``.

    Returns:
        The draft contract discovered from the samples, for inspection.

    Raises:
        ContractDriftError: If any sample read or write is undeclared and
            ``on_drift`` is ``ContractViolationAction.RAISE``.
        ContractDiscoveryError: If any sample execution fails.
    """
    discovered = await adiscover_contract(
        node,
        samples,
        name=contract.name,
        node_kwargs=node_kwargs,
    )
    _report_drift(contract, discovered, on_drift=on_drift)
    return discovered


def _report_drift(
    contract: NodeContract,
    discovered: DiscoveredContract,
    *,
    on_drift: ContractViolationAction,
) -> None:
    undeclared_reads = undeclared_read_paths(contract, discovered.reads)
    undeclared_writes = undeclared_write_paths(
        contract,
        (split_path(write) for write in discovered.writes),
    )
    if not undeclared_reads and not undeclared_writes:
        return
    error = ContractDriftError(contract.name, undeclared_reads, undeclared_writes)
    if on_drift == ContractViolationAction.WARN:
        LOGGER.warning("%s", error)
        return
    LOGGER.error("%s", error)
    raise error


def _drift_details(
    undeclared_reads: tuple[str, ...],
    undeclared_writes: tuple[str, ...],
) -> list[str]:
    details: list[str] = []
    if undeclared_reads:
        details.append(f"reads {', '.join(undeclared_reads)}")
    if undeclared_writes:
        details.append(f"writes {', '.join(undeclared_writes)}")
    return details


__all__ = [
    "ContractDriftError",
    "assert_contract_amatches",
    "assert_contract_matches",
]
