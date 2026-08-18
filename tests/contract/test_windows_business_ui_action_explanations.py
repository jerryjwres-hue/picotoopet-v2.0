from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DESKTOP = ROOT / "windows" / "desktop" / "src" / "PicotooPet.Desktop"
PAGE = DESKTOP / "Views" / "Pages" / "BusinessAutomationPage.xaml"
VIEW_MODEL = DESKTOP / "ViewModels" / "BusinessAutomationPageViewModel.cs"


# Helpers ---------------------------------------------------------------------
def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


# Business actions ------------------------------------------------------------
def test_business_actions_disable_while_busy_and_explain_unavailable_states() -> None:
    xaml = _read(PAGE)
    view_model = _read(VIEW_MODEL)

    for required in (
        'IsEnabled="{Binding CanRefresh, Mode=OneWay}"',
        'IsEnabled="{Binding CanSubmitInbox, Mode=OneWay}"',
        'ToolTip="{Binding RefreshActionReason, Mode=OneWay}"',
        'ToolTip="{Binding SubmitInboxActionReason, Mode=OneWay}"',
        'ToolTip="{Binding DeliverResultActionReason, Mode=OneWay}"',
        'ToolTip="{Binding CancelActionReason, Mode=OneWay}"',
        'ToolTip="{Binding ExportHandoffActionReason, Mode=OneWay}"',
        'ToolTipService.ShowOnDisabled="True"',
    ):
        assert required in xaml

    for required in (
        "public bool CanRefresh",
        "public bool CanSubmitInbox",
        "public string RefreshActionReason",
        "public string SubmitInboxActionReason",
        "public string DeliverResultActionReason",
        "public string CancelActionReason",
        "public string ExportHandoffActionReason",
        "请先选择业务包。",
        "业务操作正在处理中，请稍候。",
    ):
        assert required in view_model
