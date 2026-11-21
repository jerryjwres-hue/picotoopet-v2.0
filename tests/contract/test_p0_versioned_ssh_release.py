"""Real Windows 2.3 versioned film preview ships the reviewed manual SSH bootstrap."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RELEASE = ROOT / "windows/desktop/release"
BUILDER = ROOT / "windows/desktop/scripts/Build-Phase2WindowsRelease.ps1"
INSTALL = RELEASE / "Install-Phase2Prebuilt.ps1"
ROLLBACK = RELEASE / "Rollback-Phase2Prebuilt.ps1"
VERIFY = RELEASE / "Verify-Phase2Prebuilt.ps1"
COMMON = RELEASE / "Phase2Prebuilt.Common.ps1"
LIFECYCLE = ROOT / "windows/desktop/scripts/Test-Phase2WindowsRelease.ps1"
NATIVE_CI = ROOT / ".github/workflows/windows-ui-preview-release.yml"


def test_builder_binds_secure_ssh_scripts_to_versioned_hashed_payload() -> None:
    """连接脚本在 manifest 文件枚举之前复制和自检，不随 Full 桌宠包发布。"""

    text = BUILDER.read_text(encoding="utf-8-sig")
    # 安全连接脚本必须先进入 payload，才能包含在逐文件 SHA256 发布清单。
    # 不以 PowerShell 的续行符作为定位依据：其语法是反引号而非反斜杠。
    connection = text.index('$connectionOutput = Join-Path $payloadRoot')
    native_ssh_test = text.index('Start-SecureMacTunnel.ps1"), "-SelfTest"')
    files = text.index('$files = @(')
    assert connection < native_ssh_test < files
    assert 'Join-Path $payloadRoot "tools\\connection"' in text
    assert 'Join-Path $connectionOutput "Start-SecureMacTunnel.ps1"' in text
    assert 'Join-Path $connectionOutput $name' in text
    assert '"CONNECT_MAC_SECURE.vbs", "Start-SecureMacTunnel.ps1"' in text
    assert 'secure_tunnel_package = ($ValidationScope -eq "UiPreview")' in text
    assert "-SelfTest" in text
    assert "windows-ui-preview" in text


def test_shortcut_never_autostarts_ssh_and_is_bound_to_current_version() -> None:
    """只在显式点击开始菜单入口时启动；不接入 Windows Startup。"""

    text = COMMON.read_text(encoding="utf-8-sig")
    for expected in (
        "function Set-PicotooTunnelShortcut",
        "function Assert-PicotooTunnelShortcut",
        "function Get-PicotooTunnelShortcutPath",
        "Start Menu",
        "CONNECT_MAC_SECURE.vbs",
        "Start-SecureMacTunnel.ps1",
        "System32\\wscript.exe",
        "P0_VERSIONED_SSH_SHORTCUT_WRONG_TARGET",
    ):
        assert expected in text
    setter = text[text.index("function Set-PicotooTunnelShortcut"):text.index("function Assert-PicotooTunnelShortcut")]
    assert "Start-Process" not in setter
    assert "ssh.exe" not in setter
    assert "Startup" not in setter


def test_installer_and_rollback_restore_ssh_shortcut_without_worker_start() -> None:
    """指针提交后更新对应快捷方式，失败时恢复上一个已验证路径。"""

    install = INSTALL.read_text(encoding="utf-8-sig")
    rollback = ROLLBACK.read_text(encoding="utf-8-sig")
    assert "Set-PicotooTunnelShortcut -VersionRoot $finalPath" in install
    assert "Assert-PicotooTunnelShortcut -VersionRoot $finalPath" in install
    assert "Set-PicotooTunnelShortcut -VersionRoot $oldVersionRoot" in install
    assert "if ($script:StrictP0Activation) {\n        # 仅影视预览恢复 SSH 入口" in install
    assert "Set-PicotooTunnelShortcut -VersionRoot ([string]$previous.path)" in rollback
    assert "Set-PicotooTunnelShortcut -VersionRoot ([string]$current.path)" in rollback
    assert "Assert-PicotooTunnelShortcut -VersionRoot ([string]$previous.path)" in rollback
    assert "P0_PREVIEW_ACTIVE_GPU_WORKER_NO_FORCE_KILL" in install
    assert "P0_ROLLBACK_HOLD_NOT_ARMED" in rollback


def test_verifier_and_native_lifecycle_require_installed_shortcut_identity() -> None:
    """不能以 ZIP 内有 SSH 脚本替代已经安装且指向当前版本的真实入口。"""

    verifier = VERIFY.read_text(encoding="utf-8-sig")
    native = LIFECYCLE.read_text(encoding="utf-8-sig")
    assert "P0_VERSIONED_SSH_MANIFEST_MISSING" in verifier
    assert "Assert-PicotooTunnelShortcut -VersionRoot ([string]$current.path)" in verifier
    assert native.count("Assert-PicotooTunnelShortcut -VersionRoot") >= 4
    assert "-ValidationScope UiPreview" in NATIVE_CI.read_text(encoding="utf-8")


def test_native_release_builder_publishes_before_running_its_wpf_smoke() -> None:
    """发布时不得让前一个 WPF smoke 占用 DLL 后再编译同一项目。"""

    builder = BUILDER.read_text(encoding="utf-8-sig")
    first_publish = builder.index('    "publish", $appProject')
    ui_smoke = builder.index('Invoke-NativeCommand -FilePath $dotnet -Arguments $smokeArguments')
    full_pet_smoke = builder.index('"--desktop-pet-acceptance-only"')
    app_self_test = builder.index('Invoke-NativeCommand -FilePath $appExecutable -Arguments @(')

    # 先构建发布，再运行现有两个 no-build smoke；之后不得再编译。
    assert first_publish < ui_smoke < app_self_test
    assert first_publish < full_pet_smoke < app_self_test
    smoke_args = builder.index('$smokeArguments = @(')
    assert first_publish < smoke_args < ui_smoke
    assert "$smokeArguments = @($smokeDll)" in builder[smoke_args:ui_smoke]
    assert '"--ui-interaction-only"' in builder[smoke_args:ui_smoke]
    assert "P0_RELEASE_SMOKE_COMPLETION_MARKER_MISSING" in builder[ui_smoke:app_self_test]


def test_native_publish_cannot_hang_on_inherited_smoke_stdout_pipes() -> None:
    """后台测试子进程可继承管道，发布命令不能无界等待 ReadToEndAsync。"""

    builder = BUILDER.read_text(encoding="utf-8-sig")
    native = builder[
        builder.index("function Invoke-NativeCommand {"):
        builder.index("function Write-Utf8NoBom {")
    ]

    # 非捕获命令直接向 CI 控制台输出，不持有可能被子进程继承的匿名管道。
    assert "[switch]$CaptureOutput" in native
    assert "$startInfo.RedirectStandardOutput = [bool]$CaptureOutput" in native
    assert "$startInfo.RedirectStandardError  = [bool]$CaptureOutput" in native
    assert "if ($CaptureOutput) {" in native
    assert "-not $stdoutTask.Wait(5000)" in native
    assert "-not $stderrTask.Wait(5000)" in native

    # 禁止再调用无参数 WaitForExit() 或无界 stdoutTask.GetResult()。
    assert "$process.WaitForExit()" not in native
    assert "$process.WaitForExit($TimeoutSeconds * 1000)" in native
    assert 'Invoke-NativeCommand -FilePath $dotnet -Arguments @("--version") -WorkingDirectory $desktopRoot -CaptureOutput' in builder
    # SDK 版本读取与直接执行测试 DLL 均为显式有界捕获。
    assert builder.count("-CaptureOutput") == 3
    assert "native_smoke_exit    = [int]$smokeResult.ExitCode" in builder
    assert "native_smoke_marker  = $smokeMarker" in builder


def test_native_release_reuses_validated_ui_smoke_without_second_wpf_run() -> None:
    """原生构建器已执行 UI 冒烟测试，CI 只能核对凭据，不能重复启动 WPF。"""

    workflow = NATIVE_CI.read_text(encoding="utf-8")
    builder = BUILDER.read_text(encoding="utf-8-sig")
    section_start = workflow.index("      - name: Verify completed builder smoke")
    section_end = workflow.index("      - name: Verify P0 preview ZIP", section_start)
    verification = workflow[section_start:section_end]

    # 必须由构建器运行真实 UI-only smoke，成功后才写入发布报告。
    assert "Invoke-NativeCommand -FilePath $dotnet -Arguments $smokeArguments" in builder
    assert '"--ui-interaction-only"' in builder
    assert verification.count("Get-CimInstance Win32_Process") == 1
    assert "P0_RELEASE_BUILDER_SMOKE_PROVENANCE_MISMATCH" in verification
    assert "P0_RELEASE_SMOKE_PROCESS_LEFT_RUNNING" in verification
    assert "dotnet run" not in verification
    assert "PicotooPet.Desktop.Core.SmokeTests*" in verification


def test_pull_request_native_release_runs_when_security_or_contract_gates_change() -> None:
    """PR 对 Windows 合同/安全门禁的修改也必须重验真实发布，不可漏跑。"""

    workflow = NATIVE_CI.read_text(encoding="utf-8")
    section = workflow.split("  pull_request:", 1)[1].split("  workflow_dispatch:", 1)[0]
    assert '      - "windows/desktop/**"' in section
    assert '      - "tests/contract/**"' in section
    assert '      - "tests/security/**"' in section


def test_release_workflow_has_no_duplicated_or_truncated_job_sections() -> None:
    """确保 YAML 不会因字符串替换而复制整段 job 或截断尾部。"""

    workflow = NATIVE_CI.read_text(encoding="utf-8")
    assert workflow.count("  windows-ui-preview:") == 1
    assert workflow.count("      - name: Build installable Windows UI Preview") == 1
    assert workflow.count("      - name: Verify completed builder smoke") == 1
    assert workflow.count("      - name: Verify P0 preview ZIP") == 1
    assert workflow.count("      - name: Verify install upgrade recovery rollback lifecycle") == 1
    assert workflow.count("      - name: Publish Preview run provenance to source commit") == 1
    assert workflow.rstrip().endswith("});")
