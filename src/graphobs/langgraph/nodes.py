"""Contract-wrapped LangGraph node helpers."""

from __future__ import annotations

import inspect
import logging
from collections.abc import Awaitable, Callable, Mapping
from functools import wraps
from typing import Any, Protocol, TypeAlias, cast, overload

from graphobs.contracts.models import (
    Contract,
    ContractViolationAction,
    NodeContract,
)
from graphobs.langgraph.execution import (
    build_execution_input,
    instrument_contract_arun,
    instrument_contract_run,
    node_contract_run_spec,
)
from graphobs.langgraph.read_audit import (
    enforce_undeclared_reads,
)
from graphobs.langgraph.schemas import (
    langgraph_input_schema,
)
from graphobs.state.paths import StateMapping, StateUpdate
from graphobs.state.read_tracking import (
    ReadTracker,
    ReadTrackingMapping,
)

LOGGER = logging.getLogger("graphobs.langgraph")
DEFAULT_SPAN_KIND = "CHAIN"

NodeFunction: TypeAlias = Callable[..., StateUpdate]
AsyncNodeFunction: TypeAlias = Callable[..., Awaitable[StateUpdate]]
NodeWrapper: TypeAlias = NodeFunction | AsyncNodeFunction


class ContractNodeDecorator(Protocol):
    """Decorator returned by ``contract_node(contract)``."""

    @overload
    def __call__(self, fn: NodeFunction, /) -> NodeFunction: ...

    @overload
    def __call__(self, fn: AsyncNodeFunction, /) -> AsyncNodeFunction: ...


class NodeBuilder(Protocol):
    """Graph builder shape required to register a contract node."""

    def add_node(self, *args: Any, **kwargs: Any) -> object:
        """Adds a node to a graph builder."""


@overload
def contract_node(
    contract: NodeContract,
    /,
    *,
    on_violation: ContractViolationAction = ContractViolationAction.RAISE,
    pass_through_state: bool = False,
    audit_reads: bool = False,
) -> ContractNodeDecorator: ...


@overload
def contract_node(
    fn: NodeFunction,
    contract: NodeContract,
    *,
    on_violation: ContractViolationAction = ContractViolationAction.RAISE,
    pass_through_state: bool = False,
    audit_reads: bool = False,
) -> NodeFunction: ...


@overload
def contract_node(
    fn: AsyncNodeFunction,
    contract: NodeContract,
    *,
    on_violation: ContractViolationAction = ContractViolationAction.RAISE,
    pass_through_state: bool = False,
    audit_reads: bool = False,
) -> AsyncNodeFunction: ...


def contract_node(
    fn: NodeWrapper | NodeContract,
    contract: NodeContract | None = None,
    *,
    on_violation: ContractViolationAction = ContractViolationAction.RAISE,
    pass_through_state: bool = False,
    audit_reads: bool = False,
) -> NodeWrapper | ContractNodeDecorator:
    """Wraps a LangGraph node with contract projection, validation, and tracing.

    The wrapped node receives only declared public reads plus declared private
    reads. The emitted span input and output remain public-contract projections.
    The helper can be called as ``contract_node(fn, contract)`` or used as a
    decorator with ``@contract_node(contract)``.

    Strict execution audits reads and enforces them with ``on_violation``, so a
    read outside the contract raises ``StateContractError`` by default instead
    of silently resolving to a projected default value.

    Args:
        fn: Node function to wrap, or a contract when used as a decorator.
        contract: Node state and trace contract for explicit wrapping.
        on_violation: Whether undeclared writes, and undeclared reads in strict
            execution, raise or log a warning.
        pass_through_state: Whether the wrapped node should receive the
            original graph state instead of projected execution input.
        audit_reads: In pass-through execution, whether undeclared reads log a
            warning. Strict execution always audits reads and enforces them
            with ``on_violation``.

    Returns:
        A callable with the same sync or async execution style as the original
        node, or a decorator that creates such a callable.

    Raises:
        TypeError: If called with an unsupported argument shape.
    """
    if isinstance(fn, NodeContract) and contract is None:
        decorator_contract = fn

        def decorator(node_fn: NodeWrapper) -> NodeWrapper:
            return _wrap_contract_node(
                node_fn,
                decorator_contract,
                on_violation=on_violation,
                pass_through_state=pass_through_state,
                audit_reads=audit_reads,
            )

        return cast(ContractNodeDecorator, decorator)

    if callable(fn) and isinstance(contract, NodeContract):
        return _wrap_contract_node(
            fn,
            contract,
            on_violation=on_violation,
            pass_through_state=pass_through_state,
            audit_reads=audit_reads,
        )

    error = TypeError(
        "contract_node expects (fn, contract) or (contract) for decorator use"
    )
    LOGGER.error("Failed to prepare contract node wrapper: %s", error)
    raise error


def _wrap_contract_node(
    fn: NodeWrapper,
    contract: NodeContract,
    *,
    on_violation: ContractViolationAction,
    pass_through_state: bool,
    audit_reads: bool,
) -> NodeWrapper:
    track_reads, read_violation = _read_audit_plan(
        pass_through_state=pass_through_state,
        audit_reads=audit_reads,
        on_violation=on_violation,
    )
    if inspect.iscoroutinefunction(fn):
        async_fn = cast(AsyncNodeFunction, fn)

        @wraps(async_fn)
        async def async_wrapper(state: StateMapping, **kwargs: Any) -> StateUpdate:
            tracker = ReadTracker() if track_reads else None

            async def execute(run_input: StateMapping) -> StateUpdate:
                update = await async_fn(run_input, **kwargs)
                enforce_undeclared_reads(contract, tracker, on_violation=read_violation)
                return update

            spec = node_contract_run_spec(
                contract,
                span_kind=contract.span_kind or DEFAULT_SPAN_KIND,
                attributes=_node_attributes(contract),
                execution_input=lambda raw_state: _node_execution_input(
                    contract,
                    raw_state,
                    pass_through_state=pass_through_state,
                    tracker=tracker,
                ),
                on_violation=on_violation,
                logger=LOGGER,
            )
            return await instrument_contract_arun(
                spec,
                state,
                execute=execute,
            )

        return async_wrapper

    sync_fn = cast(NodeFunction, fn)

    @wraps(sync_fn)
    def sync_wrapper(state: StateMapping, **kwargs: Any) -> StateUpdate:
        tracker = ReadTracker() if track_reads else None

        def execute(run_input: StateMapping) -> StateUpdate:
            update = sync_fn(run_input, **kwargs)
            enforce_undeclared_reads(contract, tracker, on_violation=read_violation)
            return update

        spec = node_contract_run_spec(
            contract,
            span_kind=contract.span_kind or DEFAULT_SPAN_KIND,
            attributes=_node_attributes(contract),
            execution_input=lambda raw_state: _node_execution_input(
                contract,
                raw_state,
                pass_through_state=pass_through_state,
                tracker=tracker,
            ),
            on_violation=on_violation,
            logger=LOGGER,
        )
        return instrument_contract_run(
            spec,
            state,
            execute=execute,
        )

    return sync_wrapper


def add_contract_node(
    graph: NodeBuilder,
    contract: NodeContract,
    fn: NodeWrapper,
    *,
    on_violation: ContractViolationAction = ContractViolationAction.RAISE,
    pass_through_state: bool = False,
    audit_reads: bool = False,
) -> object:
    """Adds a contract-wrapped node to a LangGraph ``StateGraph`` builder.

    Args:
        graph: Graph builder exposing ``add_node``.
        contract: Node state and trace contract.
        fn: Synchronous or asynchronous node function.
        on_violation: Whether undeclared writes, and undeclared reads in strict
            execution, raise or log a warning.
        pass_through_state: Whether the node receives the original graph state.
        audit_reads: In pass-through execution, whether undeclared reads are
            logged. Strict execution always audits reads.

    Returns:
        The graph builder returned by ``add_node``.
    """
    wrapped = contract_node(
        fn,
        contract,
        on_violation=on_violation,
        pass_through_state=pass_through_state,
        audit_reads=audit_reads,
    )
    input_schema = None if pass_through_state else langgraph_input_schema(contract)

    try:
        if input_schema is None:
            return graph.add_node(contract.label, wrapped)
        return graph.add_node(contract.label, wrapped, input_schema=input_schema)
    except Exception as exc:
        LOGGER.error("Failed to add contract node %s: %s", contract.label, exc)
        raise


def _read_audit_plan(
    *,
    pass_through_state: bool,
    audit_reads: bool,
    on_violation: ContractViolationAction,
) -> tuple[bool, ContractViolationAction]:
    """Decides whether to audit reads and how read violations are handled.

    Strict execution always audits reads and enforces them with the node's
    violation action, so undeclared reads fail loudly by default instead of
    silently resolving to a projected value. Pass-through execution keeps
    auditing opt-in and warning-only, because the node intentionally receives
    the full graph state. The returned action is unused when reads are not
    audited.

    Returns:
        A ``(audit_reads, read_violation)`` pair.
    """
    if not pass_through_state:
        return True, on_violation
    if audit_reads:
        return True, ContractViolationAction.WARN
    return False, on_violation


def _node_attributes(contract: NodeContract) -> Mapping[str, object]:
    attributes: dict[str, object] = {"graph.node": contract.label}
    attributes.update(contract.attributes)
    return attributes


def _node_execution_input(
    contract: Contract,
    state: StateMapping,
    *,
    pass_through_state: bool,
    tracker: ReadTracker | None,
) -> StateMapping:
    execution_input = (
        state
        if pass_through_state
        else build_execution_input(
            contract,
            state,
        )
    )
    if tracker is None:
        return execution_input
    return ReadTrackingMapping(execution_input, tracker)


__all__ = [
    "AsyncNodeFunction",
    "ContractNodeDecorator",
    "NodeBuilder",
    "NodeFunction",
    "NodeWrapper",
    "add_contract_node",
    "contract_node",
]
