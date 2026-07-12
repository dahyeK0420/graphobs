from __future__ import annotations

import re
from pathlib import Path

REFERENCE_DIR = Path(__file__).resolve().parents[1] / "docs" / "reference"

EXPECTED_REFERENCE_TARGETS = {
    "callbacks.md": ("graphobs.langgraph.callbacks",),
    "contracts.md": (
        "graphobs.contracts.models",
        "graphobs.contracts.projection",
        "graphobs.contracts.conformance",
        "graphobs.state.paths",
    ),
    "demo.md": (
        "graphobs.demo.tracing_setup",
        "graphobs.demo.span_records",
    ),
    "langgraph.md": (
        "graphobs.langgraph.nodes",
        "graphobs.langgraph.subgraphs",
        "graphobs.langgraph.schemas",
    ),
    "logging.md": (
        "graphobs.logging.context",
        "graphobs.logging.callback",
        "graphobs.logging.invoke_config",
    ),
    "package.md": ("graphobs",),
    "payloads.md": ("graphobs.payloads",),
    "tracing.md": ("graphobs.tracing",),
}

REFERENCE_DIRECTIVE_RE = re.compile(r"^:::\s+(graphobs\S*)", re.M)


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
                if target.startswith("graphobs._")
            )
        )
    }

    assert private_targets == {}
