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
