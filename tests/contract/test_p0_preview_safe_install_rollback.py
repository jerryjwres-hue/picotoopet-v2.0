"""P0 WPF/Worker version lifecycle: HOLD-first, no force kill, no unknown rollback."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INSTALL = ROOT / "windows/desktop/release/Install-Phase2Prebuilt.ps1"
ROLLBACK = ROOT / "windows/desktop/release/Rollback-Phase2Prebuilt.ps1"
COMMON = ROOT / "windows/desktop/release/Phase2Prebuilt.Common.ps1"
BUILDER = ROOT / "windows/desktop/scripts/Build-Phase2WindowsRelease.ps1"
LIFECYCLE = ROOT / "windows/desktop/scripts/Test-Phase2WindowsRelease.ps1"
NATIVE = ROOT / ".github/workflows/windows-ui-preview-release.yml"


def test_preview_installer_never_force_kills_inflight_same_exe_worker() -> None:
    """旧正式版分支保持原行为，影视预览必须先拒绝运行中的 Worker。"""

    source = INSTALL.read_text(encoding="utf-8-sig")
    assert "$script:StrictP0Activation = ([string]$manifest.validation_scope" in source
    assert "P0_PREVIEW_ACTIVE_GPU_WORKER_NO_FORCE_KILL" in source
    assert "if ($script:StrictP0Activation)" in source
    assert "Get-CimInstance Win32_Process" in source
    assert "Get-Process -Name \"Picotoo Pet AI\" -ErrorAction SilentlyContinue | Stop-Process -Force" in source


def test_failed_preview_install_does_not_auto_restart_legacy_worker() -> None:
    """可恢复版本身份/快捷方式，但未知旧版启动不属于安全恢复。"""

    source = INSTALL.read_text(encoding="utf-8-sig")
    assert "$report.recovery_activation = 'BLOCKED_OLD_WORKER_NOT_AUTOSTARTED'" in source
    assert "$report.recovery_startup = 'DISABLED_UNVERIFIED_OLD_WORKER'" in source
    assert "$previousManifest.p0_hold_aware -eq $true" in source
    assert "Get-PicotooManagedShortcutFiles" in source
    assert "if ([string]$managed.location -eq 'startup')" in source
    assert source.index("$report.recovery_activation = 'BLOCKED_OLD_WORKER_NOT_AUTOSTARTED'") < (
        source.index("Invoke-ActivationCheck `", source.index("function Restore-PreviousActivation"))
    )


def test_preview_rollback_requires_armed_hold_and_verified_target_before_switch() -> None:
    """HOLD、目标模式与无人运行证据必须在修改版本指针之前验证。"""

    source = ROLLBACK.read_text(encoding="utf-8-sig")
    switch = source.index("$switched = $true")
    for required in (
        "P0_ROLLBACK_UNVERIFIED_OLD_WORKER_DENIED",
        "P0_ROLLBACK_HOLD_FIRST_REQUIRED",
        "P0_ROLLBACK_HOLD_NOT_ARMED",
        "P0_ROLLBACK_HOLD_REPARSE_FILE",
        "P0_PREVIEW_RUNNING_WORKER_ROLLBACK_BLOCKED",
    ):
        assert source.index(required) < switch
    assert "if ($script:StrictP0Rollback)" in source
    assert "$manifest.p0_hold_aware -ne $true" in source
    builder = BUILDER.read_text(encoding="utf-8-sig")
    assert 'p0_hold_aware        = ($ValidationScope -eq "UiPreview")' in builder


def test_native_release_lifecycle_exercises_both_rollback_negative_cases() -> None:
    """不能仅依赖源字符串；实际安装器在临时隔离用户账户跑负例。"""

    lifecycle = LIFECYCLE.read_text(encoding="utf-8-sig")
    workflow = NATIVE.read_text(encoding="utf-8")
    for marker in (
        "P0_PREVIEW_ROLLBACK_HOLD_AND_OLD_WORKER_NEGATIVES=PASS",
        "P0_PREVIEW_ROLLBACK_ALLOW_NOT_REFUSED",
        "P0_PREVIEW_ROLLBACK_UNVERIFIED_TARGET_ACCEPTED",
        "P0_PREVIEW_ROLLBACK_UNMARKED_TARGET_ACCEPTED",
        "P0_PREVIEW_FAILURE_MUST_NOT_AUTO_START_OLD_WORKER",
        "P0_PREVIEW_UNVERIFIED_LEGACY_AUTOSTART_DISABLED=PASS",
        "P0_LEGACY_STARTUP_SHORTCUT_STILL_PRESENT",
    ):
        assert marker in lifecycle
    assert "Test-Phase2WindowsRelease.ps1" in workflow
    assert "fix/p0-film-activation-no-worker-force-kill" in workflow


def test_prelaunch_hold_is_rechecked_at_last_moment_for_both_activation_paths() -> None:
    """安装/回滚复制完成后必须重读最新 HOLD，不能依赖旧检查的 TOCTOU 结果。"""

    common = COMMON.read_text(encoding="utf-8-sig")
    install = INSTALL.read_text(encoding="utf-8-sig")
    rollback = ROLLBACK.read_text(encoding="utf-8-sig")
    assert "function Assert-PicotooP0HoldForActivation" in common
    for required in (
        "P0_ACTIVATION_HOLD_FIRST_REQUIRED",
        "P0_ACTIVATION_HOLD_NOT_ARMED",
        "P0_ACTIVATION_HOLD_REPARSE_DIRECTORY",
        "P0_ACTIVATION_HOLD_REPARSE_FILE",
        "three-shot-acceptance.json",
    ):
        assert required in common
    assert "Assert-PicotooP0HoldForActivation" in install
    assert "Assert-PicotooP0HoldForActivation" in rollback
