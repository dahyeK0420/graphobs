"""LangGraph integration helpers for contract-wrapped graph execution."""

from __future__ import annotations

import inspect
import logging
import typing
from collections.abc import Awaitable, Callable, Mapping, MutableMapping
from functools import wraps
from typing import Any, Protocol, TypeAlias, cast, overload

from graph_observability_kit._state_paths import StateMapping, StateUpdate, state_diff
from graph_observability_kit.contracts import (
    Contract,
    NodeContract,
    ProjectionPolicy,
    SubgraphContract,
    project_input,
    project_output,
    validate_update,
)
from graph_observability_kit.tracing import (
    mark_span_error,
    set_span_input,
    set_span_output,
    start_graph_span,
)

LOGGER = logging.getLogger(__name__)
DEFAULT_SPAN_KIND = "CHAIN"

NodeFunction: TypeAlias = Callable[[StateMapping], StateUpdate]
AsyncNodeFunction: TypeAlias = Callable[[StateMapping], Awaitable[StateUpdate]]
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
def contract_node(contract: NodeContract, /) -> ContractNodeDecorator: ...


@overload
def contract_node(fn: NodeFunction, contract: NodeContract) -> NodeFunction: ...


@overload
def contract_node(
    fn: AsyncNodeFunction, contract: NodeContract
) -> AsyncNodeFunction: ...


def contract_node(
    fn: NodeWrapper | NodeContract,
    contract: NodeContract | None = None,
) -> NodeWrapper | ContractNodeDecorator:
    """Wraps a LangGraph node with contract projection, validation, and tracing.

    The wrapped node receives only declared public reads plus declared private
    reads. The emitted span input and output remain public-contract projections.
    The helper can be called as ``contract_node(fn, contract)`` or used as a
    decorator with ``@contract_node(contract)``.

    Args:
        fn: Node function to wrap, or a contract when used as a decorator.
        contract: Node state and trace contract for explicit wrapping.

    Returns:
        A callable with the same sync or async execution style as the original
        node, or a decorator that creates such a callable.

    Raises:
        TypeError: If called with an unsupported argument shape.
    """
    if isinstance(fn, NodeContract) and contract is None:
        decorator_contract = fn

        def decorator(node_fn: NodeWrapper) -> NodeWrapper:
            return _wrap_contract_node(node_fn, decorator_contract)

        return cast(ContractNodeDecorator, decorator)

    if callable(fn) and isinstance(contract, NodeContract):
        return _wrap_contract_node(fn, contract)

    error = TypeError(
        "contract_node expects (fn, contract) or (contract) for decorator use"
    )
    LOGGER.error("Failed to prepare contract node wrapper: %s", error)
    raise error


def _wrap_contract_node(fn: NodeWrapper, contract: NodeContract) -> NodeWrapper:
    if inspect.iscoroutinefunction(fn):
        async_fn = cast(AsyncNodeFunction, fn)

        @wraps(async_fn)
        async def async_wrapper(state: StateMapping) -> StateUpdate:
            with start_graph_span(
                contract.label,
                contract.span_kind or DEFAULT_SPAN_KIND,
                attributes=_node_attributes(contract),
            ) as span:
                try:
                    public_input = project_input(contract, state)
                    set_span_input(span, public_input)
                    update = await async_fn(_execution_input(contract, state))
                    validate_update(contract, update)
                    set_span_output(span, project_output(contract, {}, update))
                    return update
                except Exception as exc:
                    LOGGER.error("Contract node %s failed: %s", contract.label, exc)
                    mark_span_error(span, exc)
                    raise

        return async_wrapper

    sync_fn = cast(NodeFunction, fn)

    @wraps(sync_fn)
    def sync_wrapper(state: StateMapping) -> StateUpdate:
        with start_graph_span(
            contract.label,
            contract.span_kind or DEFAULT_SPAN_KIND,
            attributes=_node_attributes(contract),
        ) as span:
            try:
                public_input = project_input(contract, state)
                set_span_input(span, public_input)
                update = sync_fn(_execution_input(contract, state))
                validate_update(contract, update)
                set_span_output(span, project_output(contract, {}, update))
                return update
            except Exception as exc:
                LOGGER.error("Contract node %s failed: %s", contract.label, exc)
                mark_span_error(span, exc)
                raise

    return sync_wrapper


@overload
def contract_subgraph(
    compiled_graph: InvokableGraph,
    contract: SubgraphContract,
) -> NodeFunction: ...


@overload
def contract_subgraph(
    compiled_graph: AsyncInvokableGraph,
    contract: SubgraphContract,
) -> AsyncNodeFunction: ...


def contract_subgraph(
    compiled_graph: InvokableGraph | AsyncInvokableGraph,
    contract: SubgraphContract,
) -> NodeWrapper:
    """Wraps a compiled LangGraph subgraph with parent-boundary contracts.

    The subgraph receives only declared parent input plus declared private state
    keys. The wrapper returns only declared parent output changes.

    Args:
        compiled_graph: Compiled graph object with ``invoke``.
        contract: Subgraph parent boundary contract.

    Returns:
        A node callable suitable for ``StateGraph.add_node``.
    """
    if hasattr(compiled_graph, "ainvoke") and not hasattr(compiled_graph, "invoke"):
        return _contract_async_subgraph(compiled_graph, contract)
    return _contract_sync_subgraph(cast(InvokableGraph, compiled_graph), contract)


def _contract_sync_subgraph(
    compiled_graph: InvokableGraph,
    contract: SubgraphContract,
) -> NodeFunction:
    def wrapper(state: StateMapping) -> StateUpdate:
        with start_graph_span(
            contract.label,
            DEFAULT_SPAN_KIND,
            attributes={"graph.subgraph": contract.label},
        ) as span:
            try:
                public_input = project_input(contract, state)
                set_span_input(span, public_input)
                subgraph_input = _execution_input(contract, state)
                after_state = _invoke_compiled_graph(compiled_graph, subgraph_input)
                changed_update = state_diff(subgraph_input, after_state)
                validate_update(contract, changed_update)
                public_output = project_output(contract, subgraph_input, after_state)
                set_span_output(span, public_output)
                return public_output
            except Exception as exc:
                LOGGER.error(
                    "Contract subgraph %s failed: %s",
                    contract.label,
                    exc,
                )
                mark_span_error(span, exc)
                raise

    return wrapper


def _contract_async_subgraph(
    compiled_graph: AsyncInvokableGraph,
    contract: SubgraphContract,
) -> AsyncNodeFunction:
    async def wrapper(state: StateMapping) -> StateUpdate:
        with start_graph_span(
            contract.label,
            DEFAULT_SPAN_KIND,
            attributes={"graph.subgraph": contract.label},
        ) as span:
            try:
                public_input = project_input(contract, state)
                set_span_input(span, public_input)
                subgraph_input = _execution_input(contract, state)
                after_state = await _ainvoke_compiled_graph(
                    compiled_graph,
                    subgraph_input,
                )
                changed_update = state_diff(subgraph_input, after_state)
                validate_update(contract, changed_update)
                public_output = project_output(contract, subgraph_input, after_state)
                set_span_output(span, public_output)
                return public_output
            except Exception as exc:
                LOGGER.error(
                    "Contract subgraph %s failed: %s",
                    contract.label,
                    exc,
                )
                mark_span_error(span, exc)
                raise

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
) -> object:
    """Adds a contract-wrapped node to a LangGraph ``StateGraph`` builder.

    Args:
        graph: Graph builder exposing ``add_node``.
        contract: Node state and trace contract.
        fn: Synchronous or asynchronous node function.

    Returns:
        The graph builder returned by ``add_node``.
    """
    wrapped = contract_node(fn, contract)
    input_schema = langgraph_input_schema(contract)

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
) -> StateMapping:
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
) -> StateMapping:
    result = await compiled_graph.ainvoke(subgraph_input)
    if not isinstance(result, Mapping):
        error = TypeError(
            f"compiled graph returned unsupported type: {type(result).__name__}"
        )
        LOGGER.error("Failed to invoke contract subgraph: %s", error)
        raise error
    return result


def _execution_input(
    contract: Contract,
    state: StateMapping,
) -> dict[str, object]:
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
