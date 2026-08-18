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


def test_goal_center_delivery_branch_is_covered_by_installable_ui_preview() -> None:
    workflow = _read(PREVIEW)

    # Goal Center 改动必须在自己的交付分支上自动构建可安装 Preview；
    # 不能依赖旧 UI polish 分支，也不能改用 Full release 绕过 Natural Motion 资产门。
    assert "feature/autonomous-intelligence-e2e-goal-center-2.3.27.1" in workflow
    assert "-ValidationScope UiPreview" in workflow


def test_release_builder_uses_published_version_surface_self_test_contract() -> None:
    builder = _read(BUILDER)

    # 发布 EXE 已在 AppSelfTest 内把 Shell 文案与 ProductVersionInfo 做同源比较。
    # 外层打包器继续严格比较产品版本和窗口标题，但不再复制一份可能过期的副标题常量。
    assert '[string]$selfTest.checks.product_version_surfaces -ne "pass"' in builder
    assert '[string]$selfTest.product_version -ne $ProductVersion' in builder
    assert '[string]$selfTest.window_title -ne "Picotoo Pet AI $ProductVersion"' in builder
    assert '[string]$selfTest.control_center_subtitle -ne "Control Center · v$ProductVersion"' not in builder


def test_ui_preview_publishes_auditable_run_provenance_to_source_commit() -> None:
    workflow = _read(PREVIEW)

    # 一启动先发布 pending + run ID，结束再覆盖为 success/failure；
    # 这样源码 commit 在整个验收周期都能追溯到唯一 Preview run。
    for required in (
        "statuses: write",
        "actions/github-script@v8",
        "github.rest.repos.createCommitStatus",
        "windows-ui-preview-release",
        "context.runId",
        "context.sha",
        "state: 'pending'",
        "Preview run ${context.runId} started",
        "if: always()",
    ):
        assert required in workflow
