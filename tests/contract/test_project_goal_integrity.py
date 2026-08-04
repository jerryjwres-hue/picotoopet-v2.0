from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from scripts.verify_project_goal_integrity import (
    GoalIntegrityError,
    verify_windows_package,
)


_GOAL_GATE_MARKER = "# PICOTOO_GOAL_INTEGRITY_GATE_V1"
_PRODUCT_VERSION = "2.3.6.1"
_PRODUCT_VERSION_BYTES = (_PRODUCT_VERSION + "\n").encode("utf-8")
_APP_BYTES = b"MZ-native-wpf"
_DIAGNOSTIC_BYTES = b"MZ-diagnostics"


def _goal_gate_script() -> bytes:
    return (
        "$manifest = Read-JsonUtf8 -Path $manifestPath\r\n"
        f"    {_GOAL_GATE_MARKER}\r\n"
        '        "release_type" = "prebuilt"\r\n'
        '        "target" = "win-x64"\r\n'
        '        "delivery_surface" = "existing-native-wpf-desktop"\r\n'
        '        "ui_framework" = "WPF"\r\n'
        '        "entry_executable" = "Picotoo Pet AI.exe"\r\n'
        '        "integration_target" = "TaskCenter"\r\n'
        '        "github_repository" = "jerryjwres-hue/picotoopet-v2.0"\r\n'
        '        "product_version" = "2.3.6.1"\r\n'
        '        "source_build_on_user_pc" = $false\r\n'
        '        "browser_ui" = $false\r\n'
        '        "local_http_ui" = $false\r\n'
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
    ).encode("utf-8-sig")


def _file_entry(path: str, data: bytes) -> dict[str, object]:
    return {
        "path": path,
        "sha256": hashlib.sha256(data).hexdigest(),
        "size_bytes": len(data),
    }


def _make_package(
    tmp_path: Path,
    *,
    manifest: dict[str, object],
    extra_files: dict[str, bytes] | None = None,
) -> Path:
    root = "candidate"
    package = tmp_path / "candidate.zip"
    gate = _goal_gate_script()
    files = {
        f"{root}/release-manifest.json": json.dumps(
            manifest,
            ensure_ascii=False,
        ).encode("utf-8"),
        f"{root}/payload/product-version.txt": _PRODUCT_VERSION_BYTES,
        f"{root}/payload/Picotoo Pet AI.exe": _APP_BYTES,
        f"{root}/payload/tools/diagnostics/PicotooPet.Desktop.Diagnostics.exe": (
            _DIAGNOSTIC_BYTES
        ),
        f"{root}/Phase2Prebuilt.Common.ps1": b"function Read-JsonUtf8 { }",
        f"{root}/INSTALL_PHASE2_WINDOWS.vbs": b"ascii",
        f"{root}/VERIFY_PHASE2_WINDOWS.vbs": b"ascii",
        f"{root}/ROLLBACK_PHASE2_WINDOWS.vbs": b"ascii",
        f"{root}/Install-Phase2Prebuilt.ps1": gate,
        f"{root}/Verify-Phase2Prebuilt.ps1": gate,
        f"{root}/Rollback-Phase2Prebuilt.ps1": gate,
    }
    files.update(extra_files or {})
    with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return package


def _compliant_manifest() -> dict[str, object]:
    return {
        "schema_version": "2.3.0",
        "release_type": "prebuilt",
        "version": "2.3.0-slice-d-native-wpf-test",
        "product_version": _PRODUCT_VERSION,
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
        "github_run_id": "123456789",
        "github_run_attempt": "1",
        "github_workflow_ref": (
            "jerryjwres-hue/picotoopet-v2.0/"
            ".github/workflows/windows-phase2-release.yml@refs/pull/8/merge"
        ),
        "source_head": "a" * 40,
        "source_ref": "feature/phase23-slice-d-diagnostic-snapshot-release",
        "build_commit": "b" * 40,
        "files": [
            _file_entry("product-version.txt", _PRODUCT_VERSION_BYTES),
            _file_entry("Picotoo Pet AI.exe", _APP_BYTES),
            _file_entry(
                "tools/diagnostics/PicotooPet.Desktop.Diagnostics.exe",
                _DIAGNOSTIC_BYTES,
            ),
        ],
    }


def test_accepts_existing_native_wpf_task_center_delivery(tmp_path: Path) -> None:
    package = _make_package(tmp_path, manifest=_compliant_manifest())

    report = verify_windows_package(package)

    assert report["status"] == "pass"
    assert report["product_version"] == _PRODUCT_VERSION
    assert report["delivery_surface"] == "existing-native-wpf-desktop"
    assert report["entry_executable"] == "Picotoo Pet AI.exe"
    assert report["github_run_id"] == "123456789"
    assert report["verified_payload_files"] == 3
    assert report["installer_goal_gate"] == "pass"


def test_rejects_payload_hash_or_size_tampering(tmp_path: Path) -> None:
    package = _make_package(
        tmp_path,
        manifest=_compliant_manifest(),
        extra_files={"candidate/payload/Picotoo Pet AI.exe": b"MZ-tampered"},
    )

    with pytest.raises(GoalIntegrityError, match="SHA-256|大小"):
        verify_windows_package(package)


def test_rejects_unmanifested_payload_file(tmp_path: Path) -> None:
    package = _make_package(
        tmp_path,
        manifest=_compliant_manifest(),
        extra_files={"candidate/payload/unlisted.bin": b"unlisted"},
    )

    with pytest.raises(GoalIntegrityError, match="未列入|清单"):
        verify_windows_package(package)


def test_rejects_browser_helper_even_when_prebuilt_and_hashable(
    tmp_path: Path,
) -> None:
    manifest = _compliant_manifest() | {
        "release_type": "prebuilt-helper",
        "version": "2.3.0-slice-d-helper",
        "delivery_surface": "browser-localhost-helper",
        "ui_framework": "web",
        "entry_executable": "PicotooPet Slice D.exe",
        "integration_target": "separate-helper",
        "browser_ui": True,
        "local_http_ui": True,
        "native_ci_verified": False,
    }
    package = _make_package(
        tmp_path,
        manifest=manifest,
        extra_files={
            "candidate/payload/PicotooPet Slice D.exe": b"MZ-helper",
            "candidate/assets/index.html": b"<html></html>",
        },
    )

    with pytest.raises(
        GoalIntegrityError,
        match="GOAL_INTEGRITY_VIOLATION|不得降级|WPF",
    ):
        verify_windows_package(package)


def test_rejects_user_install_allowed_without_native_platform_verification(
    tmp_path: Path,
) -> None:
    manifest = _compliant_manifest() | {"native_ci_verified": False}
    package = _make_package(tmp_path, manifest=manifest)

    with pytest.raises(GoalIntegrityError, match="native_ci_verified"):
        verify_windows_package(package)


def test_rejects_separate_executable_instead_of_existing_desktop_app(
    tmp_path: Path,
) -> None:
    manifest = _compliant_manifest() | {"entry_executable": "SliceD.exe"}
    package = _make_package(tmp_path, manifest=manifest)

    with pytest.raises(GoalIntegrityError, match="Picotoo Pet AI.exe"):
        verify_windows_package(package)


def test_rejects_web_assets_in_formally_native_package(tmp_path: Path) -> None:
    package = _make_package(
        tmp_path,
        manifest=_compliant_manifest(),
        extra_files={"candidate/assets/app.js": b"window.open('/')"},
    )

    with pytest.raises(GoalIntegrityError, match="浏览器|Helper|WPF"):
        verify_windows_package(package)


def test_rejects_manifest_only_claim_without_installer_runtime_gate(
    tmp_path: Path,
) -> None:
    package = _make_package(
        tmp_path,
        manifest=_compliant_manifest(),
        extra_files={
            "candidate/Install-Phase2Prebuilt.ps1": (
                b"$manifest = Read-JsonUtf8 -Path $manifestPath\r\n"
            ),
        },
    )

    with pytest.raises(GoalIntegrityError, match="Install-Phase2Prebuilt|runtime gate"):
        verify_windows_package(package)


def test_rejects_package_when_verify_script_does_not_enforce_same_gate(
    tmp_path: Path,
) -> None:
    package = _make_package(
        tmp_path,
        manifest=_compliant_manifest(),
        extra_files={
            "candidate/Verify-Phase2Prebuilt.ps1": b"Write-Host pass\r\n",
        },
    )

    with pytest.raises(GoalIntegrityError, match="Verify-Phase2Prebuilt|runtime gate"):
        verify_windows_package(package)
