"""Sample execution runner for experimental contract discovery."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Iterable, Mapping
from typing import TypeAlias

from graphobs.discovery.draft import DiscoveredContract
from graphobs.state.paths import (
    StateMapping,
    StateUpdate,
    iter_update_paths,
    join_path,
)
from graphobs.state.read_tracking import (
    ReadTracker,
    ReadTrackingMapping,
)

LOGGER = logging.getLogger("graphobs.discovery")

SyncDiscoveryNode: TypeAlias = Callable[..., StateUpdate]
AsyncDiscoveryNode: TypeAlias = Callable[..., Awaitable[StateUpdate]]


class ContractDiscoveryError(RuntimeError):
    """Raised when contract discovery fails for a synthetic sample.

    Attributes:
        node_name: Human-readable node name being discovered.
        sample_index: Zero-based sample index that failed, when known.
    """

    node_name: str
    sample_index: int | None

    def __init__(
        self,
        node_name: str,
        sample_index: int | None,
        original_exception: BaseException,
    ) -> None:
        """Creates a discovery error that preserves the original exception.

        Args:
            node_name: Human-readable node name being discovered.
            sample_index: Zero-based sample index that failed, when known.
            original_exception: Exception raised by the node or discovery.
        """
        self.node_name = node_name
        self.sample_index = sample_index
        location = (
            "unknown sample" if sample_index is None else f"sample {sample_index}"
        )
        message = (
            f"Contract discovery for node {node_name!r} failed on {location}: "
            f"{type(original_exception).__name__}: {original_exception}"
        )
        super().__init__(message)


def discover_contract(
    node: SyncDiscoveryNode,
    samples: Iterable[StateMapping],
    *,
    name: str | None = None,
    node_kwargs: Mapping[str, object] | None = None,
) -> DiscoveredContract:
    """Discovers a draft node contract from synchronous sample executions.

    Args:
        node: Synchronous node callable that accepts a state mapping.
        samples: Synthetic sample states to execute sequentially.
        name: Optional node name for the draft contract.
        node_kwargs: Optional keyword arguments forwarded to every sample run.

    Returns:
        A draft discovered contract.

    Raises:
        ContractDiscoveryError: If any sample execution or returned update
            inspection fails.
    """
    node_name = _resolve_node_name(node, name)
    kwargs = dict(node_kwargs or {})
    tracker = ReadTracker()
    writes: list[str] = []
    sample_count = 0

    for sample_index, sample in enumerate(samples):
        sample_count += 1
        tracked_state = ReadTrackingMapping(sample, tracker)
        try:
            update = node(tracked_state, **kwargs)
            writes.extend(_update_paths(update))
        except Exception as exc:
            _raise_discovery_error(node_name, sample_index, exc)

    return DiscoveredContract(
        name=node_name,
        reads=tracker.paths(),
        writes=tuple(writes),
        sample_count=sample_count,
    )


async def adiscover_contract(
    node: AsyncDiscoveryNode,
    samples: Iterable[StateMapping],
    *,
    name: str | None = None,
    node_kwargs: Mapping[str, object] | None = None,
) -> DiscoveredContract:
    """Discovers a draft node contract from asynchronous sample executions.

    Args:
        node: Asynchronous node callable that accepts a state mapping.
        samples: Synthetic sample states to execute sequentially.
        name: Optional node name for the draft contract.
        node_kwargs: Optional keyword arguments forwarded to every sample run.

    Returns:
        A draft discovered contract.

    Raises:
        ContractDiscoveryError: If any sample execution or returned update
            inspection fails.
    """
    node_name = _resolve_node_name(node, name)
    kwargs = dict(node_kwargs or {})
    tracker = ReadTracker()
    writes: list[str] = []
    sample_count = 0

    for sample_index, sample in enumerate(samples):
        sample_count += 1
        tracked_state = ReadTrackingMapping(sample, tracker)
        try:
            update = await node(tracked_state, **kwargs)
            writes.extend(_update_paths(update))
        except Exception as exc:
            _raise_discovery_error(node_name, sample_index, exc)

    return DiscoveredContract(
        name=node_name,
        reads=tracker.paths(),
        writes=tuple(writes),
        sample_count=sample_count,
    )


def _update_paths(update: StateUpdate) -> tuple[str, ...]:
    if not isinstance(update, Mapping):
        raise TypeError(
            f"node returned unsupported update type: {type(update).__name__}"
        )
    return tuple(join_path(path) for path in iter_update_paths(update))


def _raise_discovery_error(
    node_name: str,
    sample_index: int,
    exc: Exception,
) -> None:
    LOGGER.exception(
        "Contract discovery for node %s failed on sample %s: %s",
        node_name,
        sample_index,
        exc,
    )
    raise ContractDiscoveryError(node_name, sample_index, exc) from exc


def _resolve_node_name(node: Callable[..., object], name: str | None) -> str:
    candidate = name
    if candidate is None:
        maybe_name = getattr(node, "__name__", None)
        candidate = str(maybe_name) if maybe_name is not None else type(node).__name__
    if not candidate.strip():
        raise ValueError("name must not be blank")
    return candidate


__all__ = [
    "AsyncDiscoveryNode",
    "ContractDiscoveryError",
    "SyncDiscoveryNode",
    "adiscover_contract",
    "discover_contract",
]
