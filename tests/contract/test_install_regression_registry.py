"""真实安装事故的永久回归门。"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "contracts" / "release" / "install-regression-cases.json"


def read(path: Path) -> str:
    """按 UTF-8 读取发布源文件。"""

    return path.read_text(encoding="utf-8-sig")


def test_install_incident_registry_is_machine_readable_and_closed() -> None:
    """事故记录必须保持机器可读，且每项都映射到自动化门。"""

    payload = json.loads(read(REGISTRY))
    assert payload["schema_version"] == "1.0.0"
    assert payload["target_devices"]["mac"] == "Apple Silicon M4 / arm64"
    cases = {case["id"]: case for case in payload["cases"]}
    assert {
        "WIN-2026-08-01-UTF8-MANIFEST",
        "MAC-2026-08-02-SPACED-RUNTIME-PATH",
        "CROSS-PLATFORM-NO-USER-BUILD",
    }.issubset(cases)
    for case in cases.values():
        assert case["status"] == "closed"
        assert case["root_cause"]
        assert case["required_controls"]
        assert case["enforced_by"]


def test_windows_utf8_incident_cannot_regress() -> None:
    """Windows PowerShell 5.1 必须按严格 UTF-8 读取机器 JSON。"""

    desktop = ROOT / "windows" / "desktop"
    for path in (
        desktop / "release" / "Install-Phase2Prebuilt.ps1",
        desktop / "release" / "Verify-Phase2Prebuilt.ps1",
        desktop / "release" / "Rollback-Phase2Prebuilt.ps1",
    ):
        text = read(path)
        assert "function Read-JsonUtf8" in text
        assert "[System.IO.File]::ReadAllText" in text
        assert "[System.Text.UTF8Encoding]::new($false, $true)" in text
        assert "Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json" not in text

    package_gate = read(desktop / "scripts" / "Test-Phase2WindowsRelease.ps1")
    assert "& $installer -PackageRoot $tempRoot -PreflightOnly" in package_gate
    assert "phase2-prebuilt-install" in package_gate
    assert "preflight.status" in package_gate


def test_mac_spaced_path_incident_cannot_regress() -> None:
    """Mac 安装器和原生夹具必须覆盖 Application Support 空格路径。"""

    installer = read(
        ROOT / "deploy" / "macos" / "phase23" / "INSTALL_MAC_CORE_SLICE_B.command"
    )
    fixture = read(ROOT / "scripts" / "mac" / "phase23" / "Test-MacCoreSliceBFixture.sh")
    workflow = read(ROOT / ".github" / "workflows" / "macos-core-slice-b-ci.yml")

    assert 'python_version="$("$current_python" --version 2>&1)"' in installer
    assert '"$current_python" -m venv' in installer
    assert 'runtime_root="$temp_root/Application Support/PicotooPetV2"' in fixture
    assert "macos-15" in workflow
    assert "arch: arm64" in workflow
    assert "macos-15-intel" not in workflow
    assert "arch: x86_64" not in workflow


def test_release_jobs_keep_success_and_diagnostic_artifacts_separate() -> None:
    """失败证据不能冒充安装候选，成功包也不能因末尾失败而消失。"""

    mac_workflow = read(ROOT / ".github" / "workflows" / "macos-core-slice-b-ci.yml")
    assert "if: failure()" in mac_workflow
    assert "DIAGNOSTIC" in mac_workflow
    assert "Upload architecture-specific package and evidence" in mac_workflow

    windows_workflow = read(ROOT / ".github" / "workflows" / "windows-phase2-release.yml")
    assert "upload-artifact" in windows_workflow
    assert "Test-Phase2WindowsRelease.ps1" in windows_workflow


def test_user_installers_never_build_source() -> None:
    """用户安装器只消费预编译 payload，不得调用构建工具链。"""

    installer_texts = (
        read(ROOT / "windows" / "desktop" / "release" / "Install-Phase2Prebuilt.ps1"),
        read(ROOT / "deploy" / "macos" / "phase23" / "INSTALL_MAC_CORE_SLICE_B.command"),
    )
    forbidden = (
        "dotnet publish",
        "dotnet build",
        "pip wheel",
        "python -m build",
        "uv build",
        "cargo build",
    )
    for text in installer_texts:
        lowered = text.lower()
        for command in forbidden:
            assert command not in lowered
