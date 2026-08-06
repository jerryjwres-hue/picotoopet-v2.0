"""Critical native workflows must not share a GitHub Actions concurrency group."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = (
    ROOT / ".github/workflows/windows-control-center-ci.yml",
    ROOT / ".github/workflows/windows-phase2-release.yml",
    ROOT / ".github/workflows/macos-core-slice-b-ci.yml",
    ROOT / ".github/workflows/macos-worker-slice-c-ci.yml",
)


def test_critical_native_workflows_use_distinct_branch_scoped_groups() -> None:
    groups: dict[str, str] = {}

    for workflow in WORKFLOWS:
        source = workflow.read_text(encoding="utf-8")
        match = re.search(r"(?m)^  group:\s*(.+?)\s*$", source)
        assert match is not None, f"{workflow.name} must declare concurrency.group"

        group = match.group(1)
        assert "${{ github.ref }}" in group
        groups[workflow.name] = group

    assert len(set(groups.values())) == len(groups), groups
