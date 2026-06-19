from __future__ import annotations

import logging
from typing import Any, TypedDict, cast

import pytest
from langgraph.graph import END, START, StateGraph

from graph_observability_kit.contracts.models import (
    Contract,
    NodeContract,
    ProjectionPolicy,
)
from graph_observability_kit.langgraph.callbacks import (
    ProjectedCallbackHandler,
    ProjectionStats,
    project_callback_payloads,
)
from graph_observability_kit.payloads import shape_summary

LARGE_VALUE = "do not expose this full callback value " * 20


class ExampleState(TypedDict, total=False):
    request: dict[str, object]
    answer: dict[str, object]


def test_project_callback_payloads_projects_iterable_contract_by_label() -> None:
    callback = _RecordingCallback()
    contract = NodeContract(
        name="answer",
        reads=("request.text",),
        writes=("answer.text",),
    )
    wrapper = project_callback_payloads(callback, [contract])

    wrapper.on_chain_start(
        {"name": "answer"},
        {"request": {"text": "hello", "raw": LARGE_VALUE}},
        run_id="node-run",
        metadata={"langgraph_node": "answer"},
    )
    wrapper.on_chain_end(
        {"answer": {"text": "done", "raw": LARGE_VALUE}},
        run_id="node-run",
    )

    assert isinstance(wrapper, ProjectedCallbackHandler)
    # Projected payload is further compacted via message_compact_summary:
    # non-message scalar strings become shape summaries.
    assert callback.events[0]["inputs"] == {
        "request": {"text": {"type": "str", "length": 5}}
    }
    assert callback.events[1]["outputs"] == {
        "answer": {"text": {"type": "str", "length": 4}}
    }
    assert LARGE_VALUE not in str(callback.events)


def test_project_callback_payloads_supports_explicit_graph_node_alias() -> None:
    callback = _RecordingCallback()
    contract = NodeContract(
        name="contract_label",
        reads=("request.text",),
        writes=("answer.text",),
    )
    wrapper = project_callback_payloads(callback, {"graph_node": contract})

    wrapper.on_chain_start(
        {"name": "graph_node"},
        {"request": {"text": "hello", "raw": LARGE_VALUE}},
        run_id="alias-run",
        metadata={"langgraph_node": "graph_node"},
    )
    wrapper.on_chain_end(
        {"answer": {"text": "done", "debug": LARGE_VALUE}},
        run_id="alias-run",
    )

    # message_compact_summary compacts scalar strings to shape summaries.
    str_5 = {"type": "str", "length": 5}
    str_4 = {"type": "str", "length": 4}
    assert callback.events[0]["inputs"] == {"request": {"text": str_5}}
    assert callback.events[1]["outputs"] == {"answer": {"text": str_4}}
    assert LARGE_VALUE not in str(callback.events)


def test_unknown_and_root_graph_events_pass_through_unchanged() -> None:
    callback = _RecordingCallback()
    contract = NodeContract(
        name="answer",
        reads=("request.text",),
        writes=("answer.text",),
    )
    wrapper = project_callback_payloads(callback, [contract])
    inputs = {"request": {"text": "hello", "raw": LARGE_VALUE}}
    outputs = {"answer": {"text": "done", "raw": LARGE_VALUE}}

    wrapper.on_chain_start(
        {"name": "root"},
        inputs,
        run_id="root-run",
        metadata={"graph": "root"},
    )
    wrapper.on_chain_end(outputs, run_id="root-run")
    wrapper.on_chain_start(
        {"name": "unknown"},
        inputs,
        run_id="unknown-run",
        metadata={"langgraph_node": "unknown"},
    )

    assert callback.events[0]["inputs"] is inputs
    assert callback.events[1]["outputs"] is outputs
    assert callback.events[2]["inputs"] is inputs


def test_projection_stats_report_matched_unmatched_and_missing_contracts(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(
        logging.DEBUG,
        logger="graph_observability_kit.langgraph.callbacks",
    )
    callback = _RecordingCallback()
    answer_contract = NodeContract(
        name="answer",
        reads=("request.text",),
        writes=("answer.text",),
    )
    missing_contract = NodeContract(
        name="missing",
        reads=("request.text",),
        writes=("answer.text",),
    )
    wrapper = project_callback_payloads(
        callback,
        [answer_contract, missing_contract],
        diagnostics=True,
    )

    wrapper.on_chain_start(
        {"name": "root"},
        {"request": {"text": "hello"}},
        run_id="root-run",
        metadata={"graph": "root"},
    )
    wrapper.on_chain_start(
        {"name": "answer"},
        {"request": {"text": "hello"}},
        run_id="answer-run",
        metadata={"langgraph_node": "answer"},
    )
    wrapper.on_chain_start(
        {"name": "unknown"},
        {"request": {"text": "hello"}},
        run_id="unknown-run",
        metadata={"langgraph_node": "unknown"},
    )

    stats = wrapper.projection_stats()

    assert isinstance(stats, ProjectionStats)
    assert stats.expected_contracts == ("answer", "missing")
    assert stats.observed_nodes == ("answer", "unknown")
    assert stats.matched_nodes == ("answer",)
    assert stats.unmatched_nodes == ("unknown",)
    assert stats.missing_contracts == ("missing",)
    assert "Observed LangGraph node callback: answer" in caplog.text
    assert "Projected callback payloads for LangGraph node: answer" in caplog.text
    assert (
        "No callback projection contract matched LangGraph node: unknown" in caplog.text
    )


def test_projection_failure_warns_and_uses_compact_summary(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    callback = _RecordingCallback()
    contract = cast(Contract, _FailingContract())
    wrapper = project_callback_payloads(callback, {"failing": contract})
    inputs = {"request": {"text": LARGE_VALUE}}
    outputs = {"answer": {"text": LARGE_VALUE}}

    wrapper.on_chain_start(
        {"name": "failing"},
        inputs,
        run_id="failing-run",
        metadata={"langgraph_node": "failing"},
    )
    wrapper.on_chain_end(outputs, run_id="failing-run")

    assert callback.events[0]["inputs"] == {"input_summary": shape_summary(inputs)}
    assert callback.events[1]["outputs"] == {"output_summary": shape_summary(outputs)}
    assert [record.levelno for record in caplog.records] == [
        logging.WARNING,
        logging.WARNING,
    ]
    assert "Could not project input payload for contract failing" in caplog.text
    assert "Could not project output payload for contract failing" in caplog.text
    assert "synthetic projection failure" in caplog.text
    assert LARGE_VALUE not in caplog.text
    assert LARGE_VALUE not in str(callback.events)


def test_chain_error_clears_remembered_projection_state() -> None:
    callback = _RecordingCallback()
    contract = NodeContract(
        name="answer",
        reads=("request.text",),
        writes=("answer.text",),
    )
    wrapper = project_callback_payloads(callback, [contract])
    outputs = {"answer": {"text": "done", "raw": LARGE_VALUE}}

    wrapper.on_chain_start(
        {"name": "answer"},
        {"request": {"text": "hello", "raw": LARGE_VALUE}},
        run_id="error-run",
        metadata={"langgraph_node": "answer"},
    )
    wrapper.on_chain_error(RuntimeError("synthetic failure"), run_id="error-run")
    wrapper.on_chain_end(outputs, run_id="error-run")

    assert callback.events[1]["event"] == "error"
    assert callback.events[2]["outputs"] is outputs


def test_langgraph_node_events_receive_projected_payloads() -> None:
    callback = _RecordingCallback()
    contract = NodeContract(
        name="answer",
        reads=("request.text",),
        writes=("answer.text",),
    )

    def answer(state: ExampleState) -> ExampleState:
        return {"answer": {"text": str(state["request"]["text"])}}

    graph = StateGraph(ExampleState)
    graph.add_node("answer", answer)
    graph.add_edge(START, "answer")
    graph.add_edge("answer", END)
    config = {"callbacks": [project_callback_payloads(callback, [contract])]}

    result = graph.compile().invoke(
        {"request": {"text": "hello", "raw": LARGE_VALUE}},
        config=cast(Any, config),
    )

    node_start = next(
        event
        for event in callback.events
        if event["event"] == "start"
        and isinstance(event["metadata"], dict)
        and event["metadata"].get("langgraph_node") == "answer"
    )
    node_run_id = node_start["run_id"]
    node_end = next(
        event
        for event in callback.events
        if event["event"] == "end" and event["run_id"] == node_run_id
    )

    assert result["answer"] == {"text": "hello"}
    # message_compact_summary compacts string values to shape summaries.
    assert node_start["inputs"] == {"request": {"text": {"type": "str", "length": 5}}}
    assert node_end["outputs"] == {"answer": {"text": {"type": "str", "length": 5}}}
    assert LARGE_VALUE not in str(node_start)
    assert LARGE_VALUE not in str(node_end)


def test_projected_messages_are_compacted_to_role_and_content() -> None:
    callback = _RecordingCallback()
    contract = NodeContract(
        name="chat",
        reads=("messages",),
        writes=("messages",),
    )
    wrapper = project_callback_payloads(callback, [contract])

    class _Msg:
        def __init__(self, msg_type: str, content: str) -> None:
            self.type = msg_type
            self.content = content

    messages = [_Msg("human", "hello"), _Msg("ai", "world")]

    wrapper.on_chain_start(
        {"name": "chat"},
        {"messages": messages, "extra": "drop me"},
        run_id="chat-run",
        metadata={"langgraph_node": "chat"},
    )

    inputs = callback.events[0]["inputs"]
    assert isinstance(inputs, dict)
    compacted = inputs["messages"]
    assert compacted == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "world"},
    ]


class _RecordingCallback:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def on_chain_start(
        self,
        serialized: dict[str, object] | None,
        inputs: object,
        *,
        run_id: object,
        parent_run_id: object | None = None,
        tags: object = None,
        metadata: object = None,
        **kwargs: object,
    ) -> None:
        self.events.append(
            {
                "event": "start",
                "serialized": serialized,
                "inputs": inputs,
                "run_id": run_id,
                "parent_run_id": parent_run_id,
                "tags": tags,
                "metadata": metadata,
                "kwargs": kwargs,
            }
        )

    def on_chain_end(
        self,
        outputs: object,
        *,
        run_id: object,
        parent_run_id: object | None = None,
        **kwargs: object,
    ) -> None:
        self.events.append(
            {
                "event": "end",
                "outputs": outputs,
                "run_id": run_id,
                "parent_run_id": parent_run_id,
                "kwargs": kwargs,
            }
        )

    def on_chain_error(
        self,
        error: BaseException,
        *,
        run_id: object,
        parent_run_id: object | None = None,
        **kwargs: object,
    ) -> None:
        self.events.append(
            {
                "event": "error",
                "error_type": type(error).__name__,
                "run_id": run_id,
                "parent_run_id": parent_run_id,
                "kwargs": kwargs,
            }
        )


class _FailingPolicy:
    def project(self, state: object) -> dict[str, object]:
        raise RuntimeError("synthetic projection failure")


class _FailingContract:
    label = "failing"
    input_policy = _FailingPolicy()
    output_policy = _FailingPolicy()
    execution_input_policies = (ProjectionPolicy(include=("request.text",)),)
    write_policies = (ProjectionPolicy(include=("answer.text",)),)
