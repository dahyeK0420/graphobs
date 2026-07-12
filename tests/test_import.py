from __future__ import annotations

import importlib.util
from collections.abc import Sequence
from types import ModuleType

import pytest

import graphobs
import graphobs.contracts.models as models
import graphobs.contracts.projection as projection
import graphobs.contracts.validation as validation
import graphobs.demo.span_records as span_records
import graphobs.demo.tracing_setup as tracing_setup
import graphobs.discovery.draft as draft
import graphobs.discovery.drift as drift
import graphobs.discovery.runner as runner
import graphobs.langgraph.callbacks as callbacks
import graphobs.langgraph.nodes as nodes
import graphobs.langgraph.schemas as schemas
import graphobs.langgraph.subgraphs as subgraphs
import graphobs.logging.callback as callback
import graphobs.logging.context as context
import graphobs.logging.invoke_config as invoke_config
import graphobs.state.paths as paths
from graphobs import payloads, tracing


def test_package_imports() -> None:
    assert graphobs.__version__ == "0.4.0"


@pytest.mark.parametrize(
    "module_name",
    [
        "graphobs._instrumented_execution",
        "graphobs._read_tracking",
        "graphobs._state_paths",
        "graphobs.callbacks",
    ],
)
def test_obsolete_shim_modules_are_removed(module_name: str) -> None:
    assert importlib.util.find_spec(module_name) is None


def test_package_root_exports_headline_interface_only() -> None:
    from graphobs import (
        NodeContract,
        NodeContractMode,
        add_contract_node,
        add_contract_nodes,
        build_invoke_config,
        contract_node,
    )

    assert graphobs.__all__ == [
        "NodeContract",
        "NodeContractMode",
        "__version__",
        "add_contract_node",
        "add_contract_nodes",
        "build_invoke_config",
        "contract_node",
    ]
    assert NodeContract.__name__ == "NodeContract"
    assert NodeContractMode.ENFORCE.value == "enforce"
    assert callable(add_contract_node)
    assert callable(add_contract_nodes)
    assert callable(build_invoke_config)
    assert callable(contract_node)


@pytest.mark.parametrize(
    ("module", "expected_exports"),
    [
        (
            graphobs,
            [
                "NodeContract",
                "NodeContractMode",
                "__version__",
                "add_contract_node",
                "add_contract_nodes",
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
                "COMPACT_OBSERVATION",
                "STRICT_OBSERVATION",
                "PayloadObservation",
                "observe_payload",
                "project_input",
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
                "NodeContractMode",
                "NodeFunction",
                "NodeWrapper",
                "add_contract_node",
                "add_contract_nodes",
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
            drift,
            [
                "ContractDriftError",
                "assert_contract_amatches",
                "assert_contract_matches",
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
    from graphobs.contracts.models import (
        Contract,
        ContractViolationAction,
        ProjectionPolicy,
        StateContractError,
        SubgraphContract,
    )
    from graphobs.contracts.projection import (
        observe_payload,
        project_input,
        project_output,
    )
    from graphobs.contracts.validation import validate_update
    from graphobs.discovery.draft import DiscoveredContract
    from graphobs.discovery.drift import (
        ContractDriftError,
        assert_contract_amatches,
        assert_contract_matches,
    )
    from graphobs.discovery.runner import (
        ContractDiscoveryError,
        adiscover_contract,
        discover_contract,
    )
    from graphobs.langgraph.callbacks import (
        ProjectedCallbackHandler,
        ProjectionStats,
        project_callback_payloads,
    )
    from graphobs.langgraph.nodes import NodeBuilder
    from graphobs.langgraph.schemas import langgraph_input_schema
    from graphobs.langgraph.subgraphs import (
        InvokableGraph,
        contract_subgraph,
    )
    from graphobs.logging.callback import GraphLogCallback
    from graphobs.logging.context import CorrelationFields, LogContext
    from graphobs.payloads import shape_summary
    from graphobs.state.paths import state_diff
    from graphobs.tracing import (
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
    assert issubclass(ContractDriftError, AssertionError)
    assert callable(assert_contract_amatches)
    assert callable(assert_contract_matches)
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
    assert callable(observe_payload)
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
        "observe_payload",
        "project_callback_payloads",
        "project_input",
        "shape_summary",
        "start_graph_span",
        "state_diff",
    )

    assert all(not hasattr(graphobs, name) for name in removed_names)
