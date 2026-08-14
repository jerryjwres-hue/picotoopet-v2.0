from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VERSION = ROOT / "src" / "picotoopet_core" / "product-version.txt"
DESKTOP = ROOT / "windows" / "desktop" / "src" / "PicotooPet.Desktop"
SHELL = DESKTOP / "Views" / "ShellWindow.xaml"
ROUTES = DESKTOP / "Navigation" / "NavigationRoute.cs"
PROJECTION = DESKTOP / "ViewModels" / "OperatorProjection.cs"
EXPERIENCE = DESKTOP / "ViewModels" / "OperatorExperienceModels.cs"
HOME_XAML = DESKTOP / "Views" / "Pages" / "OperatorHomePage.xaml"
WIZARD = DESKTOP / "ViewModels" / "NewTaskWizardViewModel.cs"
WIZARD_XAML = DESKTOP / "Views" / "Pages" / "NewTaskWizardWindow.xaml"


def assert_simple_nav_button(xaml: str, name: str, title: str) -> None:
    """允许产品化按钮使用子元素绘制图标，但固定入口名称必须留在同一 Button 内。"""

    marker = f'x:Name="{name}"'
    start = xaml.index(marker)
    end = xaml.index("</Button>", start)
    button = xaml[start:end]
    assert f'Content="{title}"' in button or f'Text="{title}"' in button


def test_version() -> None:
    assert VERSION.read_text(encoding="utf-8").strip() == "2.3.26.1"


def test_simple_sidebar_is_fixed_and_advanced_is_landing_page() -> None:
    xaml = SHELL.read_text(encoding="utf-8")
    expected = {
        "SimpleHomeButton": "首页",
        "SimpleReviewButton": "待我审核",
        "SimpleActiveButton": "进行中",
        "SimpleCompletedButton": "已完成",
        "SimpleAdvancedButton": "高级",
    }
    for name, title in expected.items():
        assert_simple_nav_button(xaml, name, title)
    assert 'x:Name="AdvancedHomePanel"' in xaml
    assert 'ItemsSource="{Binding NavigationItems}"' not in xaml


def test_operator_routes_are_additive_and_keep_every_advanced_route() -> None:
    source = ROUTES.read_text(encoding="utf-8")
    for route in (
        "OperatorHome",
        "OperatorReview",
        "OperatorInProgress",
        "OperatorCompleted",
        "AdvancedHome",
        "Dashboard",
        "Projects",
        "TaskCenter",
        "Results",
        "Approvals",
        "CloudDevelopment",
        "Automation",
        "BusinessAutomation",
        "Health",
        "Diagnostics",
        "Settings",
    ):
        assert route in source


def test_projection_is_read_only_and_has_no_fake_progress_or_execution_authority() -> None:
    source = PROJECTION.read_text(encoding="utf-8")
    assert "FromSnapshot" in source
    assert "PendingReview" in source
    assert "InProgress" in source
    assert "Completed" in source
    assert "Percentage" not in source
    assert "Percent" not in source
    for forbidden in (
        "ApiKey",
        "ProviderKey",
        "EndpointInput",
        "ModelInput",
        "PromptInput",
        "WorkflowInput",
        "CommandInput",
        "SqlInput",
    ):
        assert forbidden not in source


def test_assistant_working_requires_real_worker_execution_not_queue_presence() -> None:
    source = EXPERIENCE.read_text(encoding="utf-8")
    assert 'string.Equals(snapshot.State.Worker.Reason, "executing"' in source
    assert "Projection.FromSnapshot(snapshot).InProgress.Count > 0" not in source
    assert "hasRealExecution" in source
    assert 'OperatorAssistantVisualState.Resting         => "休息中"' in source


def test_home_matches_reference_information_architecture_without_fake_telemetry() -> None:
    xaml = HOME_XAML.read_text(encoding="utf-8")
    for marker in (
        'x:Name="ReferenceHomeLayout"',
        'x:Name="HeroNewTaskCard"',
        'x:Name="TaskSummaryBoard"',
        'x:Name="SystemStatusCard"',
        'x:Name="ResourceMonitorCard"',
        'x:Name="RecentTasksPanel"',
        'x:Name="SystemActivityPanel"',
        'x:Name="WidgetBoard"',
    ):
        assert marker in xaml
    assert "资源遥测尚未接入" in xaml
    for fake_value in ("24%", "42%", "37%", "68%", "55%", "72%"):
        assert fake_value not in xaml


def test_new_task_wizard_is_closed_and_future_web_research_is_disabled() -> None:
    source = WIZARD.read_text(encoding="utf-8")
    xaml = WIZARD_XAML.read_text(encoding="utf-8")
    assert "enum OperatorTaskKind" in source
    assert "SystemDiagnostic" in source
    assert "BusinessAnalysis" in source
    assert "ContentPlan" in source
    assert "WebResearch" in source
    assert '"尚未接入"' in source
    assert "CreateDiagnosticSnapshotAsync" in source
    assert "NavigationRoute.BusinessAutomation" in source
    assert "网络 Search / 爬虫尚未在 26.1 接入" in xaml
    for forbidden in (
        "ApiKey",
        "ProviderKey",
        "EndpointInput",
        "ModelInput",
        "PromptInput",
        "WorkflowInput",
        "CommandInput",
        "BudgetInput",
    ):
        assert forbidden not in source
        assert forbidden not in xaml
