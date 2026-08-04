from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from scripts.verify_project_goal_integrity import (
    GoalIntegrityError,
    verify_windows_package,
)


ROOT = Path(__file__).resolve().parents[2]
BUILDER = ROOT / "windows" / "desktop" / "scripts" / "Build-Phase2WindowsRelease.ps1"
CONTRACT = ROOT / "contracts" / "release" / "project-goal-invariants.json"


def _goal_gate_script() -> bytes:
    return (
        "$manifest = Read-JsonUtf8 -Path $manifestPath\r\n"
        "    # PICOTOO_GOAL_INTEGRITY_GATE_V1\r\n"
        '        "release_type" = "prebuilt"\r\n'
        '        "target" = "win-x64"\r\n'
        '        "delivery_surface" = "existing-native-wpf-desktop"\r\n'
        '        "ui_framework" = "WPF"\r\n'
        '        "entry_executable" = "Picotoo Pet AI.exe"\r\n'
        '        "integration_target" = "TaskCenter"\r\n'
        '        "github_repository" = "jerryjwres-hue/picotoopet-v2.0"\r\n'
        '        "source_build_on_user_pc" = $false\r\n'
        '        "browser_ui" = $false\r\n'
        '        "local_http_ui" = $false\r\n'
        '        "native_ci_verified" = $true\r\n'
        '        "user_install_allowed" = $true\r\n'
        '        "github_run_id"\r\n'
        '        "github_run_attempt"\r\n'
        '        "github_workflow_ref"\r\n'
        '        throw "GOAL_INTEGRITY_VIOLATION: forbidden web UI payload"\r\n'
    ).encode("utf-8-sig")


def _manifest() -> dict[str, object]:
    return {
        "schema_version": "2.3.0",
        "release_type": "prebuilt",
        "version": "2.3.0-slice-d-native-provenance-test",
        "target": "win-x64",
        "native_ci_verified": True,
        "user_install_allowed": True,
        "source_build_on_user_pc": False,
        "delivery_surface": "existing-native-wpf-desktop",
        "ui_framework": "WPF",
        "entry_executable": "Picotoo Pet AI.exe",
        "integration_target": "TaskCenter",
        "browser_ui": False,
        "local_http_ui": False,
        "github_repository": "jerryjwres-hue/picotoopet-v2.0",
        "source_head": "a" * 40,
        "source_ref": "feature/phase23-slice-d-diagnostic-snapshot-release",
        "build_commit": "b" * 40,
    }


def _make_package(tmp_path: Path, manifest: dict[str, object]) -> Path:
    root = "candidate"
    package = tmp_path / "candidate.zip"
    files = {
        f"{root}/release-manifest.json": json.dumps(manifest).encode("utf-8"),
        f"{root}/payload/Picotoo Pet AI.exe": b"MZ-native-wpf",
        f"{root}/payload/tools/diagnostics/PicotooPet.Desktop.Diagnostics.exe": b"MZ-diagnostic",
        f"{root}/INSTALL_PHASE2_WINDOWS.vbs": b"ascii",
        f"{root}/VERIFY_PHASE2_WINDOWS.vbs": b"ascii",
        f"{root}/ROLLBACK_PHASE2_WINDOWS.vbs": b"ascii",
        f"{root}/Install-Phase2Prebuilt.ps1": _goal_gate_script(),
        f"{root}/Verify-Phase2Prebuilt.ps1": _goal_gate_script(),
    }
    with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return package


def test_installable_package_requires_native_ci_run_provenance(tmp_path: Path) -> None:
    package = _make_package(tmp_path, _manifest())

    with pytest.raises(GoalIntegrityError, match="github_run_id|原生 CI 溯源"):
        verify_windows_package(package)


def test_builder_records_native_ci_run_provenance() -> None:
    source = BUILDER.read_text(encoding="utf-8-sig")

    assert "github_run_id       = $env:GITHUB_RUN_ID" in source
    assert "github_run_attempt  = $env:GITHUB_RUN_ATTEMPT" in source
    assert "github_workflow_ref = $env:GITHUB_WORKFLOW_REF" in source
    assert "github_repository   = $env:GITHUB_REPOSITORY" in source


def test_goal_contract_freezes_repository_and_provenance_fields() -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    windows = contract["windows"]

    assert windows["required_manifest_values"]["github_repository"] == (
        "jerryjwres-hue/picotoopet-v2.0"
    )
    assert windows["required_native_ci_provenance_fields"] == [
        "github_run_id",
        "github_run_attempt",
        "github_workflow_ref",
        "source_head",
        "source_ref",
        "build_commit",
    ]
