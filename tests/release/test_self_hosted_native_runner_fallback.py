from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

WORKFLOWS = {
    ".github/workflows/windows-control-center-ci.yml": (
        "picotoopet-windows-release",
        "windows-2025",
    ),
    ".github/workflows/windows-phase2-release.yml": (
        "picotoopet-windows-release",
        "windows-2025",
    ),
    ".github/workflows/macos-core-slice-b-ci.yml": (
        "picotoopet-macos-arm64-release",
        "macos-15",
    ),
    ".github/workflows/macos-worker-slice-c-ci.yml": (
        "picotoopet-macos-arm64-release",
        "macos-15",
    ),
}


def test_manual_dispatch_defaults_to_self_hosted_native_runners() -> None:
    """GitHub-hosted quota exhaustion must not block controlled native release gates."""

    for relative, (self_hosted, github_hosted) in WORKFLOWS.items():
        source = (ROOT / relative).read_text(encoding="utf-8")

        assert "workflow_dispatch:" in source
        assert "runner_target:" in source
        assert f"default: {self_hosted}" in source
        assert f"- {self_hosted}" in source
        assert f"- {github_hosted}" in source
        assert "github.event_name == 'workflow_dispatch'" in source
        assert "inputs.runner_target" in source


def test_pull_request_native_gates_remain_enabled() -> None:
    """The fallback adds a manual path without weakening normal PR verification."""

    for relative in WORKFLOWS:
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "pull_request:" in source
