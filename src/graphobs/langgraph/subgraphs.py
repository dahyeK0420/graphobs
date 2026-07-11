"""Contract-wrapped LangGraph subgraph helpers."""

from __future__ import annotations

import inspect
import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Protocol, cast, overload

from langchain_core.runnables import RunnableConfig

from graphobs.contracts.models import (
    ContractViolationAction,
    SubgraphContract,
)
from graphobs.langgraph.execution import (
    instrument_contract_arun,
    instrument_contract_run,
    subgraph_contract_run_spec,
)
from graphobs.langgraph.nodes import (
    AsyncNodeFunction,
    NodeFunction,
    NodeWrapper,
)
from graphobs.state.paths import StateMapping, StateUpdate

LOGGER = logging.getLogger("graphobs.langgraph")
DEFAULT_SPAN_KIND = "CHAIN"
_NO_CONFIG: RunnableConfig = cast(RunnableConfig, None)


class InvokableGraph(Protocol):
    """Compiled graph shape required for synchronous subgraph execution."""

    def invoke(self, *args: Any, **kwargs: Any) -> object:
        """Invokes a compiled graph synchronously."""


class AsyncInvokableGraph(Protocol):
    """Compiled graph shape required for asynchronous subgraph execution."""

    def ainvoke(self, *args: Any, **kwargs: Any) -> Awaitable[object]:
        """Invokes a compiled graph asynchronously."""


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

    Reducer safety: parent output paths must map to last-value-wins (overwrite)
    channels. The wrapper cannot see the parent graph's channel reducers, so it
    returns the subgraph's full projected value. Under a non-deduplicating
    accumulating reducer (for example ``Annotated[list, operator.add]``) the
    parent re-applies that value and duplicates the seeded input. Model
    accumulating channels with a node-level ``contract_node`` instead, which
    passes the node's partial update through unchanged.

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

        spec = subgraph_contract_run_spec(
            contract,
            span_kind=DEFAULT_SPAN_KIND,
            attributes={"graph.subgraph": contract.label},
            on_violation=on_violation,
            logger=LOGGER,
        )
        return instrument_contract_run(
            spec,
            state,
            execute=execute,
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

        spec = subgraph_contract_run_spec(
            contract,
            span_kind=DEFAULT_SPAN_KIND,
            attributes={"graph.subgraph": contract.label},
            on_violation=on_violation,
            logger=LOGGER,
        )
        return await instrument_contract_arun(
            spec,
            state,
            execute=execute,
        )

    return wrapper


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


__all__ = ["AsyncInvokableGraph", "InvokableGraph", "contract_subgraph"]
