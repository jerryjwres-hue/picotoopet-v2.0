from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DESKTOP = ROOT / "windows" / "desktop" / "src" / "PicotooPet.Desktop"
VIEWS = DESKTOP / "Views"
PAGES = VIEWS / "Pages"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def _button_open_tags(source: str) -> list[str]:
    return re.findall(r"<Button\b[^>]*>", source, flags=re.IGNORECASE | re.DOTALL)


def test_simple_sidebar_uses_navigation_items_as_single_source_of_truth() -> None:
    shell = _read(VIEWS / "ShellWindow.xaml")
    code = _read(VIEWS / "ShellWindow.xaml.cs")

    assert 'ItemsSource="{Binding NavigationItems' in shell
    assert 'Content="首页"' not in shell
    assert 'Content="待我审核"' not in shell
    assert 'Content="进行中"' not in shell
    assert 'Content="已完成"' not in shell
    assert 'Content="已删除"' not in shell
    assert 'Content="高级"' not in shell
    assert "InsertDeletedNavigationButton" not in code


def test_home_recent_tasks_are_real_detail_actions() -> None:
    xaml = _read(PAGES / "OperatorHomePage.xaml")
    code = _read(PAGES / "OperatorHomePage.xaml.cs")

    assert 'ItemsSource="{Binding RecentTasks' in xaml
    assert 'Click="RecentTask_Click"' in xaml
    assert "TaskDetailWindow" in code
    assert "TaskDetailViewModel" in code


def test_operator_home_preserves_approved_rich_product_structure() -> None:
    xaml = _read(PAGES / "OperatorHomePage.xaml")

    # 交互修复不能通过删掉既有首页产品内容来降低验收难度。
    for required in (
        'x:Name="HeroCard"',
        'x:Name="HomeGreetingStrip"',
        'x:Name="TaskOverviewCard"',
        'x:Name="RecentTasksCard"',
        'x:Name="SystemStatusCard"',
        'x:Name="ResourceMonitorCard"',
        'x:Name="WorkComponentsCard"',
        'Source="/Picotoo Pet AI;component/Assets/Pet/Husky/V1/idle_0.png"',
        '<LinearGradientBrush StartPoint="0,0" EndPoint="1,1">',
        "工作组件区",
        "资源监控",
    ):
        assert required in xaml

    assert xaml.count("<GradientStop") >= 3
    assert xaml.count("Effect=\"{StaticResource SoftCardShadow}\"") >= 5
    assert len(xaml.splitlines()) >= 650


def test_task_center_rows_and_results_open_shared_task_detail() -> None:
    task_xaml = _read(PAGES / "TaskCenterPage.xaml")
    task_code = _read(PAGES / "TaskCenterPage.xaml.cs")
    results_code = _read(PAGES / "ResultsPage.xaml.cs")
    results_vm = _read(DESKTOP / "ViewModels" / "ResultsPageViewModel.cs")

    # Task Center 不能只靠右侧按钮“形式上能打开详情”；任务行本身必须有真实入口。
    assert 'MouseDoubleClick="TaskList_DoubleClick"' in task_xaml
    assert "TaskList_DoubleClick" in task_code
    assert "OpenSelectedTaskDetail" in task_code
    assert 'Click="OpenTaskDetail_Click"' in task_xaml
    assert "TaskDetailWindow" in task_code
    assert "TaskDetailViewModel" in task_code
    assert "TaskDetailWindow" in results_code
    assert "TaskDetailViewModel" in results_code
    assert "当前只开放诊断结果正文预览" not in results_vm


def test_visible_wpf_buttons_have_an_action_or_builtin_dialog_behavior() -> None:
    excluded = {
        "AssistantPetPanel.xaml",
        "FloatingPetWindow.xaml",
    }
    dead: list[str] = []
    for path in sorted(VIEWS.rglob("*.xaml")):
        if path.name in excluded:
            continue
        source = _read(path)
        for index, tag in enumerate(_button_open_tags(source), start=1):
            actionable = any(
                token in tag
                for token in (
                    " Click=",
                    " Command=",
                    " IsCancel=\"True\"",
                    " DialogResult=",
                    " IsHitTestVisible=\"False\"",
                )
            )
            if not actionable:
                dead.append(f"{path.relative_to(ROOT)} button#{index}: {' '.join(tag.split())[:180]}")

    assert not dead, "Buttons that look actionable but have no action:\n" + "\n".join(dead)


def test_hand_cursor_is_reserved_for_actionable_surfaces() -> None:
    excluded = {
        "AssistantPetPanel.xaml",
        "FloatingPetWindow.xaml",
    }
    dead: list[str] = []
    # Image/Canvas are included because decorative artwork must never advertise a
    # clickable hand cursor unless a real event is wired. Pet surfaces are excluded
    # because Maotai's interaction implementation is integrated independently.
    pattern = re.compile(
        r"<(?P<kind>Border|Grid|TextBlock|StackPanel|Image|Canvas)\b(?P<tag>[^>]*)>",
        re.I | re.S,
    )
    for path in sorted(VIEWS.rglob("*.xaml")):
        if path.name in excluded:
            continue
        source = _read(path)
        for match in pattern.finditer(source):
            tag = match.group("tag")
            if 'Cursor="Hand"' not in tag:
                continue
            if any(
                event in tag
                for event in (
                    "MouseLeftButtonDown=",
                    "MouseLeftButtonUp=",
                    "MouseUp=",
                    "PreviewMouseLeftButtonDown=",
                )
            ):
                continue
            dead.append(
                f"{path.relative_to(ROOT)} {match.group('kind')}: {' '.join(tag.split())[:180]}"
            )

    assert not dead, "Non-actionable surfaces advertise a hand cursor:\n" + "\n".join(dead)


def test_whole_app_readability_and_dpi_floor_remain_enabled() -> None:
    app = _read(DESKTOP / "App.xaml.cs")
    resources = _read(DESKTOP / "App.xaml")
    project = _read(DESKTOP / "PicotooPet.Desktop.csproj")

    assert "MinimumOperatorFontSize = 12.0" in app
    assert "IsPetSurface" in app
    assert '<Setter Property="FontSize" Value="14" />' in resources
    assert '<Setter Property="MinHeight" Value="38" />' in resources
    assert "PerMonitorV2" in project


def test_windows_ci_and_release_never_suppress_maotai_asset_gates() -> None:
    ui_harness = ROOT / "windows" / "desktop" / "scripts" / "Prepare-WindowsUiBehaviorHarness.ps1"
    workflow = _read(ROOT / ".github" / "workflows" / "windows-control-center-ci.yml")
    release_harness = _read(
        ROOT / "windows" / "desktop" / "scripts" / "Prepare-ResearchWindowsReleaseHarness.ps1"
    )

    # CI/Release 不得通过修改 Smoke 入口来“延后”茅台验收；真实资产不完整就应明确失败。
    assert not ui_harness.exists()
    assert "Prepare-WindowsUiBehaviorHarness.ps1" not in workflow
    assert "MaotaiNaturalMotionV2AcceptanceSmokeTests.Run();" not in release_harness
    assert "MaotaiAssetPixelValidationSmokeTests.Run();" not in release_harness
    assert "DEFERRED_UNTIL_REAL_PNG_DELIVERY" not in release_harness
    assert "$program.Replace(" not in release_harness
    assert "RESEARCH_RELEASE_MAOTAI_V2_ASSET_GATE=BLOCKED_MISSING_REAL_ASSETS" in release_harness


def test_research_release_provenance_is_declared_not_runtime_patched() -> None:
    builder = _read(ROOT / "windows" / "desktop" / "scripts" / "Build-Phase2WindowsRelease.ps1")
    release_harness = _read(
        ROOT / "windows" / "desktop" / "scripts" / "Prepare-ResearchWindowsReleaseHarness.ps1"
    )

    assert ".github/workflows/research-windows-final-release.yml@" in builder
    assert "Build-Phase2WindowsRelease.ps1" not in release_harness
    assert "GITHUB_WORKFLOW_REF" not in release_harness
    assert "$build =" not in release_harness
    assert "$build.Replace(" not in release_harness


def test_research_install_readme_describes_the_real_execution_boundary() -> None:
    readme = _read(ROOT / "windows" / "desktop" / "release" / "README_INSTALL_CN.txt")

    for required in (
        "research.search",
        "Mac Worker",
        "Research Gateway",
        "只读",
        "查看详情 / 结果",
    ):
        assert required in readme
    assert "Windows 不直接调用外部研究工具" in readme
    assert "不执行点赞、关注、评论、发帖或其他账号写操作" in readme
