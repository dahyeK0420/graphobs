from __future__ import annotations

import re
from pathlib import Path

REFERENCE_DIR = Path(__file__).resolve().parents[1] / "docs" / "reference"

EXPECTED_REFERENCE_TARGETS = {
    "callbacks.md": ("graph_observability_kit.langgraph.callbacks",),
    "contracts.md": (
        "graph_observability_kit.contracts.models",
        "graph_observability_kit.contracts.projection",
        "graph_observability_kit.contracts.validation",
        "graph_observability_kit.state.paths",
    ),
    "demo.md": (
        "graph_observability_kit.demo.tracing_setup",
        "graph_observability_kit.demo.span_records",
    ),
    "discovery.md": (
        "graph_observability_kit.discovery.draft",
        "graph_observability_kit.discovery.runner",
    ),
    "langgraph.md": (
        "graph_observability_kit.langgraph.nodes",
        "graph_observability_kit.langgraph.subgraphs",
        "graph_observability_kit.langgraph.schemas",
    ),
    "logging.md": (
        "graph_observability_kit.logging.context",
        "graph_observability_kit.logging.callback",
        "graph_observability_kit.logging.invoke_config",
    ),
    "package.md": ("graph_observability_kit",),
    "payloads.md": ("graph_observability_kit.payloads",),
    "tracing.md": ("graph_observability_kit.tracing",),
}

REFERENCE_DIRECTIVE_RE = re.compile(r"^:::\s+(graph_observability_kit\S*)", re.M)


def test_reference_pages_target_public_implementation_modules() -> None:
    actual_targets = {
        path.name: tuple(REFERENCE_DIRECTIVE_RE.findall(path.read_text()))
        for path in sorted(REFERENCE_DIR.glob("*.md"))
        if path.name != "index.md"
    }

    assert actual_targets == EXPECTED_REFERENCE_TARGETS


def test_reference_pages_do_not_target_private_modules() -> None:
    private_targets = {
        path.name: targets
        for path in sorted(REFERENCE_DIR.glob("*.md"))
        if (
            targets := tuple(
                target
                for target in REFERENCE_DIRECTIVE_RE.findall(path.read_text())
                if target.startswith("graph_observability_kit._")
            )
        )
    }

    assert private_targets == {}
