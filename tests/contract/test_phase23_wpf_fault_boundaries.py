"""WPF 全局异常日志与页面导航故障隔离合同。"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP_CODE = (
    ROOT
    / "windows"
    / "desktop"
    / "src"
    / "PicotooPet.Desktop"
    / "App.xaml.cs"
)
SHELL_XAML = (
    ROOT
    / "windows"
    / "desktop"
    / "src"
    / "PicotooPet.Desktop"
    / "Views"
    / "ShellWindow.xaml"
)
SHELL_CODE = SHELL_XAML.with_suffix(".xaml.cs")


def test_app_registers_redacted_global_wpf_exception_logging() -> None:
    """逃出页面边界的 WPF 异常必须进入现有脱敏日志器。"""

    app_code = APP_CODE.read_text(encoding="utf-8")

    assert "DispatcherUnhandledException += OnDispatcherUnhandledException;" in app_code
    assert '_logger?.Error("WPF 未处理异常", e.Exception);' in app_code


def test_shell_uses_a_page_navigation_fault_boundary() -> None:
    """页面内容宿主必须隔离布局故障并转交 Shell 恢复。"""

    shell_xaml = SHELL_XAML.read_text(encoding="utf-8")
    shell_code = SHELL_CODE.read_text(encoding="utf-8")

    assert "NavigationContentHost" in shell_xaml
    assert 'NavigationFaulted="ContentHost_NavigationFaulted"' in shell_xaml
    assert "ShowNavigationFailure(failedRoute)" in shell_code
