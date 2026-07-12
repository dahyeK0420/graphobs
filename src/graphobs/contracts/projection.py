"""Contract projection helpers."""

from __future__ import annotations

import logging
from dataclasses import dataclass
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


@dataclass(frozen=True)
class PayloadObservation:
    """How an observed contract payload is projected for telemetry.

    The span execution path and the callback projection path observe the same
    node through different mechanisms; passing one of these explicitly to
    ``observe_payload`` keeps the projection identical between them instead of
    letting fallback and compaction diverge silently.

    Attributes:
        fallback_to_summary: Whether a projection failure returns a compact
            shape summary instead of raising.
        compact: Whether a successfully projected payload is further reduced to
            a message-compact summary.
    """

    fallback_to_summary: bool = False
    compact: bool = False


STRICT_OBSERVATION = PayloadObservation()
COMPACT_OBSERVATION = PayloadObservation(fallback_to_summary=True, compact=True)


def observe_payload(
    contract: ContractProjection,
    payload: StateMapping,
    kind: Literal["input", "output"],
    *,
    observation: PayloadObservation = STRICT_OBSERVATION,
) -> dict[str, object]:
    """Projects one input or output payload for telemetry observation.

    Used by both the span execution path and the callback projection path so a
    contract payload is projected the same way for both, with any tolerance or
    compaction chosen explicitly through ``observation``.

    Args:
        contract: Contract that declares the payload boundary.
        payload: Input or output payload to project.
        kind: Which public contract policy to use.
        observation: Projection tolerance and compaction policy. Defaults to
            ``STRICT_OBSERVATION``, which raises on projection failure and does
            not compact the projected payload.

    Returns:
        A projected payload, or a compact summary when the observation allows
        fallback and projection fails.

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
        fallback_to_summary=observation.fallback_to_summary,
        compact_projected=observation.compact,
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
    "COMPACT_OBSERVATION",
    "STRICT_OBSERVATION",
    "ContractProjection",
    "PayloadObservation",
    "ProjectionPolicyLike",
    "observe_payload",
    "project_input",
    "project_output",
    "project_state",
]
