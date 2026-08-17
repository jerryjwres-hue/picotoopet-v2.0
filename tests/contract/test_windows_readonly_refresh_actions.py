from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DESKTOP = ROOT / "windows" / "desktop" / "src" / "PicotooPet.Desktop"
PAGES = DESKTOP / "Views" / "Pages"
VIEW_MODELS = DESKTOP / "ViewModels"


# Helpers ---------------------------------------------------------------------
def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


# Read-only refresh pages ------------------------------------------------------
def test_diagnostics_refresh_disables_while_busy_and_explains_state() -> None:
    xaml = _read(PAGES / "DiagnosticsPage.xaml")
    view_model = _read(VIEW_MODELS / "DiagnosticsPageViewModel.cs")

    for required in (
        'IsEnabled="{Binding CanRefresh, Mode=OneWay}"',
        'ToolTip="{Binding RefreshActionReason, Mode=OneWay}"',
        'ToolTipService.ShowOnDisabled="True"',
    ):
        assert required in xaml

    for required in (
        "public bool CanRefresh",
        "public string RefreshActionReason",
        "诊断事实正在刷新，请稍候。",
    ):
        assert required in view_model


def test_health_refresh_disables_while_busy_and_explains_state() -> None:
    xaml = _read(PAGES / "HealthPage.xaml")
    view_model = _read(VIEW_MODELS / "HealthPageViewModel.cs")

    for required in (
        'IsEnabled="{Binding CanRefresh, Mode=OneWay}"',
        'ToolTip="{Binding RefreshActionReason, Mode=OneWay}"',
        'ToolTipService.ShowOnDisabled="True"',
    ):
        assert required in xaml

    for required in (
        "public bool CanRefresh",
        "public string RefreshActionReason",
        "健康快照正在刷新，请稍候。",
    ):
        assert required in view_model
