"""Draft contract model produced by discovery sample runs."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from graphobs.contracts.models import AttributeValue, NodeContract
from graphobs.state.observed_access import ObservedStatePaths
from graphobs.state.paths import normalize_paths


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
        object.__setattr__(
            self,
            "reads",
            ObservedStatePaths(self.reads).most_specific(),
        )
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
        read_partition = ObservedStatePaths(self.reads).partition_private(private_reads)
        write_partition = ObservedStatePaths(self.writes).partition_private(
            private_writes
        )
        return NodeContract(
            name=self.name if name is None else name,
            reads=read_partition.public,
            writes=write_partition.public,
            private_reads=read_partition.private,
            private_writes=write_partition.private,
            span_kind=span_kind,
            attributes=attributes,
        )


__all__ = ["DiscoveredContract"]
