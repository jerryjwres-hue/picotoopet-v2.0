from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VERSION = ROOT / "src" / "picotoopet_core" / "product-version.txt"
DESKTOP = ROOT / "windows" / "desktop" / "src" / "PicotooPet.Desktop"
SHELL = DESKTOP / "Views" / "ShellWindow.xaml"
ROUTES = DESKTOP / "Navigation" / "NavigationRoute.cs"
PROJECTION = DESKTOP / "ViewModels" / "OperatorProjection.cs"
WIZARD = DESKTOP / "ViewModels" / "NewTaskWizardViewModel.cs"
WIZARD_XAML = DESKTOP / "Views" / "Pages" / "NewTaskWizardWindow.xaml"


def test_version() -> None:
    # 产品身份仍保持已批准的 2.3.26.1；Research 2.3.27.1 是增量能力包版本。
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
        assert f'x:Name="{name}"' in xaml
        assert f'Content="{title}"' in xaml
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


def test_new_task_wizard_keeps_26_1_boundaries_and_exposes_read_only_research() -> None:
    source = WIZARD.read_text(encoding="utf-8")
    xaml = WIZARD_XAML.read_text(encoding="utf-8")
    assert "enum OperatorTaskKind" in source
    assert "SystemDiagnostic" in source
    assert "BusinessAnalysis" in source
    assert "ContentPlan" in source
    assert "WebResearch" in source
    assert "research.search" in source
    assert "CreateDiagnosticSnapshotAsync" in source
    assert "NavigationRoute.BusinessAutomation" in source
    assert "Research 2.3.27.1 已接入只读网络搜索" in xaml
    assert "网络搜索 / 爬虫尚未在 26.1 接入" not in xaml
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
