"""Callback payload projection helpers for LangGraph node events."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import TypeAlias

from graph_observability_kit._observability.payload_policy import (
    PayloadKind,
    project_contract_payload,
)
from graph_observability_kit.contracts.models import Contract

LOGGER = logging.getLogger("graph_observability_kit.langgraph.callbacks")
LANGGRAPH_NODE_METADATA_KEY = "langgraph_node"

Metadata: TypeAlias = Mapping[str, object]
ContractSource: TypeAlias = Mapping[str, Contract] | Iterable[Contract]


@dataclass(frozen=True)
class _MatchedContract:
    contract: Contract


@dataclass(frozen=True)
class ProjectionStats:
    """Snapshot of callback projection matching diagnostics.

    Attributes:
        expected_contracts: Contract keys supplied to the wrapper.
        observed_nodes: LangGraph node names observed in callback metadata.
        matched_nodes: Observed node names that matched a contract.
        unmatched_nodes: Observed node names without a matching contract.
        missing_contracts: Contract keys not matched by any observed node.
    """

    expected_contracts: tuple[str, ...]
    observed_nodes: tuple[str, ...]
    matched_nodes: tuple[str, ...]
    unmatched_nodes: tuple[str, ...]
    missing_contracts: tuple[str, ...]


def project_callback_payloads(
    callback: object,
    contracts: ContractSource,
    *,
    diagnostics: bool = False,
) -> ProjectedCallbackHandler:
    """Wraps a callback so matched LangGraph node payloads are projected.

    The wrapper matches chain events by ``metadata["langgraph_node"]``.
    Iterable contract sources are keyed by ``contract.label``. Mapping sources
    are keyed by their explicit graph node names, which supports aliases when a
    LangGraph node name differs from the contract label.

    Unknown events, including root graph events without ``langgraph_node``
    metadata, are forwarded unchanged.

    Args:
        callback: Downstream callback object to receive projected events.
        contracts: Contract iterable or explicit graph-node-name mapping.
        diagnostics: Whether to log debug messages for observed, matched, and
            unmatched LangGraph node names.

    Returns:
        A callback wrapper that delegates to ``callback``.
    """
    return ProjectedCallbackHandler(callback, contracts, diagnostics=diagnostics)


class ProjectedCallbackHandler:
    """Projects matched chain callback payloads before delegating.

    Contract node wrappers curate the input passed into the wrapped node and
    the kit spans emitted around that node. LangGraph callback handlers may
    still observe the outer graph payload for node lifecycle events. This
    wrapper narrows matched ``on_chain_start`` and ``on_chain_end`` payloads
    with the same contract policies before a downstream callback sees them.
    """

    def __init__(
        self,
        callback: object,
        contracts: ContractSource,
        *,
        diagnostics: bool = False,
    ) -> None:
        """Creates a projection wrapper for one downstream callback.

        Args:
            callback: Callback object to delegate events to.
            contracts: Contract iterable keyed by ``contract.label`` or an
                explicit mapping keyed by LangGraph node name.
            diagnostics: Whether to log debug messages for projection matching.
        """
        self.callback = callback
        self.contracts = _contract_mapping(contracts)
        self.diagnostics = diagnostics
        self._contracts_by_run_id: dict[str, _MatchedContract] = {}
        self._observed_nodes: dict[str, None] = {}
        self._matched_nodes: dict[str, None] = {}
        self._unmatched_nodes: dict[str, None] = {}

    @property
    def raise_error(self) -> bool:
        """Whether callback errors should propagate through LangChain."""
        return bool(getattr(self.callback, "raise_error", False))

    @property
    def run_inline(self) -> bool:
        """Whether LangChain should run this callback inline."""
        return bool(getattr(self.callback, "run_inline", False))

    @property
    def ignore_chain(self) -> bool:
        """Whether LangChain should skip chain events for this callback."""
        return bool(getattr(self.callback, "ignore_chain", False))

    @property
    def ignore_tool(self) -> bool:
        """Whether LangChain should skip tool events for this callback."""
        return bool(getattr(self.callback, "ignore_tool", False))

    @property
    def ignore_llm(self) -> bool:
        """Whether LangChain should skip LLM events for this callback."""
        return bool(getattr(self.callback, "ignore_llm", False))

    @property
    def ignore_retry(self) -> bool:
        """Whether LangChain should skip retry events for this callback."""
        return bool(getattr(self.callback, "ignore_retry", False))

    @property
    def ignore_agent(self) -> bool:
        """Whether LangChain should skip agent events for this callback."""
        return bool(getattr(self.callback, "ignore_agent", False))

    @property
    def ignore_retriever(self) -> bool:
        """Whether LangChain should skip retriever events for this callback."""
        return bool(getattr(self.callback, "ignore_retriever", False))

    @property
    def ignore_chat_model(self) -> bool:
        """Whether LangChain should skip chat model events for this callback."""
        return bool(getattr(self.callback, "ignore_chat_model", False))

    @property
    def ignore_custom_event(self) -> bool:
        """Whether LangChain should skip custom events for this callback."""
        return bool(getattr(self.callback, "ignore_custom_event", False))

    def __getattr__(self, name: str) -> object:
        """Delegates unimplemented callback methods and attributes."""
        return getattr(self.callback, name)

    def projection_stats(self) -> ProjectionStats:
        """Returns observed callback projection match statistics."""
        expected_contracts = tuple(self.contracts)
        matched_nodes = tuple(self._matched_nodes)
        return ProjectionStats(
            expected_contracts=expected_contracts,
            observed_nodes=tuple(self._observed_nodes),
            matched_nodes=matched_nodes,
            unmatched_nodes=tuple(self._unmatched_nodes),
            missing_contracts=tuple(
                contract_name
                for contract_name in expected_contracts
                if contract_name not in self._matched_nodes
            ),
        )

    def on_chain_start(
        self,
        serialized: Mapping[str, object] | None,
        inputs: Mapping[str, object],
        *,
        run_id: object,
        parent_run_id: object | None = None,
        tags: Sequence[str] | None = None,
        metadata: Metadata | None = None,
        **kwargs: object,
    ) -> None:
        """Projects matched node inputs before forwarding chain start."""
        node_name = _langgraph_node(metadata)
        projected_inputs: Mapping[str, object] = inputs
        if node_name is not None:
            self._observe_node(node_name)
            contract = self.contracts.get(node_name)
            if contract is not None:
                self._match_node(node_name)
                self._contracts_by_run_id[_run_key(run_id)] = _MatchedContract(
                    contract,
                )
                projected_inputs = _project_or_summarize(
                    contract,
                    inputs,
                    payload_kind="input",
                )
            else:
                self._miss_node(node_name)

        _call_callback_method(
            self.callback,
            "on_chain_start",
            serialized,
            projected_inputs,
            run_id=run_id,
            parent_run_id=parent_run_id,
            tags=tags,
            metadata=metadata,
            **kwargs,
        )

    def on_chain_end(
        self,
        outputs: Mapping[str, object],
        *,
        run_id: object,
        parent_run_id: object | None = None,
        **kwargs: object,
    ) -> None:
        """Projects remembered node outputs before forwarding chain end."""
        matched_contract = self._contracts_by_run_id.pop(_run_key(run_id), None)
        projected_outputs: Mapping[str, object] = outputs
        if matched_contract is not None:
            projected_outputs = _project_or_summarize(
                matched_contract.contract,
                outputs,
                payload_kind="output",
            )

        _call_callback_method(
            self.callback,
            "on_chain_end",
            projected_outputs,
            run_id=run_id,
            parent_run_id=parent_run_id,
            **kwargs,
        )

    def on_chain_error(
        self,
        error: BaseException,
        *,
        run_id: object,
        parent_run_id: object | None = None,
        **kwargs: object,
    ) -> None:
        """Forwards chain errors and clears remembered projection state."""
        self._contracts_by_run_id.pop(_run_key(run_id), None)
        _call_callback_method(
            self.callback,
            "on_chain_error",
            error,
            run_id=run_id,
            parent_run_id=parent_run_id,
            **kwargs,
        )

    def _observe_node(self, node_name: str) -> None:
        _remember(self._observed_nodes, node_name)
        if self.diagnostics:
            LOGGER.debug("Observed LangGraph node callback: %s", node_name)

    def _match_node(self, node_name: str) -> None:
        _remember(self._matched_nodes, node_name)
        if self.diagnostics:
            LOGGER.debug(
                "Projected callback payloads for LangGraph node: %s",
                node_name,
            )

    def _miss_node(self, node_name: str) -> None:
        _remember(self._unmatched_nodes, node_name)
        if self.diagnostics:
            LOGGER.debug(
                "No callback projection contract matched LangGraph node: %s",
                node_name,
            )


def _contract_mapping(contracts: ContractSource) -> dict[str, Contract]:
    if isinstance(contracts, Mapping):
        return dict(contracts)
    return {contract.label: contract for contract in contracts}


def _remember(target: dict[str, None], value: str) -> None:
    target[value] = None


def _langgraph_node(metadata: Metadata | None) -> str | None:
    if metadata is None:
        return None
    node_name = metadata.get(LANGGRAPH_NODE_METADATA_KEY)
    if node_name is None:
        return None
    return str(node_name)


def _project_or_summarize(
    contract: Contract,
    payload: Mapping[str, object],
    *,
    payload_kind: PayloadKind,
) -> Mapping[str, object]:
    policy = (
        contract.input_policy if payload_kind == "input" else contract.output_policy
    )
    return project_contract_payload(
        contract_label=contract.label,
        payload=payload,
        payload_kind=payload_kind,
        project=policy.project,
        logger=LOGGER,
        fallback_to_summary=True,
        compact_projected=True,
    )


def _call_callback_method(
    callback: object,
    method_name: str,
    *args: object,
    **kwargs: object,
) -> None:
    method = getattr(callback, method_name, None)
    if callable(method):
        method(*args, **kwargs)


def _run_key(run_id: object) -> str:
    return str(run_id)


__all__ = [
    "ProjectedCallbackHandler",
    "ProjectionStats",
    "project_callback_payloads",
]
