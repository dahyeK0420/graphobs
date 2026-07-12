"""Contract-wrapped LangGraph node helpers."""

from __future__ import annotations

import inspect
import logging
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
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


class NodeContractMode(StrEnum):
    """Selects how a contract-wrapped node treats state reads and violations.

    The modes form an adoption ladder from non-invasive observation to strict
    enforcement. Every mode still emits contract-projected span input and
    output; the mode only changes execution:

    - ``OBSERVE``: the node receives the full graph state unchanged. Undeclared
      writes are logged as warnings and still forwarded, and reads are not
      audited. Use for trace hygiene without any execution change.
    - ``AUDIT``: like ``OBSERVE``, but undeclared reads are also logged as
      warnings. Use during migration to surface a node's real state boundary.
    - ``ENFORCE``: the node receives only its declared reads, and an undeclared
      read or write raises ``StateContractError``. Use for stable nodes whose
      boundary should be guaranteed.
    """

    OBSERVE = "observe"
    AUDIT = "audit"
    ENFORCE = "enforce"


@dataclass(frozen=True)
class _ModeExecution:
    """Internal execution settings a ``NodeContractMode`` resolves to."""

    pass_through_state: bool
    audit_reads: bool
    on_violation: ContractViolationAction


_MODE_EXECUTIONS: dict[NodeContractMode, _ModeExecution] = {
    NodeContractMode.OBSERVE: _ModeExecution(
        pass_through_state=True,
        audit_reads=False,
        on_violation=ContractViolationAction.WARN,
    ),
    NodeContractMode.AUDIT: _ModeExecution(
        pass_through_state=True,
        audit_reads=True,
        on_violation=ContractViolationAction.WARN,
    ),
    NodeContractMode.ENFORCE: _ModeExecution(
        pass_through_state=False,
        audit_reads=False,
        on_violation=ContractViolationAction.RAISE,
    ),
}


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
    mode: NodeContractMode = NodeContractMode.ENFORCE,
) -> ContractNodeDecorator: ...


@overload
def contract_node(
    fn: NodeFunction,
    contract: NodeContract,
    *,
    mode: NodeContractMode = NodeContractMode.ENFORCE,
) -> NodeFunction: ...


@overload
def contract_node(
    fn: AsyncNodeFunction,
    contract: NodeContract,
    *,
    mode: NodeContractMode = NodeContractMode.ENFORCE,
) -> AsyncNodeFunction: ...


def contract_node(
    fn: NodeWrapper | NodeContract,
    contract: NodeContract | None = None,
    *,
    mode: NodeContractMode = NodeContractMode.ENFORCE,
) -> NodeWrapper | ContractNodeDecorator:
    """Wraps a LangGraph node with contract projection, validation, and tracing.

    The emitted span input and output are always public-contract projections.
    The ``mode`` decides how execution is affected, from non-invasive
    ``OBSERVE`` through migration-friendly ``AUDIT`` to strict ``ENFORCE`` (see
    ``NodeContractMode``). The helper can be called as ``contract_node(fn,
    contract)`` or used as a decorator with ``@contract_node(contract)``.

    Args:
        fn: Node function to wrap, or a contract when used as a decorator.
        contract: Node state and trace contract for explicit wrapping.
        mode: Execution mode from ``NodeContractMode``. Defaults to
            ``ENFORCE``, which projects the node's input to declared reads and
            raises on an undeclared read or write.

    Returns:
        A callable with the same sync or async execution style as the original
        node, or a decorator that creates such a callable.

    Raises:
        TypeError: If called with an unsupported argument shape.
    """
    execution = _mode_execution(mode)
    if isinstance(fn, NodeContract) and contract is None:
        decorator_contract = fn

        def decorator(node_fn: NodeWrapper) -> NodeWrapper:
            return _wrap_contract_node(
                node_fn,
                decorator_contract,
                execution=execution,
            )

        return cast(ContractNodeDecorator, decorator)

    if callable(fn) and isinstance(contract, NodeContract):
        return _wrap_contract_node(fn, contract, execution=execution)

    error = TypeError(
        "contract_node expects (fn, contract) or (contract) for decorator use"
    )
    LOGGER.error("Failed to prepare contract node wrapper: %s", error)
    raise error


def _wrap_contract_node(
    fn: NodeWrapper,
    contract: NodeContract,
    *,
    execution: _ModeExecution,
) -> NodeWrapper:
    track_reads, read_violation = _read_audit_plan(execution)
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
                    pass_through_state=execution.pass_through_state,
                    tracker=tracker,
                ),
                on_violation=execution.on_violation,
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
                pass_through_state=execution.pass_through_state,
                tracker=tracker,
            ),
            on_violation=execution.on_violation,
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
    mode: NodeContractMode = NodeContractMode.ENFORCE,
) -> object:
    """Adds a contract-wrapped node to a LangGraph ``StateGraph`` builder.

    Args:
        graph: Graph builder exposing ``add_node``.
        contract: Node state and trace contract.
        fn: Synchronous or asynchronous node function.
        mode: Execution mode from ``NodeContractMode``. ``ENFORCE`` registers a
            narrowed input schema; ``OBSERVE`` and ``AUDIT`` register the node
            against the full graph state.

    Returns:
        The graph builder returned by ``add_node``.
    """
    wrapped = contract_node(fn, contract, mode=mode)
    input_schema = (
        None
        if _mode_execution(mode).pass_through_state
        else langgraph_input_schema(contract)
    )

    try:
        if input_schema is None:
            return graph.add_node(contract.label, wrapped)
        return graph.add_node(contract.label, wrapped, input_schema=input_schema)
    except Exception as exc:
        LOGGER.error("Failed to add contract node %s: %s", contract.label, exc)
        raise


def add_contract_nodes(
    graph: NodeBuilder,
    contracts: Iterable[tuple[NodeContract, NodeWrapper]],
    *,
    mode: NodeContractMode = NodeContractMode.ENFORCE,
) -> tuple[object, ...]:
    """Registers several contract-wrapped nodes on a graph builder in one call.

    One execution mode is applied uniformly to every node, which suits initial
    whole-graph adoption in ``NodeContractMode.OBSERVE`` before promoting
    individual nodes to ``NodeContractMode.ENFORCE``.

    Args:
        graph: Graph builder exposing ``add_node``.
        contracts: ``(contract, node function)`` pairs in registration order.
        mode: Execution mode applied to every registered node.

    Returns:
        The ``add_node`` results in registration order.
    """
    return tuple(
        add_contract_node(graph, contract, fn, mode=mode) for contract, fn in contracts
    )


def _mode_execution(mode: NodeContractMode) -> _ModeExecution:
    """Resolves the execution settings for one node contract mode."""
    return _MODE_EXECUTIONS[mode]


def _read_audit_plan(
    execution: _ModeExecution,
) -> tuple[bool, ContractViolationAction]:
    """Decides whether to audit reads and how read violations are handled.

    Strict execution always audits reads and enforces them with the node's
    violation action, so undeclared reads fail loudly instead of silently
    resolving to a projected value. Pass-through execution keeps auditing
    opt-in and warning-only, because the node intentionally receives the full
    graph state. The returned action is unused when reads are not audited.

    Returns:
        A ``(audit_reads, read_violation)`` pair.
    """
    if not execution.pass_through_state:
        return True, execution.on_violation
    if execution.audit_reads:
        return True, ContractViolationAction.WARN
    return False, execution.on_violation


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
    "NodeContractMode",
    "NodeFunction",
    "NodeWrapper",
    "add_contract_node",
    "add_contract_nodes",
    "contract_node",
]
