"""Contract projection helpers."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from graphobs.payloads import project_contract_payload
from graphobs.state.paths import (
    StateMapping,
    get_path,
    set_path,
    split_path,
    state_diff,
)

if TYPE_CHECKING:
    from graphobs.contracts.models import Contract, ProjectionPolicy

LOGGER = logging.getLogger("graphobs.contracts")


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
    contract: Contract,
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
    policy: ProjectionPolicy,
    state: StateMapping,
) -> dict[str, object]:
    """Projects state according to one projection policy."""
    if policy.include is None:
        return dict(state)
    projected: dict[str, object] = {}
    for path_text in policy.include:
        path = split_path(path_text)
        found, value = get_path(state, path)
        if found:
            set_path(projected, path, value)
    return projected


__all__ = [
    "COMPACT_OBSERVATION",
    "STRICT_OBSERVATION",
    "PayloadObservation",
    "observe_payload",
    "project_input",
    "project_output",
    "project_state",
]
