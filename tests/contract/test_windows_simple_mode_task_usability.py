from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DESKTOP = ROOT / "windows" / "desktop" / "src" / "PicotooPet.Desktop"
PAGES = DESKTOP / "Views" / "Pages"
VIEW_MODELS = DESKTOP / "ViewModels"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def test_operator_task_modes_use_distinct_lifecycle_actions() -> None:
    view_model = _read(VIEW_MODELS / "OperatorTaskListPageViewModel.cs")

    # 活动任务必须先取消；只有终态任务才进入“已删除”，已删除任务则恢复。
    for required in (
        "取消所选",
        "取消任务",
        "移到已删除",
        "恢复所选",
        "await _session.CancelTaskAsync",
        "await _session.HideTasksAsync",
        "await _session.RestoreTasksAsync",
    ):
        assert required in view_model

    assert "OperatorTaskListMode.InProgress" in view_model
    assert "OperatorTaskListMode.Completed" in view_model
    assert "OperatorTaskListMode.Deleted" in view_model


def test_operator_task_lists_support_keyword_category_and_date_filters() -> None:
    xaml = _read(PAGES / "OperatorTaskListPage.xaml")
    code = _read(PAGES / "OperatorTaskListPage.xaml.cs")
    view_model = _read(VIEW_MODELS / "OperatorTaskListPageViewModel.cs")
    projection = _read(VIEW_MODELS / "OperatorProjection.cs")

    for required in (
        'x:Name="KeywordSearchBox"',
        'Text="{Binding Keyword, UpdateSourceTrigger=PropertyChanged}"',
        'ItemsSource="{Binding Categories, Mode=OneWay}"',
        'SelectedItem="{Binding SelectedCategory, Mode=TwoWay}"',
        'SelectedDate="{Binding StartDate, Mode=TwoWay}"',
        'SelectedDate="{Binding EndDate, Mode=TwoWay}"',
        'Click="ApplyFilters_Click"',
        'Click="ClearFilters_Click"',
        'KeyDown="KeywordSearchBox_KeyDown"',
    ):
        assert required in xaml

    for required in (
        "KeywordSearchBox_KeyDown",
        "ApplyFilters_Click",
        "ClearFilters_Click",
    ):
        assert required in code

    for required in (
        "public string Keyword",
        "public IReadOnlyList<string> Categories",
        "public string SelectedCategory",
        "public DateTime? StartDate",
        "public DateTime? EndDate",
        "public void ApplyFilters()",
        "public void ClearFilters()",
        "MatchesKeyword",
        "MatchesCategory",
        "MatchesDateRange",
    ):
        assert required in view_model

    # 搜索字段来自既有 TaskRecord 的安全投影，不读取任意文件或另建任务数据库。
    for required in (
        "string TaskType",
        "string CategoryText",
        "string SearchText",
        "DateTimeOffset CreatedAt",
    ):
        assert required in projection


def test_operator_home_work_components_are_real_navigation_actions() -> None:
    xaml = _read(PAGES / "OperatorHomePage.xaml")
    code = _read(PAGES / "OperatorHomePage.xaml.cs")

    for required in (
        'x:Name="ProjectsResearchButton"',
        'Click="ProjectsResearch_Click"',
        'x:Name="BusinessAnalysisButton"',
        'Click="BusinessAnalysis_Click"',
        'x:Name="AutomationEntryButton"',
        'Click="AutomationEntry_Click"',
        'x:Name="ResultsReviewButton"',
        'Click="ResultsReview_Click"',
    ):
        assert required in xaml

    for required in (
        "ProjectsResearch_Click",
        "Navigate(NavigationRoute.Projects)",
        "BusinessAnalysis_Click",
        "Navigate(NavigationRoute.BusinessAutomation)",
        "AutomationEntry_Click",
        "Navigate(NavigationRoute.Automation)",
        "ResultsReview_Click",
        "Navigate(NavigationRoute.Results)",
    ):
        assert required in code


def test_task_detail_uses_named_left_right_workspace() -> None:
    xaml = _read(PAGES / "TaskDetailWindow.xaml")

    for required in (
        'x:Name="DetailWorkspace"',
        'x:Name="MetadataPane"',
        'x:Name="ResultPane"',
        'Grid.Column="1"',
        'Text="任务信息"',
        'Text="{Binding ResultTitle}"',
    ):
        assert required in xaml

    assert xaml.count("<ColumnDefinition") >= 2
    assert 'MinWidth="820"' in xaml
