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


def test_windows_ci_builds_on_native_runner() -> None:
    workflow_path = ROOT / ".github" / "workflows" / "windows-phase2-release.yml"
    workflow = yaml.safe_load(read(workflow_path))
    job = workflow["jobs"]["windows-release"]
    assert job["runs-on"] == "windows-2025"
    steps = job["steps"]
    uses = [step.get("uses") for step in steps if "uses" in step]
    assert "actions/checkout@v6" in uses
    assert "actions/setup-dotnet@v6" in uses
    assert "actions/upload-artifact@v7" in uses
    run_text = "\n".join(step.get("run", "") for step in steps)
    assert "Build-Phase2WindowsRelease.ps1" in run_text
    assert "Test-Phase2WindowsRelease.ps1" in run_text


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


def test_installer_vbs_is_ascii_without_bom_and_visible() -> None:
    path = DESKTOP / "release" / "INSTALL_PHASE2_WINDOWS.vbs"
    payload = path.read_bytes()
    assert not payload.startswith(b"\xef\xbb\xbf")
    payload.decode("ascii")
    text = payload.decode("ascii")
    assert "shell.Run(command, 1, True)" in text


def test_desktop_has_headless_self_test() -> None:
    app = read(DESKTOP / "src" / "PicotooPet.Desktop" / "App.xaml.cs")
    self_test = read(
        DESKTOP / "src" / "PicotooPet.Desktop" / "Services" / "AppSelfTest.cs"
    )
    assert '"--self-test"' in app
    assert "AppSelfTest.Run" in app
    assert "PHASE2_DESKTOP_SELF_TEST=PASS" in self_test


def test_release_builder_generates_manifest_and_zip() -> None:
    builder = read(DESKTOP / "scripts" / "Build-Phase2WindowsRelease.ps1")
    assert "release-manifest.json" in builder
    assert "Compress-Archive" in builder
    assert "PicotooPet-Phase2-Windows-Prebuilt" in builder
    assert "--self-test" in builder


def test_release_verifier_checks_payload_and_process_exit() -> None:
    verifier = read(DESKTOP / "scripts" / "Test-Phase2WindowsRelease.ps1")
    assert "Get-FileHash" in verifier
    assert "release-manifest.json" in verifier
    assert "--self-test" in verifier
    assert "ExitCode" in verifier


def test_new_powershell_scripts_have_balanced_delimiters_and_safe_wildcards() -> None:
    import re

    paths = [
        DESKTOP / "scripts" / "Build-Phase2WindowsRelease.ps1",
        DESKTOP / "scripts" / "Test-Phase2WindowsRelease.ps1",
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
        assert "Compress-Archive -LiteralPath" not in text
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
