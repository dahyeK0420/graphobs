"""Contract drift checks comparing a declared contract against sample runs."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping

from graphobs.contracts.conformance import (
    undeclared_read_paths,
    undeclared_write_paths,
)
from graphobs.contracts.models import NodeContract
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
) -> DiscoveredContract:
    """Fails if a node's sample reads or writes fall outside its contract.

    Runs the raw node against synthetic samples, then compares the observed
    reads and writes with the contract's read and write policies. Intended as a
    test or CI guard that turns silent contract drift into a failed assertion.

    Args:
        node: Synchronous node callable that accepts a state mapping.
        contract: Declared node contract the samples must stay within.
        samples: Synthetic sample states to execute sequentially.
        node_kwargs: Optional keyword arguments forwarded to every sample run.

    Returns:
        The draft contract discovered from the samples, for inspection.

    Raises:
        ContractDriftError: If any sample read or write is undeclared.
        ContractDiscoveryError: If any sample execution fails.
    """
    discovered = discover_contract(
        node,
        samples,
        name=contract.name,
        node_kwargs=node_kwargs,
    )
    _raise_on_drift(contract, discovered)
    return discovered


async def assert_contract_amatches(
    node: AsyncDiscoveryNode,
    contract: NodeContract,
    samples: Iterable[StateMapping],
    *,
    node_kwargs: Mapping[str, object] | None = None,
) -> DiscoveredContract:
    """Fails if an async node's sample reads or writes fall outside its contract.

    Asynchronous counterpart to ``assert_contract_matches``.

    Args:
        node: Asynchronous node callable that accepts a state mapping.
        contract: Declared node contract the samples must stay within.
        samples: Synthetic sample states to execute sequentially.
        node_kwargs: Optional keyword arguments forwarded to every sample run.

    Returns:
        The draft contract discovered from the samples, for inspection.

    Raises:
        ContractDriftError: If any sample read or write is undeclared.
        ContractDiscoveryError: If any sample execution fails.
    """
    discovered = await adiscover_contract(
        node,
        samples,
        name=contract.name,
        node_kwargs=node_kwargs,
    )
    _raise_on_drift(contract, discovered)
    return discovered


def _raise_on_drift(
    contract: NodeContract,
    discovered: DiscoveredContract,
) -> None:
    undeclared_reads = undeclared_read_paths(contract, discovered.reads)
    undeclared_writes = undeclared_write_paths(
        contract,
        (split_path(write) for write in discovered.writes),
    )
    if not undeclared_reads and not undeclared_writes:
        return
    error = ContractDriftError(contract.name, undeclared_reads, undeclared_writes)
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
