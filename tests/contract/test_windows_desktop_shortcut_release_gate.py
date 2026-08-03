"""Windows 安装包必须创建并验证桌面快捷方式。"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RELEASE = ROOT / "windows" / "desktop" / "release"
INSTALLER = RELEASE / "Install-Phase2Prebuilt.ps1"
COMMON = RELEASE / "Phase2Prebuilt.Common.ps1"


def test_windows_installer_creates_desktop_start_menu_and_startup_shortcuts() -> None:
    """后续 Windows 安装包不得再次遗漏桌面入口。"""

    installer = INSTALLER.read_text(encoding="utf-8-sig")
    common = COMMON.read_text(encoding="utf-8-sig")

    for required in (
        "[Environment+SpecialFolder]::DesktopDirectory",
        'Join-Path $desktop "Picotoo Pet AI.lnk"',
        'Microsoft\\Windows\\Start Menu\\Programs\\Picotoo Pet AI.lnk',
        'Microsoft\\Windows\\Start Menu\\Programs\\Startup\\Picotoo Pet AI.lnk',
        "function Set-PicotooShortcuts",
        "function Assert-PicotooShortcuts",
        'IconLocation     = "$expectedExecutable,0"',
        "TargetPath",
    ):
        assert required in common

    assert '"Phase2Prebuilt.Common.ps1"' in installer
    assert ". $commonScript" in installer
    assert "Set-PicotooShortcuts -Executable $executable" in installer
    assert "Assert-PicotooShortcuts" in installer
    assert "$report.desktop_shortcut_created = $true" in installer
    assert "$report.shortcuts_verified" in installer


def test_windows_shortcut_failure_participates_in_activation_rollback() -> None:
    """快捷方式创建或校验失败必须触发既有激活恢复事务。"""

    source = INSTALLER.read_text(encoding="utf-8-sig")

    assert "$activationStarted = $true" in source
    assert "Restore-PreviousActivation" in source
    assert "Remove-PicotooShortcuts" in source
    assert "Assert-PicotooShortcuts" in source
    assert "recovery_shortcuts" in source
