"""Phase 2.3 Slice A Windows Control Center 源码边界测试。"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DESKTOP = ROOT / "windows" / "desktop" / "src" / "PicotooPet.Desktop"


def read(relative: str) -> str:
    """读取 Control Center 源文件。"""

    return (DESKTOP / relative).read_text(encoding="utf-8")


def test_shell_exists_and_desktop_remains_winexe() -> None:
    """新 Shell 必须绑定冻结导航，同时保持无控制台的 WinExe 交付。"""

    shell = read("Views/ShellWindow.xaml")
    assert "NavigationItems" in shell
    assert "CurrentPage" in shell
    assert 'Width="232"' in shell

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


def test_control_center_native_windows_ci_has_required_gates() -> None:
    """独立 Slice A CI 必须在原生 Windows 上执行全部合同、构建和包级复验。"""

    workflow = (
        ROOT / ".github" / "workflows" / "windows-control-center-ci.yml"
    ).read_text(encoding="utf-8")
    for required in (
        "windows-2025",
        "setup-python",
        "setup-dotnet",
        "pytest",
        "dotnet build",
        "PicotooPet.Desktop.Core.SmokeTests",
        "--self-test",
        "Build-Phase2WindowsRelease.ps1",
        "Test-Phase2WindowsRelease.ps1",
        "powershell",
        "upload-artifact",
    ):
        assert required in workflow


def test_control_center_ci_uses_version_label_and_shell_self_test_marker() -> None:
    """非发布包必须有独立版本标签，包级复验必须确认新 Shell 自检。"""

    build = (
        ROOT / "windows" / "desktop" / "scripts" / "Build-Phase2WindowsRelease.ps1"
    ).read_text(encoding="utf-8")
    verify = (
        ROOT / "windows" / "desktop" / "scripts" / "Test-Phase2WindowsRelease.ps1"
    ).read_text(encoding="utf-8")
    self_test = read("Services/AppSelfTest.cs")

    assert "$VersionLabel" in build
    assert "control_center_shell" in verify
    assert "PHASE23_CONTROL_CENTER_SELF_TEST=PASS" in self_test
