"""Windows 安装包必须创建并验证唯一版本快捷方式。"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RELEASE = ROOT / "windows" / "desktop" / "release"
INSTALLER = RELEASE / "Install-Phase2Prebuilt.ps1"
COMMON = RELEASE / "Phase2Prebuilt.Common.ps1"


def test_windows_installer_creates_versioned_shortcuts_in_three_managed_locations() -> None:
    """安装包只在三处受管目录保留当前四段版本快捷方式。"""

    installer = INSTALLER.read_text(encoding="utf-8-sig")
    common = COMMON.read_text(encoding="utf-8-sig")

    for required in (
        "[Environment+SpecialFolder]::DesktopDirectory",
        "function Get-PicotooManagedShortcutLocations",
        "function Get-PicotooManagedShortcutName",
        "function Get-PicotooManagedShortcutSnapshot",
        "function Restore-PicotooManagedShortcutSnapshot",
        "function Remove-PicotooManagedShortcuts",
        "function Set-PicotooShortcuts",
        "function Assert-PicotooShortcuts",
        '"Picotoo Pet AI $ProductVersion.lnk"',
        "Microsoft\\Windows\\Start Menu\\Programs",
        "Microsoft\\Windows\\Start Menu\\Programs\\Startup",
        "RequireNoLegacy",
        'IconLocation     = "$expectedExecutable,0"',
        "TargetPath",
    ):
        assert required in common

    assert '"Phase2Prebuilt.Common.ps1"' in installer
    assert ". $commonScript" in installer
    assert "preActivationShortcutState" in installer
    assert "Set-PicotooShortcuts" in installer
    assert "-ProductVersion $productVersion" in installer
    assert "Assert-PicotooShortcuts" in installer
    assert "-RequireNoLegacy" in installer
    assert "$report.desktop_shortcut_created = $true" in installer
    assert "$report.shortcuts_verified" in installer
    assert "$report.shortcut_state" in installer


def test_windows_shortcut_failure_restores_exact_pre_activation_snapshot() -> None:
    """快捷方式创建或校验失败必须恢复安装前完整 COM 属性快照。"""

    source = INSTALLER.read_text(encoding="utf-8-sig")

    assert "$activationStarted = $true" in source
    assert "Restore-PreviousActivation" in source
    assert "Get-PicotooManagedShortcutSnapshot" in source
    assert "Restore-PicotooManagedShortcutSnapshot" in source
    assert "pre-activation-snapshot" in source
    assert "Assert-PicotooShortcuts" in source
    assert "recovery_shortcuts" in source
