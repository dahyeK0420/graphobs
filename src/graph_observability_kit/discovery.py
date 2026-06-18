"""Experimental contract discovery from synthetic sample states."""

from __future__ import annotations

import logging
from collections.abc import (
    Awaitable,
    Callable,
    Iterable,
    Mapping,
)
from dataclasses import dataclass
from typing import TypeAlias

from graph_observability_kit._read_tracking import ReadTracker, ReadTrackingMapping
from graph_observability_kit._state_paths import (
    Path,
    StateMapping,
    StateUpdate,
    is_prefix,
    iter_update_paths,
    join_path,
    normalize_paths,
    split_path,
)
from graph_observability_kit.contracts import AttributeValue, NodeContract

LOGGER = logging.getLogger(__name__)

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


@dataclass(frozen=True)
class DiscoveredContract:
    """Draft node contract discovered from synthetic sample executions.

    Discovery is best-effort and sample-dependent. Treat the result as a draft
    contract for review, not as proof of a complete runtime boundary.

    Attributes:
        name: Node name used when generating a concrete contract.
        reads: Dotted state paths observed while executing samples.
        writes: Dotted update paths returned by sample executions.
        sample_count: Number of synthetic samples executed.
    """

    name: str
    reads: tuple[str, ...]
    writes: tuple[str, ...]
    sample_count: int

    def __post_init__(self) -> None:
        """Normalizes paths for deterministic draft output."""
        if not self.name.strip():
            raise ValueError("name must not be blank")
        if self.sample_count < 0:
            raise ValueError("sample_count must not be negative")
        object.__setattr__(self, "name", self.name)
        object.__setattr__(self, "reads", _specific_paths(self.reads))
        object.__setattr__(self, "writes", normalize_paths(self.writes))

    def to_node_contract(
        self,
        *,
        name: str | None = None,
        private_reads: Iterable[str] = (),
        private_writes: Iterable[str] = (),
        span_kind: str | None = None,
        attributes: Mapping[str, AttributeValue] | None = None,
    ) -> NodeContract:
        """Builds a concrete ``NodeContract`` from the discovered draft.

        All discovered reads and writes are public by default. Private path
        overrides remove matching or overlapping discovered paths from the
        public side and pass them to the private side of the generated
        ``NodeContract``.

        Args:
            name: Optional replacement name for the generated contract.
            private_reads: Paths that should be private reads.
            private_writes: Paths that should be private writes.
            span_kind: Optional observability span kind label.
            attributes: Static metadata attributes for later observability use.

        Returns:
            A node contract whose paths can be reviewed and adjusted manually.
        """
        public_reads, contract_private_reads = _split_private_paths(
            self.reads,
            private_reads,
        )
        public_writes, contract_private_writes = _split_private_paths(
            self.writes,
            private_writes,
        )
        return NodeContract(
            name=self.name if name is None else name,
            reads=public_reads,
            writes=public_writes,
            private_reads=contract_private_reads,
            private_writes=contract_private_writes,
            span_kind=span_kind,
            attributes=attributes,
        )


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


def _specific_paths(paths: Iterable[str]) -> tuple[str, ...]:
    normalized = normalize_paths(paths)
    parsed = tuple((path_text, split_path(path_text)) for path_text in normalized)
    specific = {
        path_text
        for path_text, path in parsed
        if not any(
            path != other_path and is_prefix(path, other_path)
            for _, other_path in parsed
        )
    }
    result: list[str] = []
    emitted: set[str] = set()

    for path_text, path in parsed:
        if path_text in emitted:
            continue

        descendants = tuple(
            other_text
            for other_text, other_path in parsed
            if other_text in specific
            and path != other_path
            and is_prefix(path, other_path)
        )
        if descendants:
            for descendant in descendants:
                if descendant not in emitted:
                    result.append(descendant)
                    emitted.add(descendant)
        elif path_text in specific:
            result.append(path_text)
            emitted.add(path_text)

    return tuple(result)


def _split_private_paths(
    discovered: Iterable[str],
    private_overrides: Iterable[str],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    discovered_paths = normalize_paths(discovered)
    override_paths = normalize_paths(private_overrides)
    parsed_overrides = tuple(split_path(path_text) for path_text in override_paths)

    if not parsed_overrides:
        return discovered_paths, ()

    public_paths: list[str] = []
    private_paths: list[str] = []
    for discovered_path_text in discovered_paths:
        discovered_path = split_path(discovered_path_text)
        if any(
            _paths_overlap(discovered_path, private_path)
            for private_path in parsed_overrides
        ):
            private_paths.append(discovered_path_text)
        else:
            public_paths.append(discovered_path_text)

    return tuple(public_paths), _broad_paths((*private_paths, *override_paths))


def _paths_overlap(left: Path, right: Path) -> bool:
    return is_prefix(left, right) or is_prefix(right, left)


def _broad_paths(paths: Iterable[str]) -> tuple[str, ...]:
    normalized = normalize_paths(paths)
    parsed = tuple((path_text, split_path(path_text)) for path_text in normalized)
    return tuple(
        path_text
        for path_text, path in parsed
        if not any(
            path != other_path and is_prefix(other_path, path)
            for _, other_path in parsed
        )
    )


__all__ = [
    "ContractDiscoveryError",
    "DiscoveredContract",
    "adiscover_contract",
    "discover_contract",
]
