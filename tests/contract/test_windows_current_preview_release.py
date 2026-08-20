from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "windows-ui-preview-release.yml"
CURRENT_PREVIEW_BRANCH = "feature/autonomous-intelligence-e2e-goal-center-2.3.27.1"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def test_current_goal_center_branch_can_build_installable_windows_preview() -> None:
    workflow = _read(WORKFLOW)

    # 当前 Goal Center 集成分支必须能直接产出可安装 Preview，避免要求正式茅台资产 gate 才能做 PC 实机验收。
    assert f"      - {CURRENT_PREVIEW_BRANCH}" in workflow
    assert "-ValidationScope UiPreview" in workflow
    assert "Test-Phase2WindowsRelease.ps1" in workflow
    assert "PicotooPet-Phase2-Windows-Prebuilt-*.zip" in workflow
