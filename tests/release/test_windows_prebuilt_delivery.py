from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
DESKTOP = ROOT / "windows" / "desktop"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def test_known_csharp_build_break_is_fixed() -> None:
    source = read(
        DESKTOP
        / "src"
        / "PicotooPet.Desktop.Core"
        / "Networking"
        / "MacCoreClient.cs"
    )
    assert "baseUri.AbsoluteUri.EndsWith('/')" in source
    assert "EndsWith('/', StringComparison.Ordinal)" not in source
    assert 'EndsWith("/", StringComparison.Ordinal)' not in source


def test_windows_ci_builds_slice_d_on_native_runner() -> None:
    workflow_path = ROOT / ".github" / "workflows" / "windows-phase2-release.yml"
    workflow = yaml.safe_load(read(workflow_path))
    job = workflow["jobs"]["windows-release"]
    assert job["runs-on"] == "windows-2025"
    assert job["timeout-minutes"] <= 60
    steps = job["steps"]
    uses = [step.get("uses") for step in steps if "uses" in step]
    assert "actions/checkout@v6" in uses
    assert "actions/setup-python@v6" in uses
    assert "actions/setup-dotnet@v6" in uses
    assert "actions/upload-artifact@v7" in uses
    run_text = "\n".join(step.get("run", "") for step in steps)
    assert "pytest tests/release/test_windows_prebuilt_delivery.py" in run_text
    assert "Test-TaskCenterLegacyBindingRegression.ps1" in run_text
    assert "Build-Phase2WindowsRelease.ps1 -Version $version" in run_text
    assert "2.3.0-slice-d-diagnostic" in run_text
    assert "Invoke-Phase2WindowsReleaseLifecycleGate.ps1" in run_text


def test_user_installer_only_installs_prebuilt_payload() -> None:
    installer = read(DESKTOP / "release" / "Install-Phase2Prebuilt.ps1")
    forbidden = (
        "dotnet publish",
        "dotnet run",
        "winget",
        "Microsoft.DotNet.SDK",
        "PicotooPet.Desktop.csproj",
    )
    for text in forbidden:
        assert text not in installer
    assert "release-manifest.json" in installer
    assert "install-state.json" in installer
    assert "Get-FileHash" in installer
    assert "Write-InstallProgress" in installer
    assert "Start-Transcript" not in installer


def test_release_json_is_read_as_strict_utf8_on_windows_powershell_51() -> None:
    """机器 JSON 必须绕过 Windows PowerShell 5.1 的区域默认编码。"""

    scripts = (
        DESKTOP / "release" / "Install-Phase2Prebuilt.ps1",
        DESKTOP / "release" / "Verify-Phase2Prebuilt.ps1",
        DESKTOP / "release" / "Rollback-Phase2Prebuilt.ps1",
    )
    for path in scripts:
        text = read(path)
        assert "function Read-JsonUtf8" in text, path
        assert "[System.IO.File]::ReadAllText" in text, path
        assert "[System.Text.UTF8Encoding]::new($false, $true)" in text, path
        assert "Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json" not in text, path


def test_installer_vbs_is_ascii_without_bom_and_visible() -> None:
    path = DESKTOP / "release" / "INSTALL_PHASE2_WINDOWS.vbs"
    payload = path.read_bytes()
    assert not payload.startswith(b"\xef\xbb\xbf")
    payload.decode("ascii")
    text = payload.decode("ascii")
    assert "shell.Run(command, 1, True)" in text


def test_desktop_has_headless_self_test_with_diagnostic_smoke() -> None:
    app = read(DESKTOP / "src" / "PicotooPet.Desktop" / "App.xaml.cs")
    self_test = read(
        DESKTOP / "src" / "PicotooPet.Desktop" / "Services" / "AppSelfTest.cs"
    )
    smoke = read(
        DESKTOP
        / "tests"
        / "PicotooPet.Desktop.Core.SmokeTests"
        / "DiagnosticSnapshotSmokeTests.cs"
    )
    program = read(
        DESKTOP / "tests" / "PicotooPet.Desktop.Core.SmokeTests" / "Program.cs"
    )
    assert '"--self-test"' in app
    assert "AppSelfTest.Run" in app
    assert "PHASE2_DESKTOP_SELF_TEST=PASS" in self_test
    assert "DiagnosticSnapshotSmokeTests.RunAsync" in program
    assert "system-diagnostic-snapshot" in smoke
    assert "Idempotency-Key" in smoke
    assert "DiagnosticObservationDelays" in smoke


def test_release_builder_generates_single_root_manifest_and_zip() -> None:
    builder = read(DESKTOP / "scripts" / "Build-Phase2WindowsRelease.ps1")
    assert "release-manifest.json" in builder
    assert "Compress-Archive -LiteralPath $packageRoot" in builder
    assert "Compress-Archive -Path (Join-Path $packageRoot \"*\")" not in builder
    assert "PicotooPet-Phase2-Windows-Prebuilt" in builder
    assert "[string]$Version" in builder
    assert "native_ci_verified" in builder
    assert "user_install_allowed" in builder
    assert "source_head" in builder
    assert "source_ref" in builder
    assert "--self-test" in builder


def test_release_verifier_checks_payload_process_shortcuts_and_lifecycle() -> None:
    verifier = read(DESKTOP / "scripts" / "Test-Phase2WindowsRelease.ps1")
    assert "Get-FileHash" in verifier
    assert "release-manifest.json" in verifier
    assert "--self-test" in verifier
    assert "ExitCode" in verifier
    assert "-PreflightOnly" in verifier
    assert "-ActivationSelfTest" in verifier
    assert "-OfflinePackageOnly" in verifier
    assert "Rollback-Phase2Prebuilt.ps1" in verifier
    assert "DesktopDirectory" in verifier
    assert "OneDrive" in verifier
    assert "fixture-evidence" in verifier
    assert "phase2-prebuilt-install" in verifier
    assert "phase2-windows-verification" in verifier
    assert "phase2-rollback" in verifier


def test_shortcut_resolution_is_shared_across_install_verify_and_rollback() -> None:
    common_path = DESKTOP / "release" / "Phase2Prebuilt.Common.ps1"
    common = read(common_path)
    assert "function Get-PicotooShortcutPaths" in common
    assert "DesktopDirectory" in common
    assert "Microsoft\\Windows\\Start Menu\\Programs\\Picotoo Pet AI.lnk" in common
    assert "Microsoft\\Windows\\Start Menu\\Programs\\Startup\\Picotoo Pet AI.lnk" in common
    assert "function Set-PicotooShortcuts" in common
    assert "function Assert-PicotooShortcuts" in common
    assert "TargetPath" in common

    for name in (
        "Install-Phase2Prebuilt.ps1",
        "Verify-Phase2Prebuilt.ps1",
        "Rollback-Phase2Prebuilt.ps1",
    ):
        script = read(DESKTOP / "release" / name)
        assert '"Phase2Prebuilt.Common.ps1"' in script, name
        assert ". $commonScript" in script, name


def test_verify_and_rollback_enforce_manifest_size_and_shortcut_targets() -> None:
    verifier = read(DESKTOP / "release" / "Verify-Phase2Prebuilt.ps1")
    rollback = read(DESKTOP / "release" / "Rollback-Phase2Prebuilt.ps1")

    for script in (verifier, rollback):
        assert "size_bytes" in script
        assert "Assert-PicotooShortcuts" in script
        assert "shortcut_paths" in script
        assert "shortcuts_verified" in script

    assert "Restore-RollbackOrigin" in rollback
    assert "[string]$current.executable" in rollback


def test_release_workflow_uploads_slice_d_lifecycle_evidence() -> None:
    workflow = read(ROOT / ".github" / "workflows" / "windows-phase2-release.yml")
    assert "tests/release/test_windows_prebuilt_delivery.py" in workflow
    assert "fixture-evidence/**" in workflow
    assert "PICOTOO_SOURCE_HEAD_SHA" in workflow
    assert "PICOTOO_SOURCE_REF" in workflow
    assert "PicotooPet-Phase23-SliceD-Windows-Prebuilt" in workflow


def test_windows_task_dialogs_do_not_render_raw_exception_messages() -> None:
    code_behind = read(
        DESKTOP / "src" / "PicotooPet.Desktop" / "Views" / "Pages" / "TaskCenterPage.xaml.cs"
    )
    session = read(
        DESKTOP / "src" / "PicotooPet.Desktop" / "Services" / "ControlCenterSession.Tasks.cs"
    )
    assert "exception.Message" not in code_behind
    assert "详细信息已写入脱敏日志" in code_behind
    assert "_logger.Error" in session


def test_new_powershell_scripts_have_balanced_delimiters_and_safe_wildcards() -> None:
    import re

    paths = [
        DESKTOP / "scripts" / "Build-Phase2WindowsRelease.ps1",
        DESKTOP / "scripts" / "Test-Phase2WindowsRelease.ps1",
        DESKTOP / "scripts" / "Test-TaskCenterLegacyBindingRegression.ps1",
        DESKTOP / "release" / "Phase2Prebuilt.Common.ps1",
        DESKTOP / "release" / "Install-Phase2Prebuilt.ps1",
        DESKTOP / "release" / "Verify-Phase2Prebuilt.ps1",
        DESKTOP / "release" / "Rollback-Phase2Prebuilt.ps1",
    ]
    scrub = re.compile(
        r'@?"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|#[^\n]*',
        re.DOTALL,
    )
    pairs = {"(": ")", "[": "]", "{": "}"}
    for path in paths:
        text = read(path)
        assert "-LiteralPath (Join-Path $payloadRoot \"*\")" not in text
        assert (
            "Compress-Archive -LiteralPath" not in text
            or path.name == "Build-Phase2WindowsRelease.ps1"
        )
        cleaned = scrub.sub("", text)
        stack: list[str] = []
        for character in cleaned:
            if character in pairs:
                stack.append(character)
            elif character in pairs.values():
                assert stack, f"{path}: unexpected {character}"
                opening = stack.pop()
                assert pairs[opening] == character, path
        assert not stack, f"{path}: unclosed {stack}"


def test_all_release_vbs_files_are_ascii_without_bom() -> None:
    for path in (DESKTOP / "release").glob("*.vbs"):
        payload = path.read_bytes()
        assert not payload.startswith(b"\xef\xbb\xbf"), path
        payload.decode("ascii")
