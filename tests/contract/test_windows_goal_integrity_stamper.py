from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from scripts.stamp_windows_goal_integrity import GoalStampError, stamp_windows_release
from scripts.verify_project_goal_integrity import verify_windows_package


ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "contracts" / "release" / "project-goal-invariants.json"
INSTALLER_MARKER = "PICOTOO_GOAL_INTEGRITY_GATE_V1"
_APP_BYTES = b"MZ-native-wpf"
_DIAGNOSTIC_BYTES = b"MZ-diagnostics"


def _file_entry(path: str, data: bytes) -> dict[str, object]:
    return {
        "path": path,
        "sha256": hashlib.sha256(data).hexdigest(),
        "size_bytes": len(data),
    }


def _write_candidate(
    tmp_path: Path,
    *,
    native_ci_verified: bool,
    include_scripts: bool = True,
    include_provenance: bool = True,
) -> tuple[Path, str]:
    archive_root = "candidate"
    package = tmp_path / "PicotooPet-Phase2-Windows-Prebuilt-test.zip"
    manifest: dict[str, object] = {
        "release_type": "prebuilt",
        "target": "win-x64",
        "native_ci_verified": native_ci_verified,
        "user_install_allowed": True,
        "files": [
            _file_entry("Picotoo Pet AI.exe", _APP_BYTES),
            _file_entry(
                "tools/diagnostics/PicotooPet.Desktop.Diagnostics.exe",
                _DIAGNOSTIC_BYTES,
            ),
        ],
    }
    if include_provenance:
        manifest.update(
            {
                "github_run_id": "123456789",
                "github_run_attempt": "1",
                "github_workflow_ref": (
                    "jerryjwres-hue/picotoopet-v2.0/"
                    ".github/workflows/windows-phase2-release.yml@refs/pull/8/merge"
                ),
                "source_head": "a" * 40,
                "source_ref": "feature/phase23-slice-d-diagnostic-snapshot-release",
                "build_commit": "b" * 40,
            }
        )
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr(
            f"{archive_root}/release-manifest.json",
            json.dumps(manifest),
        )
        archive.writestr(
            f"{archive_root}/payload/Picotoo Pet AI.exe",
            _APP_BYTES,
        )
        archive.writestr(
            f"{archive_root}/payload/tools/diagnostics/PicotooPet.Desktop.Diagnostics.exe",
            _DIAGNOSTIC_BYTES,
        )
        if include_scripts:
            script = (
                "$manifest = Read-JsonUtf8 -Path $manifestPath\r\n"
                "Write-Host 'continue'\r\n"
            ).encode("utf-8-sig")
            archive.writestr(
                f"{archive_root}/Phase2Prebuilt.Common.ps1",
                b"function Read-JsonUtf8 { }",
            )
            archive.writestr(
                f"{archive_root}/Install-Phase2Prebuilt.ps1",
                script,
            )
            archive.writestr(
                f"{archive_root}/Verify-Phase2Prebuilt.ps1",
                script,
            )
            archive.writestr(
                f"{archive_root}/Rollback-Phase2Prebuilt.ps1",
                b"Write-Host rollback",
            )
            archive.writestr(
                f"{archive_root}/INSTALL_PHASE2_WINDOWS.vbs",
                b"ascii",
            )
            archive.writestr(
                f"{archive_root}/VERIFY_PHASE2_WINDOWS.vbs",
                b"ascii",
            )
            archive.writestr(
                f"{archive_root}/ROLLBACK_PHASE2_WINDOWS.vbs",
                b"ascii",
            )
    (tmp_path / "windows-build-report.json").write_text(
        json.dumps({"status": "pass"}),
        encoding="utf-8",
    )
    return package, archive_root


def test_stamps_native_wpf_package_and_injects_install_time_gate(
    tmp_path: Path,
) -> None:
    package, archive_root = _write_candidate(
        tmp_path,
        native_ci_verified=False,
    )

    report = stamp_windows_release(tmp_path, contract_path=CONTRACT)

    assert report["status"] == "pass"
    assert report["user_install_allowed"] is False
    assert report["installer_goal_gate"] == "pass"
    with zipfile.ZipFile(package) as archive:
        updated = json.loads(
            archive.read(
                f"{archive_root}/release-manifest.json"
            ).decode("utf-8")
        )
        installer = archive.read(
            f"{archive_root}/Install-Phase2Prebuilt.ps1"
        ).decode("utf-8-sig")
        verifier = archive.read(
            f"{archive_root}/Verify-Phase2Prebuilt.ps1"
        ).decode("utf-8-sig")

    assert updated["delivery_surface"] == "existing-native-wpf-desktop"
    assert updated["ui_framework"] == "WPF"
    assert updated["entry_executable"] == "Picotoo Pet AI.exe"
    assert updated["integration_target"] == "TaskCenter"
    assert updated["github_repository"] == "jerryjwres-hue/picotoopet-v2.0"
    assert updated["browser_ui"] is False
    assert updated["local_http_ui"] is False
    assert updated["source_build_on_user_pc"] is False
    assert updated["user_install_allowed"] is False

    for script in (installer, verifier):
        assert INSTALLER_MARKER in script
        assert '"delivery_surface" = "existing-native-wpf-desktop"' in script
        assert '"ui_framework" = "WPF"' in script
        assert '"integration_target" = "TaskCenter"' in script
        assert '"github_repository" = "jerryjwres-hue/picotoopet-v2.0"' in script
        assert '"native_ci_verified" = $true' in script
        assert '"user_install_allowed" = $true' in script
        assert '"github_run_id"' in script
        assert '"github_workflow_ref"' in script
        assert "native CI provenance is missing" in script
        assert "windows-control-center-ci.yml" in script
        assert "windows-phase2-release.yml" in script
        assert "forbidden web UI payload" in script
        assert "[System.IO.Path]::DirectorySeparatorChar" in script
        assert "[System.IO.Path]::AltDirectorySeparatorChar" in script
        assert ".Replace('\\\\', '/')" not in script

    checksum = package.with_name(package.name + ".sha256.txt")
    assert package.name in checksum.read_text(encoding="utf-8")
    build_report = json.loads(
        (tmp_path / "windows-build-report.json").read_text(encoding="utf-8")
    )
    assert build_report["delivery_surface"] == "existing-native-wpf-desktop"
    assert build_report["user_install_allowed"] is False
    assert build_report["github_run_id"] == "123456789"
    assert build_report["installer_goal_gate"] == "pass"


def test_formal_stamp_output_passes_independent_zip_verifier(tmp_path: Path) -> None:
    package, _ = _write_candidate(
        tmp_path,
        native_ci_verified=True,
    )

    stamp_windows_release(tmp_path, contract_path=CONTRACT)

    report = verify_windows_package(package, contract_path=CONTRACT)
    assert report["status"] == "pass"
    assert report["verified_payload_files"] == 2
    assert report["github_workflow_ref"].endswith("@refs/pull/8/merge")


def test_stamp_rejects_native_package_without_run_provenance(
    tmp_path: Path,
) -> None:
    _write_candidate(
        tmp_path,
        native_ci_verified=True,
        include_provenance=False,
    )

    with pytest.raises(GoalStampError, match="原生 CI 溯源字段"):
        stamp_windows_release(tmp_path, contract_path=CONTRACT)


def test_stamp_rejects_package_without_formal_install_and_verify_scripts(
    tmp_path: Path,
) -> None:
    _write_candidate(
        tmp_path,
        native_ci_verified=True,
        include_scripts=False,
    )

    with pytest.raises(GoalStampError, match="Install-Phase2Prebuilt.ps1"):
        stamp_windows_release(tmp_path, contract_path=CONTRACT)
