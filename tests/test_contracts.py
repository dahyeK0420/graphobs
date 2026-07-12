from __future__ import annotations

import logging
from typing import cast

import pytest

from graphobs.contracts.models import (
    Contract,
    ContractViolationAction,
    NodeContract,
    ProjectionPolicy,
    StateContractError,
    SubgraphContract,
)
from graphobs.contracts.projection import (
    PayloadObservation,
    observe_payload,
    project_input,
    project_output,
)
from graphobs.contracts.validation import (
    enforce_undeclared_reads,
    validate_update,
)
from graphobs.state.paths import state_diff
from graphobs.state.read_tracking import ReadTracker


def test_node_contract_exposes_contract_interface() -> None:
    contract: Contract = NodeContract(
        name="classify",
        reads=("request.text",),
        writes=("classification.label",),
        private_reads=("scratch.step",),
        private_writes=("scratch.step",),
    )

    assert contract.label == "classify"
    assert contract.input_policy.project(
        {"request": {"text": "hello", "raw": "ignored"}}
    ) == {"request": {"text": "hello"}}
    assert contract.output_policy.project(
        {"classification": {"label": "greeting", "score": 0.9}}
    ) == {"classification": {"label": "greeting"}}
    assert [policy.include for policy in contract.execution_input_policies] == [
        ("request.text",),
        ("scratch.step",),
    ]
    assert [policy.include for policy in contract.write_policies] == [
        ("classification.label",),
        ("scratch.step",),
    ]
    assert not hasattr(contract, "reads")
    assert not hasattr(contract, "writes")


def test_subgraph_contract_exposes_contract_interface() -> None:
    contract: Contract = SubgraphContract(
        parent_input=("request.text",),
        parent_output=("answer.text",),
        private_state_keys=("scratch",),
        owner_namespace="answer_subgraph",
        cleanup_writes=("temporary",),
    )

    assert contract.label == "answer_subgraph"
    assert contract.input_policy.project(
        {"request": {"text": "hello", "raw": "ignored"}}
    ) == {"request": {"text": "hello"}}
    assert contract.output_policy.project(
        {"answer": {"text": "done", "debug": "ignored"}}
    ) == {"answer": {"text": "done"}}
    assert [policy.include for policy in contract.execution_input_policies] == [
        ("request.text",),
        ("scratch",),
    ]
    assert [policy.include for policy in contract.write_policies] == [
        ("answer.text",),
        ("scratch",),
        ("temporary",),
    ]
    assert not hasattr(contract, "parent_input")
    assert not hasattr(contract, "parent_output")


def test_node_projects_public_reads_only() -> None:
    contract = NodeContract(
        name="classify",
        reads=("request.text", "context.locale"),
        private_reads=("scratch.notes",),
    )
    state = {
        "request": {"text": "hello", "raw": "ignored"},
        "context": {"locale": "en", "debug": True},
        "scratch": {"notes": "private"},
    }

    assert project_input(contract, state) == {
        "request": {"text": "hello"},
        "context": {"locale": "en"},
    }


def test_node_projects_changed_public_writes_only() -> None:
    contract = NodeContract(
        name="answer",
        writes=("answer.text", "answer.confidence", "unchanged"),
        private_writes=("scratch.trace",),
    )
    before_state = {
        "answer": {"text": "old", "confidence": 0.3},
        "unchanged": "same",
        "scratch": {"trace": "before"},
    }
    after_state = {
        "answer": {"text": "new", "confidence": 0.3, "extra": "ignored"},
        "unchanged": "same",
        "scratch": {"trace": "after"},
    }

    assert project_output(contract, before_state, after_state) == {
        "answer": {"text": "new"}
    }


def test_observe_payload_projects_input_or_output() -> None:
    contract = NodeContract(
        name="answer",
        reads=("request.text",),
        writes=("answer.text",),
    )

    assert observe_payload(
        contract,
        {"request": {"text": "hello", "raw": "hidden"}},
        "input",
    ) == {"request": {"text": "hello"}}
    assert observe_payload(
        contract,
        {"answer": {"text": "done", "debug": "hidden"}},
        "output",
    ) == {"answer": {"text": "done"}}


def test_observe_payload_can_fall_back_to_summary(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="graphobs.contracts")
    contract = cast(Contract, ContractWithFailingPolicies())
    payload = {"request": {"text": "hello", "raw": "hidden"}}

    assert observe_payload(
        contract,
        payload,
        "input",
        observation=PayloadObservation(fallback_to_summary=True),
    ) == {"input_summary": {"type": "mapping", "size": 1, "keys": ["request"]}}
    assert caplog.records[0].levelno == logging.WARNING
    assert (
        "Could not project input payload for contract failing; "
        "using compact summary after RuntimeError: synthetic projection failure"
    ) in caplog.messages
    assert "hidden" not in caplog.text


def test_observe_payload_raises_projection_errors_by_default() -> None:
    contract = cast(Contract, ContractWithFailingPolicies())

    with pytest.raises(RuntimeError, match="synthetic projection failure"):
        observe_payload(contract, {"request": "hello"}, "input")


def test_state_diff_reports_changed_after_state_paths_only() -> None:
    assert state_diff(
        {"answer": {"text": "old", "score": 1}, "removed": "before"},
        {"answer": {"text": "new", "score": 1}, "added": "after"},
    ) == {"answer": {"text": "new"}, "added": "after"}


def test_validate_update_allows_public_and_private_writes() -> None:
    contract = NodeContract(
        name="retrieve",
        writes=("documents",),
        private_writes=("scratch.query_plan",),
    )

    validate_update(
        contract,
        {
            "documents": [{"title": "Example"}],
            "scratch": {"query_plan": {"terms": ["example"]}},
        },
    )


def test_validate_update_rejects_undeclared_public_writes() -> None:
    contract = NodeContract(name="retrieve", writes=("documents",))

    with pytest.raises(StateContractError) as error:
        validate_update(
            contract,
            {"documents": [], "score": 0.9, "debug": {"enabled": True}},
        )

    assert error.value.contract_name == "retrieve"
    assert error.value.undeclared_paths == ("debug.enabled", "score")
    assert "0.9" not in str(error.value)


def test_validate_update_logs_hard_error_with_original_message(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.ERROR, logger="graphobs.contracts")
    contract = NodeContract(name="retrieve", writes=("documents",))

    with pytest.raises(StateContractError) as error:
        validate_update(contract, {"debug": {"enabled": True}})

    assert caplog.records[0].levelno == logging.ERROR
    assert caplog.messages == [str(error.value)]


def test_validate_update_can_warn_and_continue(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="graphobs.contracts")
    contract = NodeContract(name="retrieve", writes=("documents",))
    expected_error = StateContractError("retrieve", ("debug.enabled",))

    validate_update(
        contract,
        {"debug": {"enabled": True}},
        on_violation=ContractViolationAction.WARN,
    )

    assert caplog.records[0].levelno == logging.WARNING
    assert caplog.messages == [str(expected_error)]


def test_enforce_undeclared_reads_ignores_missing_tracker() -> None:
    contract = NodeContract(name="audited", reads=("request.text",), writes=())

    enforce_undeclared_reads(contract, None)


def test_enforce_undeclared_reads_raises_by_default() -> None:
    contract = NodeContract(name="audited", reads=("request.text",), writes=())
    tracker = ReadTracker()
    tracker.record(("context", "extra"))
    tracker.record(("request", "raw"))

    with pytest.raises(StateContractError) as error:
        enforce_undeclared_reads(contract, tracker)

    assert error.value.access == "read"
    assert error.value.undeclared_paths == ("context.extra", "request.raw")


def test_enforce_undeclared_reads_warns_and_continues(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="graphobs.contracts")
    contract = NodeContract(name="audited", reads=("request.text",), writes=())
    tracker = ReadTracker()
    tracker.record(("context", "extra"))
    tracker.record(("request", "raw"))

    enforce_undeclared_reads(
        contract,
        tracker,
        on_violation=ContractViolationAction.WARN,
    )

    assert caplog.messages == [
        "Contract 'audited' read undeclared state paths: context.extra, request.raw"
    ]


def test_projection_policy_excludes_and_summarizes_nested_state() -> None:
    policy = ProjectionPolicy(
        include=("request", "documents", "blob", "optional"),
        exclude=("request.raw",),
        summarize=("documents", "blob", "optional"),
    )
    state = {
        "request": {"text": "find notes", "raw": "large raw payload"},
        "documents": [
            {"title": "A"},
            {"title": "B"},
        ],
        "blob": b"large bytes",
        "optional": None,
        "scratch": {"ignored": True},
    }

    assert policy.project(state) == {
        "request": {"text": "find notes"},
        "documents": {"type": "sequence", "size": 2},
        "blob": {"type": "bytes", "length": 11},
        "optional": {"type": "none"},
    }


def test_projection_policy_can_project_all_except_excluded_paths() -> None:
    policy = ProjectionPolicy(exclude=("scratch",))

    assert policy.project({"public": "yes", "scratch": "hidden"}) == {"public": "yes"}


def test_subgraph_public_projection_excludes_private_state() -> None:
    contract = SubgraphContract(
        parent_input=("request.text",),
        parent_output=("answer.text",),
        private_state_keys=("scratch",),
        owner_namespace="retrieval_subgraph",
        cleanup_writes=("scratch",),
    )
    before_state = {
        "request": {"text": "hello"},
        "answer": {"text": "old"},
        "scratch": {"step": 1},
    }
    after_state = {
        "request": {"text": "hello"},
        "answer": {"text": "new", "debug": "ignored"},
        "scratch": {"step": 2},
    }

    assert project_input(contract, after_state) == {"request": {"text": "hello"}}
    assert project_output(contract, before_state, after_state) == {
        "answer": {"text": "new"}
    }


def test_subgraph_validate_update_allows_cleanup_and_private_writes() -> None:
    contract = SubgraphContract(
        parent_input=("request",),
        parent_output=("answer",),
        private_state_keys=("scratch",),
        owner_namespace="worker_subgraph",
        cleanup_writes=("temporary",),
    )

    validate_update(
        contract,
        {
            "answer": {"text": "done"},
            "scratch": {"step": "complete"},
            "temporary": None,
        },
    )


def test_subgraph_validate_update_rejects_undeclared_writes() -> None:
    contract = SubgraphContract(
        parent_input=("request",),
        parent_output=("answer",),
        private_state_keys=("scratch",),
        owner_namespace="worker_subgraph",
        cleanup_writes=("temporary",),
    )

    with pytest.raises(StateContractError) as error:
        validate_update(contract, {"answer": "done", "metrics": {"count": 1}})

    assert error.value.contract_name == "worker_subgraph"
    assert error.value.undeclared_paths == ("metrics.count",)


class FailingProjectionPolicy:
    def project(self, state: object) -> dict[str, object]:
        raise RuntimeError("synthetic projection failure")


class ContractWithFailingPolicies:
    label = "failing"
    input_policy = FailingProjectionPolicy()
    output_policy = FailingProjectionPolicy()
    execution_input_policies = (ProjectionPolicy(include=("request.text",)),)
    write_policies = (ProjectionPolicy(include=("answer.text",)),)
