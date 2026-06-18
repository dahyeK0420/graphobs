"""LangGraph integration helpers for contract-wrapped graph execution."""

from __future__ import annotations

import inspect
import logging
import typing
from collections.abc import Awaitable, Callable, Mapping, MutableMapping
from functools import wraps
from typing import Any, Protocol, TypeAlias, cast, overload

from langchain_core.runnables import RunnableConfig

from graph_observability_kit._instrumented_execution import (
    instrument_contract_arun,
    instrument_contract_run,
)
from graph_observability_kit._read_tracking import ReadTracker, ReadTrackingMapping
from graph_observability_kit._state_paths import (
    Path,
    StateMapping,
    StateUpdate,
    is_prefix,
    split_path,
    state_diff,
)
from graph_observability_kit.contracts import (
    Contract,
    ContractViolationAction,
    NodeContract,
    ProjectionPolicy,
    SubgraphContract,
    project_node_payload,
    project_output,
)

LOGGER = logging.getLogger(__name__)
DEFAULT_SPAN_KIND = "CHAIN"
_NO_CONFIG: RunnableConfig = cast(RunnableConfig, None)

NodeFunction: TypeAlias = Callable[..., StateUpdate]
AsyncNodeFunction: TypeAlias = Callable[..., Awaitable[StateUpdate]]
NodeWrapper: TypeAlias = NodeFunction | AsyncNodeFunction


class ContractNodeDecorator(Protocol):
    """Decorator returned by ``contract_node(contract)``."""

    @overload
    def __call__(self, fn: NodeFunction, /) -> NodeFunction: ...

    @overload
    def __call__(self, fn: AsyncNodeFunction, /) -> AsyncNodeFunction: ...


class TypedDictFactory(Protocol):
    """Runtime callable shape for the functional ``TypedDict`` factory."""

    def __call__(
        self,
        typename: str,
        fields: dict[str, type[object]],
        *,
        total: bool,
    ) -> type[object]:
        """Creates a ``TypedDict`` class."""


class InvokableGraph(Protocol):
    """Compiled graph shape required for synchronous subgraph execution."""

    def invoke(self, *args: Any, **kwargs: Any) -> object:
        """Invokes a compiled graph synchronously."""


class AsyncInvokableGraph(Protocol):
    """Compiled graph shape required for asynchronous subgraph execution."""

    def ainvoke(self, *args: Any, **kwargs: Any) -> Awaitable[object]:
        """Invokes a compiled graph asynchronously."""


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

    Args:
        fn: Node function to wrap, or a contract when used as a decorator.
        contract: Node state and trace contract for explicit wrapping.
        on_violation: Whether undeclared writes raise or log a warning.
        pass_through_state: Whether the wrapped node should receive the
            original graph state instead of projected execution input.
        audit_reads: Whether observed state reads should warn when they are not
            declared by public or private read policies.

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
    if inspect.iscoroutinefunction(fn):
        async_fn = cast(AsyncNodeFunction, fn)

        @wraps(async_fn)
        async def async_wrapper(state: StateMapping, **kwargs: Any) -> StateUpdate:
            tracker = ReadTracker() if audit_reads else None

            async def execute(run_input: StateMapping) -> StateUpdate:
                update = await async_fn(run_input, **kwargs)
                _warn_undeclared_reads(contract, tracker)
                return update

            return await instrument_contract_arun(
                contract,
                state,
                span_kind=contract.span_kind or DEFAULT_SPAN_KIND,
                attributes=_node_attributes(contract),
                execution_input=lambda raw_state: _node_execution_input(
                    contract,
                    raw_state,
                    pass_through_state=pass_through_state,
                    tracker=tracker,
                ),
                execute=execute,
                validation_update=lambda _run_input, update: update,
                public_output=lambda _run_input, update: project_node_payload(
                    contract,
                    update,
                    "output",
                ),
                return_value=lambda _run_input, update: update,
                on_violation=on_violation,
                logger=LOGGER,
                operation_name="Contract node",
            )

        return async_wrapper

    sync_fn = cast(NodeFunction, fn)

    @wraps(sync_fn)
    def sync_wrapper(state: StateMapping, **kwargs: Any) -> StateUpdate:
        tracker = ReadTracker() if audit_reads else None

        def execute(run_input: StateMapping) -> StateUpdate:
            update = sync_fn(run_input, **kwargs)
            _warn_undeclared_reads(contract, tracker)
            return update

        return instrument_contract_run(
            contract,
            state,
            span_kind=contract.span_kind or DEFAULT_SPAN_KIND,
            attributes=_node_attributes(contract),
            execution_input=lambda raw_state: _node_execution_input(
                contract,
                raw_state,
                pass_through_state=pass_through_state,
                tracker=tracker,
            ),
            execute=execute,
            validation_update=lambda _run_input, update: update,
            public_output=lambda _run_input, update: project_node_payload(
                contract,
                update,
                "output",
            ),
            return_value=lambda _run_input, update: update,
            on_violation=on_violation,
            logger=LOGGER,
            operation_name="Contract node",
        )

    return sync_wrapper


@overload
def contract_subgraph(
    compiled_graph: InvokableGraph,
    contract: SubgraphContract,
    *,
    on_violation: ContractViolationAction = ContractViolationAction.RAISE,
) -> NodeFunction: ...


@overload
def contract_subgraph(
    compiled_graph: AsyncInvokableGraph,
    contract: SubgraphContract,
    *,
    on_violation: ContractViolationAction = ContractViolationAction.RAISE,
) -> AsyncNodeFunction: ...


def contract_subgraph(
    compiled_graph: InvokableGraph | AsyncInvokableGraph,
    contract: SubgraphContract,
    *,
    on_violation: ContractViolationAction = ContractViolationAction.RAISE,
) -> NodeWrapper:
    """Wraps a compiled LangGraph subgraph with parent-boundary contracts.

    The subgraph receives only declared parent input plus declared private state
    keys. The wrapper returns only declared parent output changes.

    Args:
        compiled_graph: Compiled graph object with ``invoke``.
        contract: Subgraph parent boundary contract.
        on_violation: Whether undeclared writes raise or log a warning.

    Returns:
        A node callable suitable for ``StateGraph.add_node``.
    """
    if hasattr(compiled_graph, "ainvoke") and not hasattr(compiled_graph, "invoke"):
        return _contract_async_subgraph(
            compiled_graph,
            contract,
            on_violation=on_violation,
        )
    return _contract_sync_subgraph(
        cast(InvokableGraph, compiled_graph),
        contract,
        on_violation=on_violation,
    )


def _contract_sync_subgraph(
    compiled_graph: InvokableGraph,
    contract: SubgraphContract,
    *,
    on_violation: ContractViolationAction,
) -> NodeFunction:
    def wrapper(
        state: StateMapping,
        config: RunnableConfig = _NO_CONFIG,
    ) -> StateUpdate:
        def execute(subgraph_input: StateMapping) -> StateMapping:
            return _invoke_compiled_graph(
                compiled_graph,
                subgraph_input,
                config=config,
            )

        return instrument_contract_run(
            contract,
            state,
            span_kind=DEFAULT_SPAN_KIND,
            attributes={"graph.subgraph": contract.label},
            execution_input=lambda raw_state: _execution_input(contract, raw_state),
            execute=execute,
            validation_update=state_diff,
            public_output=lambda subgraph_input, after_state: project_output(
                contract,
                subgraph_input,
                after_state,
            ),
            on_violation=on_violation,
            logger=LOGGER,
            operation_name="Contract subgraph",
        )

    return wrapper


def _contract_async_subgraph(
    compiled_graph: AsyncInvokableGraph,
    contract: SubgraphContract,
    *,
    on_violation: ContractViolationAction,
) -> AsyncNodeFunction:
    async def wrapper(
        state: StateMapping,
        config: RunnableConfig = _NO_CONFIG,
    ) -> StateUpdate:
        async def execute(subgraph_input: StateMapping) -> StateMapping:
            return await _ainvoke_compiled_graph(
                compiled_graph,
                subgraph_input,
                config=config,
            )

        return await instrument_contract_arun(
            contract,
            state,
            span_kind=DEFAULT_SPAN_KIND,
            attributes={"graph.subgraph": contract.label},
            execution_input=lambda raw_state: _execution_input(contract, raw_state),
            execute=execute,
            validation_update=state_diff,
            public_output=lambda subgraph_input, after_state: project_output(
                contract,
                subgraph_input,
                after_state,
            ),
            on_violation=on_violation,
            logger=LOGGER,
            operation_name="Contract subgraph",
        )

    return wrapper


def langgraph_input_schema(contract: Contract) -> type[object] | None:
    """Builds a best-effort LangGraph input schema from explicit contract keys.

    Args:
        contract: Contract that declares public and execution input policies.

    Returns:
        A dynamic ``TypedDict`` schema, or ``None`` when the contract cannot be
        safely narrowed.
    """
    try:
        fields = _top_level_fields(contract.execution_input_policies)
        typed_dict = cast(TypedDictFactory, typing.TypedDict)
        return typed_dict(f"{_schema_name(contract.label)}Input", fields, total=False)
    except ValueError as exc:
        LOGGER.warning(
            "Could not build LangGraph input schema for %s: %s",
            contract.label,
            exc,
        )
        return None


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
        on_violation: Whether undeclared writes raise or log a warning.
        pass_through_state: Whether the node receives the original graph state.
        audit_reads: Whether undeclared runtime reads should be logged.

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


def _node_attributes(contract: NodeContract) -> Mapping[str, object]:
    attributes: dict[str, object] = {"graph.node": contract.label}
    attributes.update(contract.attributes)
    return attributes


def _invoke_compiled_graph(
    compiled_graph: InvokableGraph,
    subgraph_input: StateMapping,
    *,
    config: RunnableConfig | None = None,
) -> StateMapping:
    if config is not None and _call_accepts_config(compiled_graph.invoke):
        result = compiled_graph.invoke(subgraph_input, config=config)
    else:
        result = compiled_graph.invoke(subgraph_input)
    if not isinstance(result, Mapping):
        error = TypeError(
            f"compiled graph returned unsupported type: {type(result).__name__}"
        )
        LOGGER.error("Failed to invoke contract subgraph: %s", error)
        raise error
    return result


async def _ainvoke_compiled_graph(
    compiled_graph: AsyncInvokableGraph,
    subgraph_input: StateMapping,
    *,
    config: RunnableConfig | None = None,
) -> StateMapping:
    if config is not None and _call_accepts_config(compiled_graph.ainvoke):
        result = await compiled_graph.ainvoke(subgraph_input, config=config)
    else:
        result = await compiled_graph.ainvoke(subgraph_input)
    if not isinstance(result, Mapping):
        error = TypeError(
            f"compiled graph returned unsupported type: {type(result).__name__}"
        )
        LOGGER.error("Failed to invoke contract subgraph: %s", error)
        raise error
    return result


def _call_accepts_config(callable_obj: Callable[..., object]) -> bool:
    try:
        parameters = inspect.signature(callable_obj).parameters
    except (TypeError, ValueError):
        return False
    return "config" in parameters or any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    )


def _execution_input(
    contract: Contract,
    state: StateMapping,
) -> dict[str, object]:
    execution_input: dict[str, object] = {}
    for policy in contract.execution_input_policies:
        execution_input = _merge_mappings(execution_input, policy.project(state))
    return execution_input


def _node_execution_input(
    contract: Contract,
    state: StateMapping,
    *,
    pass_through_state: bool,
    tracker: ReadTracker | None,
) -> StateMapping:
    execution_input = state if pass_through_state else _execution_input(contract, state)
    if tracker is None:
        return execution_input
    return ReadTrackingMapping(execution_input, tracker)


def _warn_undeclared_reads(
    contract: Contract,
    tracker: ReadTracker | None,
) -> None:
    if tracker is None:
        return

    undeclared_paths = _undeclared_read_paths(contract, tracker.paths())
    if not undeclared_paths:
        return

    LOGGER.warning(
        "Contract %r read undeclared state paths: %s",
        contract.label,
        ", ".join(undeclared_paths),
    )


def _undeclared_read_paths(
    contract: Contract,
    observed_paths: tuple[str, ...],
) -> tuple[str, ...]:
    return tuple(
        path_text
        for path_text in observed_paths
        if not any(
            _path_allowed_by_policy(split_path(path_text), policy)
            for policy in contract.execution_input_policies
        )
    )


def _path_allowed_by_policy(path: Path, policy: ProjectionPolicy) -> bool:
    include_paths = (
        None
        if policy.include is None
        else tuple(split_path(path_text) for path_text in policy.include)
    )
    included = include_paths is None or any(
        is_prefix(allowed_path, path) or is_prefix(path, allowed_path)
        for allowed_path in include_paths
    )
    if not included:
        return False

    exclude_paths = tuple(split_path(path_text) for path_text in policy.exclude)
    return not any(
        is_prefix(excluded_path, path) or is_prefix(path, excluded_path)
        for excluded_path in exclude_paths
    )


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


def _top_level_fields(
    policies: tuple[ProjectionPolicy, ...],
) -> dict[str, type[object]]:
    fields: dict[str, type[object]] = {}
    for policy in policies:
        if policy.include is None:
            raise ValueError("open-ended projection cannot be represented")
        for path_text in policy.include:
            key = path_text.split(".", maxsplit=1)[0]
            fields[key] = object
    return fields


def _schema_name(name: str) -> str:
    return "".join(part.capitalize() for part in name.replace("-", "_").split("_"))


__all__ = [
    "AsyncInvokableGraph",
    "ContractNodeDecorator",
    "InvokableGraph",
    "NodeBuilder",
    "add_contract_node",
    "contract_node",
    "contract_subgraph",
    "langgraph_input_schema",
]
