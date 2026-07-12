"""Contract projection helpers."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from graphobs._observability.payload_policy import project_contract_payload
from graphobs.contracts.models import Contract
from graphobs.state.paths import StateMapping, state_diff

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

    Controls the two knobs applied after a contract's projection policy runs. It
    does not choose which policy is applied; it only decides what happens on a
    projection failure and whether the projected payload is compacted in this
    layer.

    The two knobs exist because the span path and the callback path compact in
    different places. The span path uses ``STRICT_OBSERVATION`` and leaves final
    compaction to the tracing serializer (message-compact by default). The
    callback path has no span to serialize, so it uses ``COMPACT_OBSERVATION``
    to compact inline. Both routes reduce through the same
    ``message_compact_summary`` helper, so they agree on shape.

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


__all__ = [
    "COMPACT_OBSERVATION",
    "STRICT_OBSERVATION",
    "PayloadObservation",
    "observe_payload",
    "project_input",
    "project_output",
]
