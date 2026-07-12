from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping

import pytest

from graphobs.contracts.models import NodeContract
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


def test_discover_contract_tracks_mapping_reads_and_update_writes() -> None:
    def classify(state: Mapping[str, object], *, suffix: str) -> Mapping[str, object]:
        request = state["request"]
        context = state.get("context", {})
        metadata = state["metadata"]
        settings = state["settings"]
        profile = state["profile"]
        flags = state["flags"]
        optional = state.get("optional")

        text = request["text"] if isinstance(request, Mapping) else ""
        locale = context.get("locale", "en") if isinstance(context, Mapping) else "en"
        has_debug = "debug" in state

        if isinstance(metadata, Mapping):
            list(metadata)
        if isinstance(settings, Mapping):
            list(settings.keys())
        if isinstance(profile, Mapping):
            for value in profile.values():
                if isinstance(value, Mapping):
                    value.get("level")
        if isinstance(flags, Mapping):
            list(flags.items())

        return {
            "classification": {"label": f"{text}-{locale}{suffix}"},
            "metrics": {"debug": has_debug, "optional": optional is not None},
        }

    draft = discover_contract(
        classify,
        [
            {
                "request": {"text": "hello", "raw": "ignored"},
                "context": {"locale": "en"},
                "debug": True,
                "metadata": {"source": "synthetic", "priority": 1},
                "settings": {"mode": "test"},
                "profile": {"details": {"level": "basic"}},
                "flags": {"enabled": True, "dry_run": False},
            }
        ],
        name="classify",
        node_kwargs={"suffix": "!"},
    )

    assert isinstance(draft, DiscoveredContract)
    assert draft.name == "classify"
    assert draft.sample_count == 1
    assert draft.reads == (
        "request.text",
        "context.locale",
        "metadata.source",
        "metadata.priority",
        "settings.mode",
        "profile.details.level",
        "flags.enabled",
        "flags.dry_run",
        "optional",
        "debug",
    )
    assert draft.writes == (
        "classification.label",
        "metrics.debug",
        "metrics.optional",
    )


def test_discover_contract_runs_samples_sequentially() -> None:
    observed_steps: list[object] = []

    def record_step(state: Mapping[str, object]) -> Mapping[str, object]:
        observed_steps.append(state["step"])
        return {"result": {"step": state["step"]}}

    draft = discover_contract(
        record_step,
        [{"step": 1}, {"step": 2}],
        name="record_step",
    )

    assert observed_steps == [1, 2]
    assert draft.sample_count == 2
    assert draft.reads == ("step",)
    assert draft.writes == ("result.step",)


def test_adiscover_contract_tracks_async_reads_and_writes() -> None:
    async def answer(state: Mapping[str, object]) -> Mapping[str, object]:
        await asyncio.sleep(0)
        request = state["request"]
        text = request["text"] if isinstance(request, Mapping) else ""
        return {"answer": {"text": text}}

    draft = asyncio.run(
        adiscover_contract(
            answer,
            [{"request": {"text": "hello", "raw": "ignored"}}],
            name="answer",
        )
    )

    assert draft.name == "answer"
    assert draft.reads == ("request.text",)
    assert draft.writes == ("answer.text",)
    assert draft.sample_count == 1


def test_discovered_contract_private_overrides_move_overlapping_paths() -> None:
    draft = DiscoveredContract(
        name="draft",
        reads=("request.text", "scratch.notes"),
        writes=("answer.text", "scratch.notes"),
        sample_count=1,
    )

    contract = draft.to_node_contract(
        private_reads=("scratch",),
        private_writes=("scratch.notes",),
    )

    assert contract.label == "draft"
    assert contract.input_policy.include == ("request.text",)
    assert contract.output_policy.include == ("answer.text",)
    assert contract.execution_input_policies[1].include == ("scratch",)
    assert contract.write_policies[1].include == ("scratch.notes",)


def test_discovery_failure_logs_error_and_preserves_original_exception(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.ERROR, logger="graphobs.discovery")

    def failing_node(state: Mapping[str, object]) -> Mapping[str, object]:
        raise RuntimeError(f"synthetic failure for {state['request']}")

    with pytest.raises(ContractDiscoveryError) as error:
        discover_contract(
            failing_node,
            [{"request": "sample"}],
            name="failing_node",
        )

    assert error.value.node_name == "failing_node"
    assert error.value.sample_index == 0
    assert isinstance(error.value.__cause__, RuntimeError)
    assert caplog.records[0].levelno == logging.ERROR
    assert "Contract discovery for node failing_node failed on sample 0" in caplog.text
    assert "synthetic failure for sample" in caplog.text


def test_discovery_rejects_non_mapping_updates() -> None:
    def invalid_node(state: Mapping[str, object]) -> Mapping[str, object]:
        state["request"]
        return "not an update"  # type: ignore[return-value]

    with pytest.raises(ContractDiscoveryError) as error:
        discover_contract(
            invalid_node,
            [{"request": "sample"}],
            name="invalid_node",
        )

    assert isinstance(error.value.__cause__, TypeError)
    assert "unsupported update type" in str(error.value)


def test_assert_contract_matches_returns_draft_when_within_contract() -> None:
    def classify(state: Mapping[str, object]) -> Mapping[str, object]:
        request = state["request"]
        text = request["text"] if isinstance(request, Mapping) else ""
        return {"classification": {"label": str(text)}}

    contract = NodeContract(
        name="classify",
        reads=("request.text",),
        writes=("classification.label",),
    )

    draft = assert_contract_matches(
        classify,
        contract,
        [{"request": {"text": "hello", "raw": "ignored"}}],
    )

    assert draft.name == "classify"
    assert draft.reads == ("request.text",)
    assert draft.writes == ("classification.label",)


def test_assert_contract_matches_detects_undeclared_read() -> None:
    def classify(state: Mapping[str, object]) -> Mapping[str, object]:
        request = state["request"]
        secret = state["secret"]
        return {"classification": {"label": f"{request}-{secret}"}}

    contract = NodeContract(
        name="classify",
        reads=("request",),
        writes=("classification.label",),
    )

    with pytest.raises(ContractDriftError) as error:
        assert_contract_matches(
            classify,
            contract,
            [{"request": {"text": "hi"}, "secret": "token"}],
        )

    assert error.value.node_name == "classify"
    assert error.value.undeclared_reads == ("secret",)
    assert error.value.undeclared_writes == ()


def test_assert_contract_matches_detects_undeclared_write() -> None:
    def classify(state: Mapping[str, object]) -> Mapping[str, object]:
        request = state["request"]
        return {
            "classification": {"label": str(request)},
            "debug": {"trace": "unexpected"},
        }

    contract = NodeContract(
        name="classify",
        reads=("request",),
        writes=("classification.label",),
    )

    with pytest.raises(ContractDriftError) as error:
        assert_contract_matches(
            classify,
            contract,
            [{"request": {"text": "hi"}}],
        )

    assert error.value.undeclared_reads == ()
    assert error.value.undeclared_writes == ("debug.trace",)


def test_assert_contract_amatches_detects_drift() -> None:
    async def answer(state: Mapping[str, object]) -> Mapping[str, object]:
        await asyncio.sleep(0)
        request = state["request"]
        return {"answer": {"text": str(request)}, "scratch": {"note": "x"}}

    contract = NodeContract(
        name="answer",
        reads=("request",),
        writes=("answer.text",),
    )

    with pytest.raises(ContractDriftError) as error:
        asyncio.run(
            assert_contract_amatches(
                answer,
                contract,
                [{"request": {"text": "hi"}}],
            )
        )

    assert error.value.undeclared_writes == ("scratch.note",)


def test_contract_drift_error_reports_paths_without_sampled_values(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.ERROR, logger="graphobs.discovery")

    def classify(state: Mapping[str, object]) -> Mapping[str, object]:
        state["request"]
        return {"leak": "secret-value"}

    contract = NodeContract(name="classify", reads=("request",), writes=())

    with pytest.raises(ContractDriftError) as error:
        assert_contract_matches(
            classify,
            contract,
            [{"request": {"text": "secret-value"}}],
        )

    assert error.value.undeclared_writes == ("leak",)
    assert "secret-value" not in str(error.value)
    assert "secret-value" not in caplog.text
    assert caplog.records[0].levelno == logging.ERROR
