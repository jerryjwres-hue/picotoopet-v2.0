"""Phase 2 Windows Desktop 安装、验证与回滚包契约。"""

from __future__ import annotations

from pathlib import Path

ROOT    = Path(__file__).resolve().parents[2]
DESKTOP = ROOT / "windows/desktop"
SCRIPTS = DESKTOP / "scripts"


def read(relative: str) -> str:
    """按 UTF-8-SIG 读取脚本，兼容 PowerShell 5.1 BOM。"""

    return (DESKTOP / relative).read_text(encoding="utf-8-sig")


def test_double_click_entry_points_are_hidden_and_complete() -> None:
    """安装、验证和回滚必须提供无终端双击入口。"""

    for name in (
        "INSTALL_PHASE2_WINDOWS.vbs",
        "VERIFY_PHASE2_WINDOWS.vbs",
        "ROLLBACK_PHASE2_WINDOWS.vbs",
    ):
        path = SCRIPTS / name
        assert path.is_file(), path
        text = path.read_text(encoding="utf-8-sig")
        assert "powershell.exe" in text
        assert ", 0, True" in text or ", 0, False" in text


def test_powershell_scripts_are_bom_encoded_for_windows_powershell_51() -> None:
    """直接面向用户的仓库脚本必须有 BOM；预编译包脚本由构建器写入 BOM。"""

    expected = {
        "Install-Phase2Windows.ps1",
        "Verify-Phase2Windows.ps1",
        "Rollback-Phase2Windows.ps1",
        "Build-Phase2Windows.ps1",
    }
    assert expected <= {path.name for path in SCRIPTS.glob("*.ps1")}
    for name in expected:
        path = SCRIPTS / name
        assert path.read_bytes().startswith(b"\xef\xbb\xbf"), path

    builder = read("scripts/Build-Phase2WindowsRelease.ps1")
    assert "function Copy-ReleaseFile" in builder
    assert "[System.Text.UTF8Encoding]::new($true)" in builder
    for name in (
        "Install-Phase2Prebuilt.ps1",
        "Verify-Phase2Prebuilt.ps1",
        "Rollback-Phase2Prebuilt.ps1",
        "Phase2Prebuilt.Common.ps1",
    ):
        assert name in builder


def test_installer_uses_official_sdk_self_contained_publish_and_version_switch() -> None:
    """安装器必须使用官方 SDK、独立发布和可回滚版本指针。"""

    installer = read("scripts/Install-Phase2Windows.ps1")

    assert "Microsoft.DotNet.SDK.10" in installer
    assert "--self-contained" in installer
    assert "PublishSingleFile=true" in installer
    assert "PublishReadyToRun=true" in installer
    assert "versions" in installer
    assert "current_version.json" in installer
    assert "previous_version.json" in installer
    assert "Get-FileHash" in installer
    assert "Picotoo Pet AI.lnk" in installer


def test_installer_serializes_concurrent_runs_and_predeclares_report_fields() -> None:
    """重复双击不得并发覆盖版本目录，StrictMode 下也不能动态添加报告字段。"""

    installer = read("scripts/Install-Phase2Windows.ps1")

    assert "Global\\PicotooPetV2.Phase2Installer" in installer
    assert "WaitOne(0)" in installer
    assert "$PID" in installer
    assert "executable_sha256 = $null" in installer


def test_verifier_runs_real_diagnostics_and_exports_machine_readable_report() -> None:
    """验证器必须执行真实客户端诊断并输出分位数报告。"""

    verifier = read("scripts/Verify-Phase2Windows.ps1")
    diagnostics = read(
        "tools/PicotooPet.Desktop.Diagnostics/Program.cs"
    )

    assert "PicotooPet.Desktop.Diagnostics" in verifier
    assert "phase2-windows-verification.json" in verifier
    assert "p95" in diagnostics.lower()
    assert "p99" in diagnostics.lower()
    assert "CreateTaskAsync" in diagnostics
    assert "EventStreamClient" in diagnostics
    assert "CredentialManagerTokenStore" in diagnostics
    assert "TaskSamples" in diagnostics
    assert "task_submit" in diagnostics
    assert "task_event" in diagnostics
    assert 'RestSamples = 500' in verifier
    assert 'TaskSamples = 500' in verifier
    assert 'SocketSamples = 500' in verifier


def test_rollback_never_deletes_user_settings_or_credentials() -> None:
    """回滚只能切换程序版本，不得删除设置、日志或 Credential Manager 数据。"""

    rollback = read("scripts/Rollback-Phase2Windows.ps1")

    assert "previous_version.json" in rollback
    assert "current_version.json" in rollback
    assert "settings.json" not in rollback
    assert "CredentialManager" not in rollback
    assert "Remove-Item $dataRoot" not in rollback


def test_phase2_install_and_real_machine_acceptance_docs_exist() -> None:
    """交付必须包含中文安装和实机性能验收说明。"""

    for relative in (
        "docs/phase2/INSTALLATION_GUIDE_CN.md",
        "docs/phase2/REAL_MACHINE_ACCEPTANCE_CN.md",
    ):
        path = ROOT / relative
        assert path.is_file(), path
        assert len(path.read_text(encoding="utf-8")) > 800


def test_diagnostics_project_has_no_third_party_packages() -> None:
    """诊断工具必须复用核心客户端且不增加第三方运行时依赖。"""

    project = read(
        "tools/PicotooPet.Desktop.Diagnostics/PicotooPet.Desktop.Diagnostics.csproj"
    )
    assert "net10.0-windows" in project
    assert "ProjectReference" in project
    assert "PackageReference" not in project


def test_native_tools_do_not_trigger_powershell51_nativecommanderror() -> None:
    """WinGet 与 dotnet 必须通过真实退出码判断，不把正常 stderr 当成脚本错误。"""

    installer = read("scripts/Install-Phase2Windows.ps1")
    builder   = read("scripts/Build-Phase2Windows.ps1")

    for script in (installer, builder):
        assert "Invoke-NativeCommand" in script
        assert "RedirectStandardOutput" in script
        assert "RedirectStandardError" in script
        assert "& $dotnet publish" not in script
    assert "& $winget.Source install" not in installer


def test_scripts_and_diagnostics_have_balanced_delimiters() -> None:
    """缺少 Windows 编译器时先防止明显的脚本和 C# 截断错误。"""

    import re

    paths = list(SCRIPTS.glob("*.ps1")) + list(
        (DESKTOP / "tools/PicotooPet.Desktop.Diagnostics").glob("*.cs")
    )
    powershell_scrub = re.compile(
        r'@?"(?:`.|""|[^"])*"|\'(?:\'\'|[^\'])*\'|#[^\n]*',
        re.DOTALL,
    )
    csharp_scrub = re.compile(
        r'@?"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|//[^\n]*',
        re.DOTALL,
    )
    pairs = {"(": ")", "[": "]", "{": "}"}
    for path in paths:
        scrub = powershell_scrub if path.suffix.lower() == ".ps1" else csharp_scrub
        cleaned = scrub.sub("", path.read_text(encoding="utf-8-sig"))
        stack: list[str] = []
        for character in cleaned:
            if character in pairs:
                stack.append(character)
            elif character in pairs.values():
                assert stack, f"{path}: 多余的 {character}"
                opening = stack.pop()
                assert pairs[opening] == character, path
        assert not stack, f"{path}: 未闭合 {stack}"


def test_verifier_always_writes_schema_complete_report_and_validates_all_binaries() -> None:
    """安装缺失或校验异常时也必须产出统一结构，且主程序与诊断器都要校验。"""

    verifier = read("scripts/Verify-Phase2Windows.ps1")

    assert "function New-VerificationReport" in verifier
    assert "function Write-JsonAtomic" in verifier
    assert "environment" in verifier
    assert "metrics" in verifier
    assert "errors" in verifier
    assert "diagnostic_sha256" in verifier
    assert "finally" in verifier
    assert "Start-Process -FilePath \"notepad.exe\"" in verifier


def test_installer_restores_previous_pointer_when_activation_fails() -> None:
    """版本指针切换后的任意激活失败必须恢复上一版本，避免留下不可启动状态。"""

    installer = read("scripts/Install-Phase2Windows.ps1")

    assert "$previousCurrent" in installer and "= $null" in installer
    assert "$activationStarted = $false" in installer
    assert "Restore-PreviousActivation" in installer
    assert "diagnostic_sha256" in installer


def test_rollback_reports_failures_and_validates_diagnostic_binary() -> None:
    """回滚失败也必须有报告，并在切换前校验诊断器完整性。"""

    rollback = read("scripts/Rollback-Phase2Windows.ps1")

    assert "diagnostic_sha256" in rollback
    assert 'status            = "running"' in rollback
    assert "catch" in rollback
    assert "finally" in rollback
    assert "Write-JsonAtomic" in rollback


def test_solution_includes_diagnostics_project_for_full_release_build() -> None:
    """解决方案级构建必须覆盖诊断器，不能只依赖安装脚本单独发布。"""

    solution = (DESKTOP / "PicotooPet.Desktop.sln").read_text(encoding="utf-8-sig")
    assert "PicotooPet.Desktop.Diagnostics" in solution
    assert "tools\\PicotooPet.Desktop.Diagnostics\\PicotooPet.Desktop.Diagnostics.csproj" in solution


def test_windows_build_enforces_nullable_determinism_and_zero_warnings() -> None:
    """Release 构建必须启用空值分析、确定性输出并把警告作为失败。"""

    props = (DESKTOP / "Directory.Build.props").read_text(encoding="utf-8")
    assert "<Nullable>enable</Nullable>" in props
    assert "<ImplicitUsings>enable</ImplicitUsings>" in props
    assert "<LangVersion>14.0</LangVersion>" in props
    assert "<TreatWarningsAsErrors>true</TreatWarningsAsErrors>" in props
    assert "<Deterministic>true</Deterministic>" in props


def test_installer_replaces_running_desktop_without_parallel_instances() -> None:
    """升级时必须停止旧桌面并在新版本失败时重新启动旧版本。"""

    installer = read("scripts/Install-Phase2Windows.ps1")
    assert 'Get-Process -Name "Picotoo Pet AI"' in installer
    assert "Stop-Process -Force" in installer
    assert "Start-Process -FilePath $previousCurrent.executable" in installer
