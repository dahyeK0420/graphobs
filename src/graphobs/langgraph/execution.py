"""Shared contract execution lifecycle for LangGraph integration adapters."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping, MutableMapping

from graphobs.contracts.conformance import validate_update
from graphobs.contracts.models import (
    Contract,
    ContractViolationAction,
)
from graphobs.contracts.projection import (
    STRICT_OBSERVATION,
    observe_payload,
)
from graphobs.state.paths import StateMapping, StateUpdate
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


def instrument_contract_run(
    contract: Contract,
    state: StateMapping,
    *,
    span_kind: str,
    attributes: Mapping[str, object],
    execution_input: ExecutionInputBuilder,
    execute: ExecutionStep,
    validation_update: UpdateBuilder,
    public_output: UpdateBuilder,
    return_value: UpdateBuilder | None,
    on_violation: ContractViolationAction,
    logger: logging.Logger,
    operation_name: str,
) -> StateUpdate:
    """Runs a contract-bound operation with tracing and validation.

    Opens one span, records the contract-projected input, runs ``execute`` on
    the projected execution input, validates the update, records the projected
    public output, then returns that output or an explicit ``return_value``.

    Args:
        contract: Contract that owns the span label and projection policies.
        state: Full graph state passed to the wrapped operation.
        span_kind: OpenInference span kind label.
        attributes: Searchable span attributes.
        execution_input: Builds the input actually passed to ``execute``.
        execute: Runs the wrapped node or subgraph on the execution input.
        validation_update: Builds the update validated against write policies.
        public_output: Builds the projected output recorded on the span.
        return_value: Builds the wrapper return value, or ``None`` to return the
            projected public output.
        on_violation: Whether undeclared writes raise or log a warning.
        logger: Logger that records failures.
        operation_name: Human-readable operation label used in failure logs.

    Returns:
        The projected public output, or the explicit ``return_value`` result.
    """
    with start_graph_span(contract.label, span_kind, attributes=attributes) as span:
        try:
            span_input = observe_payload(
                contract, state, "input", observation=STRICT_OBSERVATION
            )
            set_span_input(span, span_input)
            run_input = execution_input(state)
            run_result = execute(run_input)
            validate_update(
                contract,
                validation_update(run_input, run_result),
                on_violation=on_violation,
            )
            output = public_output(run_input, run_result)
            set_span_output(span, output)
            if return_value is None:
                return output
            return return_value(run_input, run_result)
        except Exception as exc:
            logger.error("%s %s failed: %s", operation_name, contract.label, exc)
            mark_span_error(span, exc)
            raise


async def instrument_contract_arun(
    contract: Contract,
    state: StateMapping,
    *,
    span_kind: str,
    attributes: Mapping[str, object],
    execution_input: ExecutionInputBuilder,
    execute: AsyncExecutionStep,
    validation_update: UpdateBuilder,
    public_output: UpdateBuilder,
    return_value: UpdateBuilder | None,
    on_violation: ContractViolationAction,
    logger: logging.Logger,
    operation_name: str,
) -> StateUpdate:
    """Runs an async contract-bound operation with tracing and validation.

    Asynchronous counterpart to ``instrument_contract_run``; see that function
    for the argument and return semantics.
    """
    with start_graph_span(contract.label, span_kind, attributes=attributes) as span:
        try:
            span_input = observe_payload(
                contract, state, "input", observation=STRICT_OBSERVATION
            )
            set_span_input(span, span_input)
            run_input = execution_input(state)
            run_result = await execute(run_input)
            validate_update(
                contract,
                validation_update(run_input, run_result),
                on_violation=on_violation,
            )
            output = public_output(run_input, run_result)
            set_span_output(span, output)
            if return_value is None:
                return output
            return return_value(run_input, run_result)
        except Exception as exc:
            logger.error("%s %s failed: %s", operation_name, contract.label, exc)
            mark_span_error(span, exc)
            raise


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
    "build_execution_input",
    "instrument_contract_arun",
    "instrument_contract_run",
]
