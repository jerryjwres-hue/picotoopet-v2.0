from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DESKTOP = ROOT / "windows" / "desktop"
BUILDER = DESKTOP / "scripts" / "Build-Phase2WindowsRelease.ps1"
PREVIEW = ROOT / ".github" / "workflows" / "windows-ui-preview-release.yml"
FORMAL = ROOT / ".github" / "workflows" / "windows-phase2-release.yml"
RESEARCH_FORMAL = ROOT / ".github" / "workflows" / "research-windows-final-release.yml"


# Helpers ---------------------------------------------------------------------
def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


# Preview isolation -----------------------------------------------------------
def test_ui_preview_builder_is_explicit_and_full_release_remains_default() -> None:
    builder = _read(BUILDER)

    for required in (
        '[ValidateSet("Full", "UiPreview")]',
        '[string]$ValidationScope = "Full"',
        '$ValidationScope -eq "UiPreview"',
        '"--ui-interaction-only"',
        '$validationScopeText = if ($ValidationScope -eq "UiPreview") {',
        '"windows-ui-preview"',
        '$fullRelease = $ValidationScope -eq "Full"',
        'validation_scope      = $validationScopeText',
        'full_release         = $fullRelease',
        'windows-ui-preview-release.yml',
    ):
        assert required in builder

    # 正式构建仍必须默认走完整 Smoke；Preview 只在显式选择时追加 UI-only 参数。
    assert '"run", "--project", $smokeProject, "--configuration", "Release", "--no-build"' in builder
    assert '$smokeArguments += @("--", "--ui-interaction-only")' in builder


def test_formal_release_workflows_never_request_ui_preview_scope() -> None:
    for path in (FORMAL, RESEARCH_FORMAL):
        workflow = _read(path)
        assert "ValidationScope UiPreview" not in workflow
        assert "windows-ui-preview" not in workflow.lower()


def test_ui_preview_workflow_builds_installable_lifecycle_verified_artifact() -> None:
    assert PREVIEW.exists(), "缺少独立 Windows UI Preview workflow"
    workflow = _read(PREVIEW)

    for required in (
        "feature/windows-ui-interaction-polish-2.3.27.1",
        "windows-2025",
        "tests/contract",
        "--ui-interaction-only",
        "-ValidationScope UiPreview",
        "Test-Phase2WindowsRelease.ps1",
        "actions/upload-artifact@v7",
        "PicotooPet-Windows-UI-Preview-2.3.27.1",
        "artifact-sha256.txt",
    ):
        assert required in workflow

    # Preview 只能作为验收包，不能伪装正式发布或跳过生命周期验证。
    assert "windows-phase2-release.yml" not in workflow
    assert "research-windows-final-release.yml" not in workflow
