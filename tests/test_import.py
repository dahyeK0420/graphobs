from __future__ import annotations

import graph_observability_kit


def test_package_imports() -> None:
    assert graph_observability_kit.__version__ == "0.1.0"


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


def test_deep_apis_remain_available_from_submodules() -> None:
    from graph_observability_kit.contracts import (
        Contract,
        ProjectionPolicy,
        StateContractError,
        SubgraphContract,
        project_input,
        project_output,
        state_diff,
        validate_update,
    )
    from graph_observability_kit.langgraph import (
        AsyncInvokableGraph,
        InvokableGraph,
        NodeBuilder,
        contract_subgraph,
        langgraph_input_schema,
    )
    from graph_observability_kit.logging import (
        CorrelationFields,
        GraphLogCallback,
        LogContext,
    )
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

    assert AsyncInvokableGraph.__name__ == "AsyncInvokableGraph"
    assert Contract.__name__ == "Contract"
    assert CorrelationFields.__name__ == "CorrelationFields"
    assert GraphLogCallback.__name__ == "GraphLogCallback"
    assert InvokableGraph.__name__ == "InvokableGraph"
    assert LogContext.__name__ == "LogContext"
    assert NodeBuilder.__name__ == "NodeBuilder"
    assert PayloadSerializer.__name__ == "PayloadSerializer"
    assert ProjectionPolicy.__name__ == "ProjectionPolicy"
    assert issubclass(StateContractError, ValueError)
    assert SubgraphContract.__name__ == "SubgraphContract"
    assert TracePayloadMode.COMPACT.value == "compact"
    assert callable(contract_subgraph)
    assert callable(default_payload_serializer)
    assert callable(langgraph_input_schema)
    assert callable(mark_span_error)
    assert callable(project_input)
    assert callable(project_output)
    assert callable(set_span_attributes)
    assert callable(set_span_input)
    assert callable(set_span_output)
    assert callable(state_diff)
    assert callable(start_graph_span)
    assert callable(validate_update)


def test_removed_names_are_not_available_from_package_root() -> None:
    removed_names = (
        "Contract",
        "CorrelationFields",
        "GraphLogCallback",
        "ProjectionPolicy",
        "StateContractError",
        "SubgraphContract",
        "TracePayloadMode",
        "project_input",
        "start_graph_span",
        "state_diff",
    )

    assert all(not hasattr(graph_observability_kit, name) for name in removed_names)
