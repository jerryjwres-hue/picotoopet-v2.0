"""Phase 2.3 Windows Control Center 源码与交付边界测试。"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DESKTOP = ROOT / "windows" / "desktop" / "src" / "PicotooPet.Desktop"
CORE = ROOT / "windows" / "desktop" / "src" / "PicotooPet.Desktop.Core"


def read(relative: str) -> str:
    """读取 Control Center 源文件。"""

    return (DESKTOP / relative).read_text(encoding="utf-8")


def read_core(relative: str) -> str:
    """读取 Windows Core 源文件。"""

    return (CORE / relative).read_text(encoding="utf-8")


def test_shell_exists_and_desktop_remains_winexe() -> None:
    """当前 Shell 使用单一数据源展示六个简单入口，同时完整保留高级工程路由。"""

    shell = read("Views/ShellWindow.xaml")
    shell_vm = read("ViewModels/ShellViewModel.cs")
    simple_mode = read("Views/ShellWindow.SimpleMode.cs")
    for required in (
        'ItemsSource="{Binding NavigationItems, Mode=OneWay}"',
        'SelectedItem="{Binding SelectedNavigationItem, Mode=TwoWay',
        'x:Name="AdvancedHomePanel"',
        'Content="{Binding CurrentPage, Mode=OneWay}"',
        'Title="{Binding WindowTitle, Mode=OneWay}"',
        'Text="{Binding ControlCenterSubtitle, Mode=OneWay}"',
    ):
        assert required in shell
    for title in ("首页", "待我审核", "进行中", "已完成", "已删除", "高级"):
        assert f'Content="{title}"' not in shell
        assert f'"{title}"' in shell_vm
    assert "NavigationRoute.OperatorDeleted" in shell_vm
    for route in (
        "NavigationRoute.Projects",
        "NavigationRoute.TaskCenter",
        "NavigationRoute.Results",
        "NavigationRoute.Approvals",
        "NavigationRoute.CloudDevelopment",
        "NavigationRoute.Automation",
        "NavigationRoute.BusinessAutomation",
        "NavigationRoute.Health",
        "NavigationRoute.Diagnostics",
        "NavigationRoute.Settings",
    ):
        assert route in simple_mode

    project = read("PicotooPet.Desktop.csproj")
    assert "<OutputType>WinExe</OutputType>" in project


def test_control_center_session_owns_connection_lifecycle() -> None:
    """Session 必须集中保留初始化、重新配对和异步释放边界。"""

    session = read("Services/ControlCenterSession.cs")
    for required in (
        "InitializeAsync",
        "SaveAndConnectAsync",
        "DisposeAsync",
        "StateSyncCoordinator",
        "CredentialManagerTokenStore",
        "DesktopSettingsStore",
        "WorkerStore",
    ):
        assert required in session


def test_shell_code_behind_only_forwards_password_and_lifecycle() -> None:
    """PasswordBox 密文只能由视图转交 Session，不得进入 ShellViewModel。"""

    code = read("Views/ShellWindow.xaml.cs")
    assert "TokenPasswordBox.Password" in code
    assert "_session.SaveAndConnectAsync" in code
    assert "TokenPasswordBox.Clear()" in code
    assert "MacCoreClient" not in code
    assert "EventStreamClient" not in code


def test_composition_root_uses_new_shell_without_changing_storage_targets() -> None:
    """组合根必须切换到 Session/Shell，同时保留单实例和现有数据路径。"""

    app = read("App.xaml.cs")
    for required in (
        "ControlCenterSession",
        "ShellViewModel",
        "ShellWindow",
        "Local\\PicotooPetV2.Desktop.SingleInstance",
        '"PicotooPetV2"',
        '"Desktop"',
        '"settings.json"',
        '"desktop.log"',
    ):
        assert required in app


def test_shell_close_is_intercepted_and_exit_is_explicit() -> None:
    """普通关闭必须隐藏到托盘，只有显式退出才能结束 UI 进程。"""

    code = read("Views/ShellWindow.xaml.cs")
    app = read("App.xaml")
    assert "OnClosing" in code
    assert "ExitRequested" in code
    assert 'ShutdownMode="OnExplicitShutdown"' in app


def test_tray_uses_builtin_notify_icon_and_has_required_commands() -> None:
    """托盘必须使用系统自带 NotifyIcon，并提供打开、审批入口和显式退出。"""

    contract = read("Services/ITrayService.cs")
    service = read("Services/WindowsTrayService.cs")
    project = read("PicotooPet.Desktop.csproj")

    for required in ("OpenRequested", "PendingApprovalsRequested", "ExitRequested"):
        assert required in contract
        assert required in service
    assert "NotifyIcon" in service
    assert "ContextMenuStrip" in service
    assert "<UseWindowsForms>true</UseWindowsForms>" in project
    assert "<PackageReference" not in project


def test_explicit_exit_disposes_session_and_tray_before_shutdown() -> None:
    """组合根必须先释放网络、日志和托盘句柄，再显式关闭 WPF。"""

    app = read("App.xaml.cs")
    for required in (
        "WindowsTrayService",
        "DisposeRuntimeAsync",
        "await _session.DisposeAsync()",
        "_trayService.Dispose()",
        "Shutdown()",
    ):
        assert required in app


def test_worker_status_is_synchronized_without_starting_a_worker() -> None:
    """客户端只能读取 Worker 状态，不能在 Slice B 自动创建或启动执行器。"""

    client = read_core("Networking/MacCoreClient.cs")
    coordinator = read_core("State/StateSyncCoordinator.cs")
    worker_store = read_core("State/WorkerStateStore.cs")

    assert "GetWorkerStatusAsync" in client
    assert '"api/v1/workers/status"' in client
    assert "LoadWorkerStatusAsync" in coordinator
    assert "WorkerSnapshot.NotDeployed" in worker_store
    forbidden = (
        "lease_next",
        "StartWorker",
        "RunWorker",
        "ProcessQueuedTasks",
    )
    combined = client + coordinator + worker_store
    assert all(item not in combined for item in forbidden)


def test_task_center_uses_real_queue_and_truthful_waiting_state() -> None:
    """任务中心必须展示真实队列并把无 Worker 的 Queued 解释为等待执行器。"""

    view_model = read("ViewModels/TaskCenterPageViewModel.cs")
    task_row = read("ViewModels/TaskRowViewModel.cs")
    view = read("Views/Pages/TaskCenterPage.xaml")
    app = read("App.xaml")
    shell = read("ViewModels/ShellViewModel.cs")

    for required in (
        "VisibleTasks",
        "SelectedFilter",
        "CancelSelectedAsync",
        "RetrySelectedAsync",
        "WorkerStatusText",
    ):
        assert required in view_model
    assert '"Queued" when !worker.Available => "等待执行器"' in task_row
    assert "DisplayStatus" in task_row
    assert "VirtualizationMode=\"Recycling\"" in view
    assert "TaskCenterPageViewModel" in app
    assert "new TaskCenterPageViewModel(_session, snapshot)" in shell


def test_terminal_cancel_requires_confirmation_and_retry_is_new_task() -> None:
    """取消必须显式确认；重试必须调用服务端创建子任务而不是重开原任务。"""

    view_code = read("Views/Pages/TaskCenterPage.xaml.cs")
    session_actions = read("Services/ControlCenterSession.Tasks.cs")
    coordinator = read_core("State/StateSyncCoordinator.cs")

    assert "MessageBoxButton.YesNo" in view_code
    assert "MessageBoxResult.No" in view_code
    assert "CancelTaskAsync" in session_actions
    assert "RetryTaskAsync" in session_actions
    assert "_client.RetryTaskAsync" in coordinator


def test_dashboard_exposes_worker_state_without_fake_availability() -> None:
    """总览必须显示 Worker 状态和等待数量，不能只显示任务数量。"""

    view_model = read("ViewModels/OverviewPageViewModel.cs")
    view = read("Views/Pages/OverviewPage.xaml")
    for required in ("WorkerText", "WorkerReason", "WaitingForWorkerCount"):
        assert required in view_model
        assert required in view


def test_control_center_and_release_ci_have_non_overlapping_required_gates() -> None:
    """WPF 行为门不重复打包；正式 Release 独占盖章和原始安装生命周期测试。"""

    control = (
        ROOT / ".github" / "workflows" / "windows-control-center-ci.yml"
    ).read_text(encoding="utf-8")
    release = (
        ROOT / ".github" / "workflows" / "windows-phase2-release.yml"
    ).read_text(encoding="utf-8")

    for required in (
        "Detect Windows impact",
        "windows-2025",
        "workflow_dispatch",
        "inputs.runner_target",
        "setup-python",
        "setup-dotnet",
        "pytest",
        "dotnet build",
        "PicotooPet.Desktop.Core.SmokeTests",
        "ShellNavigationReconnectWpfSmokeTests",
        "PHASE23_TASK_CENTER_SELF_TEST=PASS",
        "upload-artifact",
    ):
        assert required in control
    for forbidden in (
        "Build-Phase2WindowsRelease.ps1",
        "stamp_windows_goal_integrity.py",
        "verify_project_goal_integrity.py",
        "Invoke-Phase2WindowsReleaseLifecycleGate.ps1",
    ):
        assert forbidden not in control
    for required in (
        "Detect Windows release impact",
        "Build-Phase2WindowsRelease.ps1",
        "stamp_windows_goal_integrity.py",
        "verify_project_goal_integrity.py",
        "Test-Phase2WindowsRelease.ps1",
        "PicotooPet-Phase23-CloudContract-Windows-Prebuilt",
    ):
        assert required in release
    assert "Invoke-Phase2WindowsReleaseLifecycleGate.ps1" not in release


def test_package_verifies_task_center_and_worker_fallback() -> None:
    """真实 ZIP 载荷必须运行桌面自检，并由自检报告覆盖任务中心与 Worker 降级。"""

    build = (
        ROOT / "windows" / "desktop" / "scripts" / "Build-Phase2WindowsRelease.ps1"
    ).read_text(encoding="utf-8")
    verify = (
        ROOT / "windows" / "desktop" / "scripts" / "Test-Phase2WindowsRelease.ps1"
    ).read_text(encoding="utf-8")
    self_test = read("Services/AppSelfTest.cs")

    assert "$VersionLabel" in build
    assert '"--self-test"' in verify
    assert "selfTest.status" in verify
    assert "PHASE23_TASK_CENTER_PACKAGE_TEST=PASS" in verify
    for required in (
        "control_center_shell",
        "task_center_policy",
        "worker_fallback",
        "PHASE23_CONTROL_CENTER_SELF_TEST=PASS",
        "PHASE23_TASK_CENTER_SELF_TEST=PASS",
    ):
        assert required in self_test
