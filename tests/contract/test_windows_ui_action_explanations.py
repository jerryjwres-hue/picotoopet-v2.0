from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DESKTOP = ROOT / "windows" / "desktop" / "src" / "PicotooPet.Desktop"
PAGES = DESKTOP / "Views" / "Pages"
VIEW_MODELS = DESKTOP / "ViewModels"


# Helpers ---------------------------------------------------------------------
def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


# Approval page ---------------------------------------------------------------
def test_approval_actions_disable_while_busy_and_explain_unavailable_states() -> None:
    xaml = _read(PAGES / "ApprovalsPage.xaml")
    view_model = _read(VIEW_MODELS / "ApprovalsPageViewModel.cs")

    for required in (
        'IsEnabled="{Binding CanRefresh, Mode=OneWay}"',
        'ToolTip="{Binding RefreshActionReason, Mode=OneWay}"',
        'ToolTip="{Binding ApproveActionReason, Mode=OneWay}"',
        'ToolTip="{Binding RejectActionReason, Mode=OneWay}"',
    ):
        assert required in xaml

    for required in (
        "public bool CanRefresh",
        "public string RefreshActionReason",
        "public string ApproveActionReason",
        "public string RejectActionReason",
        "请先选择一项审批。",
        "请填写本次决策原因。",
        "审批操作正在处理中，请稍候。",
    ):
        assert required in view_model


# Automation page -------------------------------------------------------------
def test_automation_actions_prevent_duplicate_clicks_and_explain_state() -> None:
    xaml = _read(PAGES / "AutomationPage.xaml")
    view_model = _read(VIEW_MODELS / "AutomationPageViewModel.cs")

    for required in (
        'IsEnabled="{Binding CanRefresh, Mode=OneWay}"',
        'IsEnabled="{Binding CanCreateSafeWorkflow, Mode=OneWay}"',
        'ToolTip="{Binding RefreshActionReason, Mode=OneWay}"',
        'ToolTip="{Binding CreateActionReason, Mode=OneWay}"',
        'ToolTip="{Binding ReconcileActionReason, Mode=OneWay}"',
        'ToolTip="{Binding PauseActionReason, Mode=OneWay}"',
        'ToolTip="{Binding ResumeActionReason, Mode=OneWay}"',
        'ToolTip="{Binding CancelActionReason, Mode=OneWay}"',
    ):
        assert required in xaml

    for required in (
        "public bool CanRefresh",
        "public bool CanCreateSafeWorkflow",
        "public string RefreshActionReason",
        "public string CreateActionReason",
        "public string ReconcileActionReason",
        "public string PauseActionReason",
        "public string ResumeActionReason",
        "public string CancelActionReason",
        "请先选择一个工作流。",
        "工作流操作正在处理中，请稍候。",
    ):
        assert required in view_model


# Projects page ---------------------------------------------------------------
def test_project_actions_validate_input_before_click_and_explain_archive_state() -> None:
    xaml = _read(PAGES / "ProjectsPage.xaml")
    view_model = _read(VIEW_MODELS / "ProjectsPageViewModel.cs")

    for required in (
        'IsEnabled="{Binding CanCreate, Mode=OneWay}"',
        'IsEnabled="{Binding CanRefresh, Mode=OneWay}"',
        'ToolTip="{Binding CreateActionReason, Mode=OneWay}"',
        'ToolTip="{Binding RefreshActionReason, Mode=OneWay}"',
        'ToolTip="{Binding ArchiveActionReason, Mode=OneWay}"',
    ):
        assert required in xaml

    for required in (
        "public bool CanCreate",
        "public bool CanRefresh",
        "public string CreateActionReason",
        "public string RefreshActionReason",
        "public string ArchiveActionReason",
        "项目标题、类型和来源不能为空。",
        "请先选择项目。",
        "项目操作正在处理中，请稍候。",
    ):
        assert required in view_model
