"""Contract for the branch-scoped one-shot native package dispatcher."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/phase10c-one-shot-native-package-dispatch.yml"
BRANCH = "feature/phase10c-event-stream-recovery"


def test_one_shot_dispatcher_is_branch_scoped_and_actions_write_only() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert f'github.ref == "refs/heads/{BRANCH}"' in source
    assert f'github.repository == "jerryjwres-hue/picotoopet-v2.0"' in source
    assert "actions: write" in source
    assert "contents: read" in source
    assert "workflow_dispatch" not in source


def test_one_shot_dispatcher_targets_all_native_delivery_gates() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    for workflow in (
        "windows-control-center-ci.yml",
        "windows-phase2-release.yml",
        "macos-core-slice-b-ci.yml",
        "macos-worker-slice-c-ci.yml",
    ):
        assert workflow in source

    assert source.count("runner_target=windows-2025") == 2
    assert source.count("runner_target=macos-15") == 2
    assert '--ref "$REF"' in source
