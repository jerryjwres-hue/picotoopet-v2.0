"""Versioned Windows shortcut lifecycle and exact-state restoration contract."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RELEASE = ROOT / "windows" / "desktop" / "release"
SCRIPTS = ROOT / "windows" / "desktop" / "scripts"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_managed_shortcuts_use_exact_versioned_names_and_snapshots() -> None:
    common = read(RELEASE / "Phase2Prebuilt.Common.ps1")
    for required in (
        "Get-PicotooManagedShortcutSnapshot",
        "Restore-PicotooManagedShortcutSnapshot",
        "Remove-PicotooManagedShortcuts",
        "Get-PicotooManagedShortcutLocations",
        "ProductVersion",
        "RequireNoLegacy",
        "target_path",
        "arguments",
        "working_directory",
        "icon_location",
        "description",
    ):
        assert required in common
    assert (
        "^Picotoo Pet AI(?: [0-9]+\\.[0-9]+\\.[0-9]+\\.[0-9]+)?\\.lnk$"
        in common
    )
    assert '"Picotoo Pet AI $ProductVersion.lnk"' in common


def test_install_and_rollback_persist_and_restore_shortcut_state() -> None:
    install = read(RELEASE / "Install-Phase2Prebuilt.ps1")
    rollback = read(RELEASE / "Rollback-Phase2Prebuilt.ps1")
    verify = read(RELEASE / "Verify-Phase2Prebuilt.ps1")

    for required in (
        "preActivationShortcutState",
        "shortcut_state",
        "Get-PicotooManagedShortcutSnapshot",
        "Restore-PicotooManagedShortcutSnapshot",
        "ProductVersion",
        "RequireNoLegacy",
    ):
        assert required in install
    for required in (
        "shortcut_state",
        "Restore-PicotooManagedShortcutSnapshot",
        "legacy-pointer-fallback",
    ):
        assert required in rollback
    assert "RequireNoLegacy" in verify
    assert "product_version" in verify


def test_native_lifecycle_fixture_covers_version_replacement_and_exact_restore() -> None:
    lifecycle = read(SCRIPTS / "Test-Phase2WindowsRelease.ps1")
    for required in (
        "Set-PackageProductVersion",
        '"2.3.5.9"',
        '"2.3.6.1"',
        "shortcut_state",
        "Assert-ShortcutSnapshotEqual",
        "Picotoo Pet AI 2.3.5.9.lnk",
        "Picotoo Pet AI 2.3.6.1.lnk",
    ):
        assert required in lifecycle


def test_source_lifecycle_gate_uses_canonical_version_for_formal_package_only() -> None:
    lifecycle = read(SCRIPTS / "Test-Phase2WindowsRelease.ps1")
    wrapper = SCRIPTS / "Invoke-Phase2WindowsReleaseLifecycleGate.ps1"

    assert not wrapper.exists()
    for required in (
        "product-version.txt",
        "expectedProductVersion",
        "正式包 product_version",
        "桌面自检报告产品版本",
    ):
        assert required in lifecycle
    # 合成升级/回滚夹具仍可改 fixture 的产品版本；正式包断言必须直接读取唯一版本源。
    assert "Set-PackageProductVersion" in lifecycle
    assert "formalManifestAssertion" not in lifecycle
    assert "formalSelfTestAssertion" not in lifecycle
