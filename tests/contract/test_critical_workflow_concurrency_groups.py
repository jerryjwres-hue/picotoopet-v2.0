"""Critical native workflows must keep distinct groups and stable runners."""

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
NATIVE_RUNNER_MARKERS = {
    "windows-control-center-ci.yml": "'windows-2025'",
    "windows-phase2-release.yml": "'windows-2025'",
    "macos-core-slice-b-ci.yml": "runner: macos-15",
    "macos-worker-slice-c-ci.yml": "'macos-15'",
}


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


def test_critical_native_workflows_use_stable_impact_runner() -> None:
    for workflow in WORKFLOWS:
        source = workflow.read_text(encoding="utf-8")
        match = re.search(
            r"(?ms)^  impact:\n.*?^    runs-on:\s*([^\s]+)\s*$",
            source,
        )
        assert match is not None, f"{workflow.name} must declare impact runs-on"
        assert match.group(1) == "ubuntu-22.04"


def test_native_platform_runner_labels_are_unchanged() -> None:
    for workflow in WORKFLOWS:
        source = workflow.read_text(encoding="utf-8")
        assert NATIVE_RUNNER_MARKERS[workflow.name] in source
