from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from scripts.verify_project_goal_integrity import GoalIntegrityError, verify_windows_package


ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "contracts" / "release" / "project-goal-invariants.json"


def _gate_script() -> bytes:
    return (
        "$manifest = Read-JsonUtf8 -Path $manifestPath\r\n"
        "    # PICOTOO_GOAL_INTEGRITY_GATE_V1\r\n"
        '        "release_type" = "prebuilt"\r\n'
        '        "target" = "win-x64"\r\n'
        '        "source_build_on_user_pc" = $false\r\n'
        '        "delivery_surface" = "existing-native-wpf-desktop"\r\n'
        '        "ui_framework" = "WPF"\r\n'
        '        "entry_executable" = "Picotoo Pet AI.exe"\r\n'
        '        "integration_target" = "TaskCenter"\r\n'
        '        "browser_ui" = $false\r\n'
        '        "local_http_ui" = $false\r\n'
        '        "native_ci_verified" = $true\r\n'
        '        "user_install_allowed" = $true\r\n'
        '        "picotoo pet ai.exe"\r\n'
        '        "tools/diagnostics/picotoopet.desktop.diagnostics.exe"\r\n'
        '        throw "GOAL_INTEGRITY_VIOLATION: forbidden web UI payload"\r\n'
        '        throw "GOAL_INTEGRITY_VIOLATION: unapproved executable payload"\r\n'
    ).encode("utf-8-sig")


def _manifest() -> dict[str, object]:
    return {
        "schema_version": "2.3.0",
        "release_type": "prebuilt",
        "version": "2.3.0-slice-d-native-wpf-test",
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
    }


def _package(tmp_path: Path, *, extra_executable: bool) -> Path:
    package = tmp_path / "candidate.zip"
    root = "candidate"
    files: dict[str, bytes] = {
        f"{root}/release-manifest.json": json.dumps(_manifest()).encode(),
        f"{root}/payload/Picotoo Pet AI.exe": b"MZ-native-wpf",
        f"{root}/payload/tools/diagnostics/PicotooPet.Desktop.Diagnostics.exe": b"MZ-diagnostics",
        f"{root}/Phase2Prebuilt.Common.ps1": b"common",
        f"{root}/Install-Phase2Prebuilt.ps1": _gate_script(),
        f"{root}/Verify-Phase2Prebuilt.ps1": _gate_script(),
        f"{root}/Rollback-Phase2Prebuilt.ps1": b"rollback",
        f"{root}/INSTALL_PHASE2_WINDOWS.vbs": b"ascii",
        f"{root}/VERIFY_PHASE2_WINDOWS.vbs": b"ascii",
        f"{root}/ROLLBACK_PHASE2_WINDOWS.vbs": b"ascii",
    }
    if extra_executable:
        files[f"{root}/payload/Updater.exe"] = b"MZ-unapproved"
    with zipfile.ZipFile(package, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return package


def test_contract_allows_only_main_wpf_and_diagnostics_executables() -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert contract["windows"]["allowed_payload_executable_paths"] == [
        "Picotoo Pet AI.exe",
        "tools/diagnostics/PicotooPet.Desktop.Diagnostics.exe",
    ]


def test_rejects_third_executable_even_when_manifest_claims_native_wpf(
    tmp_path: Path,
) -> None:
    package = _package(tmp_path, extra_executable=True)

    with pytest.raises(GoalIntegrityError, match="unapproved executable|未批准"):
        verify_windows_package(package, contract_path=CONTRACT)


def test_accepts_only_the_two_approved_executables(tmp_path: Path) -> None:
    package = _package(tmp_path, extra_executable=False)

    report = verify_windows_package(package, contract_path=CONTRACT)

    assert report["status"] == "pass"
