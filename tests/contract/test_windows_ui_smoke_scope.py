from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROGRAM = ROOT / "windows" / "desktop" / "tests" / "PicotooPet.Desktop.Core.SmokeTests" / "Program.cs"
UI_CI = ROOT / ".github" / "workflows" / "windows-control-center-ci.yml"
FULL_RELEASE = ROOT / ".github" / "workflows" / "windows-phase2-release.yml"
RESEARCH_RELEASE = ROOT / ".github" / "workflows" / "research-windows-final-release.yml"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def test_control_center_ci_has_a_ui_only_smoke_mode() -> None:
    program = _read(PROGRAM)
    workflow = _read(UI_CI)

    assert '"--ui-interaction-only"' in program
    assert "RunUiInteractionOnly" in program
    assert "--ui-interaction-only" in workflow


def test_formal_windows_releases_never_use_ui_only_smoke_mode() -> None:
    for path in (FULL_RELEASE, RESEARCH_RELEASE):
        workflow = _read(path)
        assert "--ui-interaction-only" not in workflow


def test_ui_only_mode_keeps_real_ui_behavior_gates() -> None:
    program = _read(PROGRAM)

    for required in (
        "NavigationSmokeTests.Run();",
        "OperatorSimpleModeSmokeTests.Run();",
        "NavigationFaultBoundarySmokeTests.Run();",
        "NavigationContentRenderingSmokeTests.Run();",
        "ShellNavigationReconnectWpfSmokeTests.Run();",
        "TaskCenterSmokeTests.Run();",
        "ResultsCenterSmokeTests.Run();",
        "ApprovalCenterSmokeTests.Run();",
        "ProductVersionWpfSmokeTests.Run();",
        "TaskCenterWpfLayoutSmokeTests.Run();",
        "ResultsPageWpfLayoutSmokeTests.Run();",
        "ApprovalsPageWpfLayoutSmokeTests.Run();",
    ):
        assert required in program
