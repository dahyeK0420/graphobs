"""Shared contract execution lifecycle for integration adapters."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping

from graph_observability_kit._state_paths import StateMapping, StateUpdate
from graph_observability_kit.contracts import (
    Contract,
    ContractViolationAction,
    project_node_payload,
    validate_update,
)
from graph_observability_kit.tracing import (
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
    return_value: UpdateBuilder | None = None,
    on_violation: ContractViolationAction,
    logger: logging.Logger,
    operation_name: str,
) -> StateUpdate:
    """Runs a contract-bound operation with tracing and validation.

    Args:
        contract: Contract that declares the public state boundary.
        state: Full graph state visible at the adapter boundary.
        span_kind: OpenInference span kind value.
        attributes: Attributes to attach to the emitted span.
        execution_input: Builds the state passed to the wrapped operation.
        execute: Runs the wrapped operation.
        validation_update: Builds the update checked against write policies.
        public_output: Builds the state emitted as span output.
        return_value: Optional builder for the adapter return value. Defaults
            to the public output.
        on_violation: Whether undeclared writes raise or log a warning.
        logger: Logger used for adapter-compatible failure messages.
        operation_name: Human-readable adapter name used in failure messages.

    Returns:
        Public output state for the adapter.
    """
    with start_graph_span(
        contract.label,
        span_kind,
        attributes=attributes,
    ) as span:
        try:
            set_span_input(span, project_node_payload(contract, state, "input"))
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
    return_value: UpdateBuilder | None = None,
    on_violation: ContractViolationAction,
    logger: logging.Logger,
    operation_name: str,
) -> StateUpdate:
    """Runs an async contract-bound operation with tracing and validation."""
    with start_graph_span(
        contract.label,
        span_kind,
        attributes=attributes,
    ) as span:
        try:
            set_span_input(span, project_node_payload(contract, state, "input"))
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


__all__ = ["instrument_contract_arun", "instrument_contract_run"]
