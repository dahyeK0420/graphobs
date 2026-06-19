"""Contract projection helpers."""

from __future__ import annotations

import logging
from typing import Literal, Protocol

from graphobs._observability.payload_policy import (
    payload_summary,
    project_contract_payload,
)
from graphobs.state.paths import (
    StateMapping,
    delete_path,
    get_path,
    set_path,
    split_path,
    state_diff,
)

LOGGER = logging.getLogger("graphobs.contracts")


class ProjectionPolicyLike(Protocol):
    """Minimal projection policy shape for projection helpers."""

    @property
    def include(self) -> tuple[str, ...] | None:
        """Dotted paths included by the policy, or all paths when omitted."""

    @property
    def exclude(self) -> tuple[str, ...]:
        """Dotted paths excluded by the policy."""

    @property
    def summarize(self) -> tuple[str, ...]:
        """Dotted paths summarized by the policy."""

    def project(self, state: StateMapping) -> dict[str, object]:
        """Projects state through the policy."""


class ContractProjection(Protocol):
    """Minimal contract shape used by projection helpers."""

    @property
    def label(self) -> str:
        """Human-readable contract label."""

    @property
    def input_policy(self) -> ProjectionPolicyLike:
        """Public input projection policy."""

    @property
    def output_policy(self) -> ProjectionPolicyLike:
        """Public output projection policy."""


def project_input(
    contract: ContractProjection,
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
    contract: ContractProjection,
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


def project_node_payload(
    contract: ContractProjection,
    payload: StateMapping,
    kind: Literal["input", "output"],
    *,
    fallback_to_summary: bool = False,
) -> dict[str, object]:
    """Projects one input or output payload through a contract policy.

    Args:
        contract: Contract that declares the payload boundary.
        payload: Input or output payload to project.
        kind: Which public contract policy to use.
        fallback_to_summary: Whether projection failures should return a
            compact shape summary instead of raising.

    Returns:
        A projected payload, or a compact summary when fallback is enabled and
        projection fails.

    Raises:
        ValueError: If ``kind`` is not a supported payload direction.
        Exception: Re-raises projection errors when fallback is disabled.
    """
    if kind not in ("input", "output"):
        raise ValueError(f"unsupported payload kind: {kind!r}")

    policy = contract.input_policy if kind == "input" else contract.output_policy
    return project_contract_payload(
        contract_label=contract.label,
        payload=payload,
        payload_kind=kind,
        project=policy.project,
        logger=LOGGER,
        fallback_to_summary=fallback_to_summary,
    )


def project_state(
    policy: ProjectionPolicyLike,
    state: StateMapping,
) -> dict[str, object]:
    """Projects state according to one projection policy."""
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
            set_path(projected, path, payload_summary(value))

    return projected


__all__ = [
    "ContractProjection",
    "ProjectionPolicyLike",
    "project_input",
    "project_node_payload",
    "project_output",
    "project_state",
]
