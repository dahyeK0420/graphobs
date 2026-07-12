"""Shared contract execution lifecycle for LangGraph integration adapters."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping, MutableMapping
from dataclasses import dataclass

from graphobs.contracts.models import (
    Contract,
    ContractViolationAction,
)
from graphobs.contracts.projection import (
    STRICT_OBSERVATION,
    observe_payload,
    project_output,
)
from graphobs.contracts.validation import validate_update
from graphobs.state.paths import StateMapping, StateUpdate, state_diff
from graphobs.tracing import (
    mark_span_error,
    set_span_input,
    set_span_output,
    start_graph_span,
)

ExecutionInputBuilder = Callable[[StateMapping], StateMapping]
ExecutionStep = Callable[[StateMapping], StateMapping]
AsyncExecutionStep = Callable[[StateMapping], Awaitable[StateMapping]]
UpdateBuilder = Callable[[StateMapping, StateMapping], StateUpdate]
SpanPayloadBuilder = Callable[[StateMapping], dict[str, object]]


@dataclass(frozen=True)
class ContractRunSpec:
    """Describes one contract-bound execution lifecycle."""

    contract: Contract
    span_kind: str
    attributes: Mapping[str, object]
    execution_input: ExecutionInputBuilder
    span_input: SpanPayloadBuilder
    validation_update: UpdateBuilder
    public_output: UpdateBuilder
    return_value: UpdateBuilder | None
    on_violation: ContractViolationAction
    logger: logging.Logger
    operation_name: str


def instrument_contract_run(
    spec: ContractRunSpec,
    state: StateMapping,
    *,
    execute: ExecutionStep,
) -> StateUpdate:
    """Runs a contract-bound operation with tracing and validation."""
    with start_graph_span(
        spec.contract.label,
        spec.span_kind,
        attributes=spec.attributes,
    ) as span:
        try:
            set_span_input(span, spec.span_input(state))
            run_input = spec.execution_input(state)
            run_result = execute(run_input)
            validate_update(
                spec.contract,
                spec.validation_update(run_input, run_result),
                on_violation=spec.on_violation,
            )
            output = spec.public_output(run_input, run_result)
            set_span_output(span, output)
            if spec.return_value is None:
                return output
            return spec.return_value(run_input, run_result)
        except Exception as exc:
            spec.logger.error(
                "%s %s failed: %s",
                spec.operation_name,
                spec.contract.label,
                exc,
            )
            mark_span_error(span, exc)
            raise


async def instrument_contract_arun(
    spec: ContractRunSpec,
    state: StateMapping,
    *,
    execute: AsyncExecutionStep,
) -> StateUpdate:
    """Runs an async contract-bound operation with tracing and validation."""
    with start_graph_span(
        spec.contract.label,
        spec.span_kind,
        attributes=spec.attributes,
    ) as span:
        try:
            set_span_input(span, spec.span_input(state))
            run_input = spec.execution_input(state)
            run_result = await execute(run_input)
            validate_update(
                spec.contract,
                spec.validation_update(run_input, run_result),
                on_violation=spec.on_violation,
            )
            output = spec.public_output(run_input, run_result)
            set_span_output(span, output)
            if spec.return_value is None:
                return output
            return spec.return_value(run_input, run_result)
        except Exception as exc:
            spec.logger.error(
                "%s %s failed: %s",
                spec.operation_name,
                spec.contract.label,
                exc,
            )
            mark_span_error(span, exc)
            raise


def node_contract_run_spec(
    contract: Contract,
    *,
    span_kind: str,
    attributes: Mapping[str, object],
    execution_input: ExecutionInputBuilder,
    on_violation: ContractViolationAction,
    logger: logging.Logger,
) -> ContractRunSpec:
    """Builds the execution lifecycle for one contract node."""
    return ContractRunSpec(
        contract=contract,
        span_kind=span_kind,
        attributes=attributes,
        execution_input=execution_input,
        span_input=lambda raw_state: observe_payload(
            contract,
            raw_state,
            "input",
            observation=STRICT_OBSERVATION,
        ),
        validation_update=lambda _run_input, update: update,
        public_output=lambda _run_input, update: observe_payload(
            contract,
            update,
            "output",
            observation=STRICT_OBSERVATION,
        ),
        return_value=lambda _run_input, update: update,
        on_violation=on_violation,
        logger=logger,
        operation_name="Contract node",
    )


def subgraph_contract_run_spec(
    contract: Contract,
    *,
    span_kind: str,
    attributes: Mapping[str, object],
    on_violation: ContractViolationAction,
    logger: logging.Logger,
) -> ContractRunSpec:
    """Builds the execution lifecycle for one contract subgraph."""
    return ContractRunSpec(
        contract=contract,
        span_kind=span_kind,
        attributes=attributes,
        execution_input=lambda raw_state: build_execution_input(contract, raw_state),
        span_input=lambda raw_state: observe_payload(
            contract,
            raw_state,
            "input",
            observation=STRICT_OBSERVATION,
        ),
        validation_update=state_diff,
        public_output=lambda subgraph_input, after_state: project_output(
            contract,
            subgraph_input,
            after_state,
        ),
        return_value=None,
        on_violation=on_violation,
        logger=logger,
        operation_name="Contract subgraph",
    )


def build_execution_input(
    contract: Contract,
    state: StateMapping,
) -> dict[str, object]:
    """Builds adapter execution input from a contract's execution policies."""
    execution_input: dict[str, object] = {}
    for policy in contract.execution_input_policies:
        execution_input = _merge_mappings(execution_input, policy.project(state))
    return execution_input


def _merge_mappings(
    public_values: Mapping[str, object],
    private_values: Mapping[str, object],
) -> dict[str, object]:
    merged = dict(public_values)
    for key, value in private_values.items():
        existing = merged.get(key)
        if isinstance(existing, MutableMapping) and isinstance(value, Mapping):
            merged[key] = _merge_mappings(existing, value)
        else:
            merged[key] = value
    return merged


__all__ = [
    "ContractRunSpec",
    "build_execution_input",
    "instrument_contract_arun",
    "instrument_contract_run",
    "node_contract_run_spec",
    "subgraph_contract_run_spec",
]
