from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from scripts.verify_project_goal_integrity import GoalIntegrityError, verify_windows_package


ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "contracts" / "release" / "project-goal-invariants.json"
PRODUCT_VERSION = "2.3.18.1"
PRODUCT_VERSION_BYTES = (PRODUCT_VERSION + "\n").encode("utf-8")
_APP_BYTES = b"MZ-native-wpf"
_DIAGNOSTIC_BYTES = b"MZ-diagnostics"
_UPDATER_BYTES = b"MZ-unapproved"


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
        '        "github_repository" = "jerryjwres-hue/picotoopet-v2.0"\r\n'
        '        "product_version" = "2.3.18.1"\r\n'
        '        "native_ci_verified" = $true\r\n'
        '        "user_install_allowed" = $true\r\n'
        '        "github_run_id"\r\n'
        '        "github_run_attempt"\r\n'
        '        "github_workflow_ref"\r\n'
        '        "source_head"\r\n'
        '        "source_ref"\r\n'
        '        "build_commit"\r\n'
        '        ".github/workflows/windows-control-center-ci.yml"\r\n'
        '        ".github/workflows/windows-phase2-release.yml"\r\n'
        '        "picotoo pet ai.exe"\r\n'
        '        "tools/diagnostics/picotoopet.desktop.diagnostics.exe"\r\n'
        '        throw "GOAL_INTEGRITY_VIOLATION: forbidden web UI payload"\r\n'
        '        throw "GOAL_INTEGRITY_VIOLATION: unapproved executable payload"\r\n'
    ).encode("utf-8-sig")


def _file_entry(path: str, data: bytes) -> dict[str, object]:
    return {"path": path, "sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data)}


def _manifest(*, extra_executable: bool) -> dict[str, object]:
    files = [
        _file_entry("product-version.txt", PRODUCT_VERSION_BYTES),
        _file_entry("Picotoo Pet AI.exe", _APP_BYTES),
        _file_entry("tools/diagnostics/PicotooPet.Desktop.Diagnostics.exe", _DIAGNOSTIC_BYTES),
    ]
    if extra_executable:
        files.append(_file_entry("Updater.exe", _UPDATER_BYTES))
    return {
        "schema_version": "2.3.0", "release_type": "prebuilt", "version": "2.3.0-slice-d-native-wpf-test",
        "product_version": PRODUCT_VERSION, "target": "win-x64", "native_ci_verified": True,
        "user_install_allowed": True, "source_build_on_user_pc": False,
        "delivery_surface": "existing-native-wpf-desktop", "ui_framework": "WPF",
        "entry_executable": "Picotoo Pet AI.exe", "integration_target": "TaskCenter",
        "browser_ui": False, "local_http_ui": False, "github_repository": "jerryjwres-hue/picotoopet-v2.0",
        "github_run_id": "123456789", "github_run_attempt": "1",
        "github_workflow_ref": "jerryjwres-hue/picotoopet-v2.0/.github/workflows/windows-phase2-release.yml@refs/pull/10/merge",
        "source_head": "a" * 40, "source_ref": "feature/phase10b-return-intake", "build_commit": "b" * 40,
        "files": files,
    }


def _package(tmp_path: Path, *, extra_executable: bool) -> Path:
    package = tmp_path / "candidate.zip"; root = "candidate"; gate = _gate_script()
    files: dict[str, bytes] = {
        f"{root}/release-manifest.json": json.dumps(_manifest(extra_executable=extra_executable)).encode(),
        f"{root}/payload/product-version.txt": PRODUCT_VERSION_BYTES,
        f"{root}/payload/Picotoo Pet AI.exe": _APP_BYTES,
        f"{root}/payload/tools/diagnostics/PicotooPet.Desktop.Diagnostics.exe": _DIAGNOSTIC_BYTES,
        f"{root}/Phase2Prebuilt.Common.ps1": b"common",
        f"{root}/Install-Phase2Prebuilt.ps1": gate,
        f"{root}/Verify-Phase2Prebuilt.ps1": gate,
        f"{root}/Rollback-Phase2Prebuilt.ps1": gate,
        f"{root}/INSTALL_PHASE2_WINDOWS.vbs": b"ascii", f"{root}/VERIFY_PHASE2_WINDOWS.vbs": b"ascii",
        f"{root}/ROLLBACK_PHASE2_WINDOWS.vbs": b"ascii",
    }
    if extra_executable:
        files[f"{root}/payload/Updater.exe"] = _UPDATER_BYTES
    with zipfile.ZipFile(package, "w") as archive:
        for name, data in files.items(): archive.writestr(name, data)
    return package


def test_contract_allows_only_main_wpf_and_diagnostics_executables() -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert contract["windows"]["allowed_payload_executable_paths"] == [
        "Picotoo Pet AI.exe", "tools/diagnostics/PicotooPet.Desktop.Diagnostics.exe",
    ]


def test_rejects_third_executable_even_when_manifest_claims_native_wpf(tmp_path: Path) -> None:
    with pytest.raises(GoalIntegrityError, match="unapproved executable|未批准"):
        verify_windows_package(_package(tmp_path, extra_executable=True), contract_path=CONTRACT)


def test_accepts_only_the_two_approved_executables(tmp_path: Path) -> None:
    report = verify_windows_package(_package(tmp_path, extra_executable=False), contract_path=CONTRACT)
    assert report["status"] == "pass"
    assert report["product_version"] == PRODUCT_VERSION
    assert report["verified_payload_files"] == 3
