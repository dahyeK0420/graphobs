from __future__ import annotations

import importlib.util
from collections.abc import Sequence
from types import ModuleType

import pytest

import graph_observability_kit
import graph_observability_kit.contracts.models as models
import graph_observability_kit.contracts.projection as projection
import graph_observability_kit.contracts.validation as validation
import graph_observability_kit.demo.span_records as span_records
import graph_observability_kit.demo.tracing_setup as tracing_setup
import graph_observability_kit.discovery.draft as draft
import graph_observability_kit.discovery.runner as runner
import graph_observability_kit.langgraph.callbacks as callbacks
import graph_observability_kit.langgraph.nodes as nodes
import graph_observability_kit.langgraph.schemas as schemas
import graph_observability_kit.langgraph.subgraphs as subgraphs
import graph_observability_kit.logging.callback as callback
import graph_observability_kit.logging.context as context
import graph_observability_kit.logging.invoke_config as invoke_config
import graph_observability_kit.state.paths as paths
from graph_observability_kit import payloads, tracing


def test_package_imports() -> None:
    assert graph_observability_kit.__version__ == "0.2.0"


@pytest.mark.parametrize(
    "module_name",
    [
        "graph_observability_kit._instrumented_execution",
        "graph_observability_kit._read_tracking",
        "graph_observability_kit._state_paths",
        "graph_observability_kit.callbacks",
    ],
)
def test_obsolete_shim_modules_are_removed(module_name: str) -> None:
    assert importlib.util.find_spec(module_name) is None


def test_package_root_exports_headline_interface_only() -> None:
    from graph_observability_kit import (
        NodeContract,
        add_contract_node,
        build_invoke_config,
        contract_node,
    )

    assert graph_observability_kit.__all__ == [
        "NodeContract",
        "__version__",
        "add_contract_node",
        "build_invoke_config",
        "contract_node",
    ]
    assert NodeContract.__name__ == "NodeContract"
    assert callable(add_contract_node)
    assert callable(build_invoke_config)
    assert callable(contract_node)


@pytest.mark.parametrize(
    ("module", "expected_exports"),
    [
        (
            graph_observability_kit,
            [
                "NodeContract",
                "__version__",
                "add_contract_node",
                "build_invoke_config",
                "contract_node",
            ],
        ),
        (
            models,
            [
                "AttributeValue",
                "Contract",
                "ContractViolationAction",
                "NodeContract",
                "ProjectionPolicy",
                "ProjectionSpec",
                "StateContractError",
                "SubgraphContract",
            ],
        ),
        (
            projection,
            [
                "ContractProjection",
                "ProjectionPolicyLike",
                "project_input",
                "project_node_payload",
                "project_output",
                "project_state",
            ],
        ),
        (validation, ["validate_update"]),
        (
            paths,
            [
                "Path",
                "StateMapping",
                "StateUpdate",
                "delete_path",
                "get_path",
                "is_prefix",
                "iter_update_paths",
                "join_path",
                "normalize_optional_paths",
                "normalize_paths",
                "set_path",
                "split_path",
                "state_diff",
            ],
        ),
        (
            nodes,
            [
                "AsyncNodeFunction",
                "ContractNodeDecorator",
                "NodeBuilder",
                "NodeFunction",
                "NodeWrapper",
                "add_contract_node",
                "contract_node",
            ],
        ),
        (
            subgraphs,
            ["AsyncInvokableGraph", "InvokableGraph", "contract_subgraph"],
        ),
        (schemas, ["TypedDictFactory", "langgraph_input_schema"]),
        (
            callbacks,
            [
                "ProjectedCallbackHandler",
                "ProjectionStats",
                "project_callback_payloads",
            ],
        ),
        (
            context,
            [
                "CorrelationFields",
                "CorrelationValue",
                "LogContext",
                "Metadata",
                "field_names",
            ],
        ),
        (callback, ["GraphLogCallback"]),
        (invoke_config, ["InvokeConfig", "build_invoke_config"]),
        (draft, ["DiscoveredContract"]),
        (
            runner,
            [
                "AsyncDiscoveryNode",
                "ContractDiscoveryError",
                "SyncDiscoveryNode",
                "adiscover_contract",
                "discover_contract",
            ],
        ),
        (
            tracing_setup,
            [
                "configure_local_tracing",
                "configure_otlp_tracing",
                "configure_phoenix_tracing",
            ],
        ),
        (span_records, ["span_record", "span_records"]),
        (payloads, ["message_compact_summary", "shape_summary"]),
        (
            tracing,
            [
                "PayloadSerializer",
                "TracePayloadMode",
                "default_payload_serializer",
                "mark_span_error",
                "set_span_attributes",
                "set_span_input",
                "set_span_output",
                "start_graph_span",
            ],
        ),
    ],
)
def test_public_module_exports_are_stable(
    module: ModuleType,
    expected_exports: Sequence[str],
) -> None:
    assert module.__all__ == list(expected_exports)


def test_concrete_public_modules_expose_expected_objects() -> None:
    from graph_observability_kit.contracts.models import (
        Contract,
        ContractViolationAction,
        ProjectionPolicy,
        StateContractError,
        SubgraphContract,
    )
    from graph_observability_kit.contracts.projection import (
        project_input,
        project_node_payload,
        project_output,
    )
    from graph_observability_kit.contracts.validation import validate_update
    from graph_observability_kit.discovery.draft import DiscoveredContract
    from graph_observability_kit.discovery.runner import (
        ContractDiscoveryError,
        adiscover_contract,
        discover_contract,
    )
    from graph_observability_kit.langgraph.callbacks import (
        ProjectedCallbackHandler,
        ProjectionStats,
        project_callback_payloads,
    )
    from graph_observability_kit.langgraph.nodes import NodeBuilder
    from graph_observability_kit.langgraph.schemas import langgraph_input_schema
    from graph_observability_kit.langgraph.subgraphs import (
        InvokableGraph,
        contract_subgraph,
    )
    from graph_observability_kit.logging.callback import GraphLogCallback
    from graph_observability_kit.logging.context import CorrelationFields, LogContext
    from graph_observability_kit.payloads import shape_summary
    from graph_observability_kit.state.paths import state_diff
    from graph_observability_kit.tracing import (
        PayloadSerializer,
        TracePayloadMode,
        default_payload_serializer,
        mark_span_error,
        set_span_attributes,
        set_span_input,
        set_span_output,
        start_graph_span,
    )

    assert Contract.__name__ == "Contract"
    assert ContractDiscoveryError.__name__ == "ContractDiscoveryError"
    assert ContractViolationAction.WARN.value == "warn"
    assert CorrelationFields.__name__ == "CorrelationFields"
    assert DiscoveredContract.__name__ == "DiscoveredContract"
    assert GraphLogCallback.__name__ == "GraphLogCallback"
    assert InvokableGraph.__name__ == "InvokableGraph"
    assert LogContext.__name__ == "LogContext"
    assert NodeBuilder.__name__ == "NodeBuilder"
    assert PayloadSerializer.__name__ == "PayloadSerializer"
    assert ProjectionStats.__name__ == "ProjectionStats"
    assert ProjectedCallbackHandler.__name__ == "ProjectedCallbackHandler"
    assert ProjectionPolicy.__name__ == "ProjectionPolicy"
    assert issubclass(StateContractError, ValueError)
    assert SubgraphContract.__name__ == "SubgraphContract"
    assert TracePayloadMode.COMPACT.value == "compact"
    assert callable(adiscover_contract)
    assert callable(contract_subgraph)
    assert callable(default_payload_serializer)
    assert callable(discover_contract)
    assert callable(langgraph_input_schema)
    assert callable(mark_span_error)
    assert callable(project_callback_payloads)
    assert callable(project_input)
    assert callable(project_node_payload)
    assert callable(project_output)
    assert callable(set_span_attributes)
    assert callable(set_span_input)
    assert callable(set_span_output)
    assert callable(shape_summary)
    assert callable(state_diff)
    assert callable(start_graph_span)
    assert callable(validate_update)


def test_removed_names_are_not_available_from_package_root() -> None:
    removed_names = (
        "Contract",
        "ContractViolationAction",
        "ContractDiscoveryError",
        "CorrelationFields",
        "DiscoveredContract",
        "GraphLogCallback",
        "ProjectionPolicy",
        "ProjectionStats",
        "ProjectedCallbackHandler",
        "StateContractError",
        "SubgraphContract",
        "TracePayloadMode",
        "adiscover_contract",
        "discover_contract",
        "project_callback_payloads",
        "project_input",
        "project_node_payload",
        "shape_summary",
        "start_graph_span",
        "state_diff",
    )

    assert all(not hasattr(graph_observability_kit, name) for name in removed_names)
