"""State contract models and projection helpers."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol, TypeAlias

from graph_observability_kit._shape_summary import shape_summary
from graph_observability_kit._state_paths import (
    Path,
    StateMapping,
    StateUpdate,
    delete_path,
    get_path,
    is_prefix,
    iter_update_paths,
    join_path,
    normalize_optional_paths,
    normalize_paths,
    set_path,
    split_path,
    state_diff,
)

LOGGER = logging.getLogger(__name__)

AttributeValue = str | int | float | bool | None


class StateContractError(ValueError):
    """Raised when an update writes keys that a contract did not declare."""

    contract_name: str
    undeclared_paths: tuple[str, ...]

    def __init__(self, contract_name: str, undeclared_paths: Iterable[str]) -> None:
        """Creates an error without storing state values.

        Args:
            contract_name: Human-readable contract label.
            undeclared_paths: Dotted state paths that were not declared.
        """
        self.contract_name = contract_name
        self.undeclared_paths = tuple(sorted(undeclared_paths))
        joined_paths = ", ".join(self.undeclared_paths)
        message = (
            f"Contract {contract_name!r} wrote undeclared state paths: {joined_paths}"
        )
        super().__init__(message)


@dataclass(frozen=True, init=False)
class ProjectionPolicy:
    """Selects, removes, and summarizes nested state paths.

    Paths use dotted notation, such as ``"request.text"``. An omitted
    ``include`` value means all top-level state is initially selected. An empty
    include collection selects nothing.

    Attributes:
        include: Dotted paths to include, or ``None`` to include all state.
        exclude: Dotted paths to remove after inclusion.
        summarize: Dotted paths to replace with compact metadata.
    """

    include: tuple[str, ...] | None
    exclude: tuple[str, ...]
    summarize: tuple[str, ...]

    def __init__(
        self,
        include: Iterable[str] | None = None,
        *,
        exclude: Iterable[str] = (),
        summarize: Iterable[str] = (),
    ) -> None:
        """Creates a projection policy.

        Args:
            include: Dotted paths to include, or ``None`` to include all state.
            exclude: Dotted paths to remove from the projected state.
            summarize: Dotted paths to replace with compact summary metadata.
        """
        object.__setattr__(self, "include", _normalize_optional_paths(include))
        object.__setattr__(self, "exclude", _normalize_paths(exclude))
        object.__setattr__(self, "summarize", _normalize_paths(summarize))

    def project(self, state: StateMapping) -> dict[str, object]:
        """Projects state according to this policy.

        Args:
            state: Mapping of graph state keys to values.

        Returns:
            A new dictionary containing only the selected public state.
        """
        return _project_state(self, state)


ProjectionSpec: TypeAlias = ProjectionPolicy | Iterable[str]


class Contract(Protocol):
    """Common state boundary interface for contract helpers.

    Concrete contracts may use domain-specific constructor fields, but shared
    projection, validation, and integration helpers depend on this interface.
    """

    @property
    def label(self) -> str:
        """Human-readable contract label used in messages and schema names."""

    @property
    def input_policy(self) -> ProjectionPolicy:
        """Public state projection policy for contract input."""

    @property
    def output_policy(self) -> ProjectionPolicy:
        """Public state projection policy for contract output."""

    @property
    def execution_input_policies(self) -> tuple[ProjectionPolicy, ...]:
        """State projection policies used to build execution input schemas."""

    @property
    def write_policies(self) -> tuple[ProjectionPolicy, ...]:
        """Public and private write policies allowed by the contract."""


@dataclass(frozen=True, init=False)
class NodeContract:
    """Declares the public and private state boundary for one node.

    Private keys are part of the contract for validation, but they are not
    returned by the public projection helpers. They are not a security boundary.
    """

    label: str
    input_policy: ProjectionPolicy
    output_policy: ProjectionPolicy
    execution_input_policies: tuple[ProjectionPolicy, ...]
    write_policies: tuple[ProjectionPolicy, ...]
    span_kind: str | None
    attributes: Mapping[str, AttributeValue]

    def __init__(
        self,
        *,
        name: str,
        reads: ProjectionSpec = (),
        writes: ProjectionSpec = (),
        private_reads: ProjectionSpec = (),
        private_writes: ProjectionSpec = (),
        span_kind: str | None = None,
        attributes: Mapping[str, AttributeValue] | None = None,
    ) -> None:
        """Creates a node contract.

        Args:
            name: Public node name used in validation messages and later spans.
            reads: Public state paths the node may read.
            writes: Public state paths the node may write.
            private_reads: Private state paths the node may read locally.
            private_writes: Private state paths the node may write locally.
            span_kind: Optional observability span kind label.
            attributes: Static metadata attributes for later observability use.
        """
        input_policy = _coerce_projection(reads)
        output_policy = _coerce_projection(writes)
        private_input_policy = _coerce_projection(private_reads)
        private_output_policy = _coerce_projection(private_writes)

        object.__setattr__(self, "label", _validate_name(name, "name"))
        object.__setattr__(self, "input_policy", input_policy)
        object.__setattr__(self, "output_policy", output_policy)
        object.__setattr__(
            self,
            "execution_input_policies",
            (input_policy, private_input_policy),
        )
        object.__setattr__(
            self,
            "write_policies",
            (output_policy, private_output_policy),
        )
        object.__setattr__(self, "span_kind", span_kind)
        object.__setattr__(
            self,
            "attributes",
            MappingProxyType(dict(attributes or {})),
        )

    @property
    def name(self) -> str:
        """Node name used when registering the contract with LangGraph."""
        return self.label


@dataclass(frozen=True, init=False)
class SubgraphContract:
    """Declares the public parent boundary for a nested graph.

    Private state keys may be passed through or cleaned up by integration
    layers, but they are excluded from public input and output projections.
    """

    label: str
    input_policy: ProjectionPolicy
    output_policy: ProjectionPolicy
    execution_input_policies: tuple[ProjectionPolicy, ...]
    write_policies: tuple[ProjectionPolicy, ...]

    def __init__(
        self,
        *,
        parent_input: ProjectionSpec = (),
        parent_output: ProjectionSpec = (),
        private_state_keys: Iterable[str] = (),
        owner_namespace: str,
        cleanup_writes: ProjectionSpec = (),
    ) -> None:
        """Creates a subgraph contract.

        Args:
            parent_input: Public parent state paths passed into the subgraph.
            parent_output: Public parent state paths returned from the subgraph.
            private_state_keys: Private state paths owned by the subgraph.
            owner_namespace: Generic owner label used in validation messages.
            cleanup_writes: State paths the subgraph may write during cleanup.
        """
        input_policy = _coerce_projection(parent_input)
        output_policy = _coerce_projection(parent_output)
        private_policy = ProjectionPolicy(include=private_state_keys)
        cleanup_policy = _coerce_projection(cleanup_writes)

        object.__setattr__(
            self,
            "label",
            _validate_name(owner_namespace, "owner_namespace"),
        )
        object.__setattr__(self, "input_policy", input_policy)
        object.__setattr__(self, "output_policy", output_policy)
        object.__setattr__(
            self,
            "execution_input_policies",
            (input_policy, private_policy),
        )
        object.__setattr__(
            self,
            "write_policies",
            (output_policy, private_policy, cleanup_policy),
        )


def project_input(
    contract: Contract,
    state: StateMapping,
) -> dict[str, object]:
    """Projects public input state for a node or subgraph contract.

    Args:
        contract: Contract that declares the public input boundary.
        state: Full graph state.

    Returns:
        A new dictionary containing only public input state.
    """
    return contract.input_policy.project(state)


def project_output(
    contract: Contract,
    before_state: StateMapping,
    after_state: StateMapping,
) -> dict[str, object]:
    """Projects changed public output state for a node or subgraph contract.

    Args:
        contract: Contract that declares the public output boundary.
        before_state: State before execution.
        after_state: State after execution.

    Returns:
        A new dictionary containing changed public output paths only.
    """
    policy = contract.output_policy
    before_projection = policy.project(before_state)
    after_projection = policy.project(after_state)
    return state_diff(before_projection, after_projection)


def validate_update(
    contract: Contract,
    update: StateUpdate,
) -> None:
    """Validates that an update only writes declared paths.

    Args:
        contract: Contract that declares allowed public and private writes.
        update: State update returned by a node or subgraph.

    Raises:
        StateContractError: If any update path is not declared by the contract.
    """
    undeclared = [
        join_path(path)
        for path in iter_update_paths(update)
        if not any(
            _path_allowed_by_policy(path, policy) for policy in contract.write_policies
        )
    ]
    if undeclared:
        error = StateContractError(contract.label, undeclared)
        LOGGER.error("%s", error)
        raise error


def _coerce_projection(spec: ProjectionSpec) -> ProjectionPolicy:
    if isinstance(spec, ProjectionPolicy):
        return spec
    return ProjectionPolicy(include=spec)


def _project_state(policy: ProjectionPolicy, state: StateMapping) -> dict[str, object]:
    if policy.include is None:
        projected: dict[str, object] = dict(state)
    else:
        projected = {}
        for path_text in policy.include:
            path = split_path(path_text)
            found, value = get_path(state, path)
            if found:
                set_path(projected, path, value)

    for path_text in policy.exclude:
        delete_path(projected, split_path(path_text))

    for path_text in policy.summarize:
        path = split_path(path_text)
        found, value = get_path(projected, path)
        if found:
            set_path(projected, path, shape_summary(value))

    return projected


def _normalize_optional_paths(paths: Iterable[str] | None) -> tuple[str, ...] | None:
    return normalize_optional_paths(paths)


def _normalize_paths(paths: Iterable[str]) -> tuple[str, ...]:
    return normalize_paths(paths)


def _validate_name(value: str, field_name: str) -> str:
    if not value.strip():
        raise ValueError(f"{field_name} must not be blank")
    return value


def _path_allowed_by_policy(path: Path, policy: ProjectionPolicy) -> bool:
    include_paths = (
        None
        if policy.include is None
        else tuple(split_path(path_text) for path_text in policy.include)
    )
    included = include_paths is None or any(
        is_prefix(allowed_path, path) for allowed_path in include_paths
    )
    if not included:
        return False

    exclude_paths = tuple(split_path(path_text) for path_text in policy.exclude)
    return not any(
        is_prefix(excluded_path, path) or is_prefix(path, excluded_path)
        for excluded_path in exclude_paths
    )


__all__ = [
    "Contract",
    "NodeContract",
    "ProjectionPolicy",
    "StateContractError",
    "SubgraphContract",
    "project_input",
    "project_output",
    "state_diff",
    "validate_update",
]
