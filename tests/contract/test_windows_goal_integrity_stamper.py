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
PRODUCT_VERSION = "2.3.11.1"
PRODUCT_VERSION_BYTES = (PRODUCT_VERSION + "\n").encode("utf-8")
SOURCE_HEAD = "a" * 40
SOURCE_REF = "feature/phase10b-return-intake"
BUILD_COMMIT = "b" * 40
WORKFLOW_REF = (
    "jerryjwres-hue/picotoopet-v2.0/"
    ".github/workflows/windows-phase2-release.yml@refs/pull/10/merge"
)
_APP_BYTES = b"MZ-native-wpf"
_DIAGNOSTIC_BYTES = b"MZ-diagnostics"


def _file_entry(path: str, data: bytes) -> dict[str, object]:
    return {
        "path": path,
        "sha256": hashlib.sha256(data).hexdigest(),
        "size_bytes": len(data),
    }


def _set_native_ci(monkeypatch: pytest.MonkeyPatch) -> None:
    values = {
        "CI": "true",
        "GITHUB_ACTIONS": "true",
        "RUNNER_OS": "Windows",
        "GITHUB_REPOSITORY": "jerryjwres-hue/picotoopet-v2.0",
        "GITHUB_RUN_ID": "123456789",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_WORKFLOW_REF": WORKFLOW_REF,
        "GITHUB_SHA": BUILD_COMMIT,
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)


def _write_candidate(
    tmp_path: Path,
    *,
    native_ci_verified: bool = True,
    include_scripts: bool = True,
    include_provenance: bool = True,
) -> tuple[Path, str]:
    archive_root = "candidate"
    package = tmp_path / (
        "PicotooPet-Phase2-Windows-Prebuilt-2.3.11.1-test.zip"
    )
    manifest: dict[str, object] = {
        "release_type": "prebuilt",
        "target": "win-x64",
        "product_version": PRODUCT_VERSION,
        "native_ci_verified": native_ci_verified,
        "user_install_allowed": native_ci_verified,
        "github_repository": "jerryjwres-hue/picotoopet-v2.0",
        "files": [
            _file_entry("product-version.txt", PRODUCT_VERSION_BYTES),
            _file_entry("Picotoo Pet AI.exe", _APP_BYTES),
            _file_entry(
                "tools/diagnostics/PicotooPet.Desktop.Diagnostics.exe",
                _DIAGNOSTIC_BYTES,
            ),
        ],
    }
    provenance = {
        "github_run_id": "123456789",
        "github_run_attempt": "1",
        "github_workflow_ref": WORKFLOW_REF,
        "source_head": SOURCE_HEAD,
        "source_ref": SOURCE_REF,
        "build_commit": BUILD_COMMIT,
    }
    if include_provenance:
        manifest.update(provenance)

    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr(
            f"{archive_root}/release-manifest.json",
            json.dumps(manifest),
        )
        archive.writestr(
            f"{archive_root}/payload/product-version.txt",
            PRODUCT_VERSION_BYTES,
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
                "# fixture\r\n"
                "[CmdletBinding()]\r\n"
                "param()\r\n"
                "try {\r\n"
                "    $manifest = Read-JsonUtf8 -Path $manifestPath\r\n"
                "    Write-Host 'continue'\r\n"
                "}\r\n"
                "catch { throw }\r\n"
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
                script,
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

    report: dict[str, object] = {
        "status": "pass",
        "product_version": PRODUCT_VERSION,
        "native_ci_verified": native_ci_verified,
        "user_install_allowed": native_ci_verified,
        "github_repository": "jerryjwres-hue/picotoopet-v2.0",
        "package_sha256": hashlib.sha256(package.read_bytes()).hexdigest(),
    }
    if include_provenance:
        report.update(provenance)
    (tmp_path / "windows-build-report.json").write_text(
        json.dumps(report),
        encoding="utf-8",
    )
    return package, archive_root


def _stamp(
    package: Path,
    tmp_path: Path,
) -> dict[str, object]:
    return stamp_windows_release(
        package,
        output_root=tmp_path / "stamped",
        source_head=SOURCE_HEAD,
        source_ref=SOURCE_REF,
        contract_path=CONTRACT,
    )


def test_stamps_native_wpf_package_and_injects_install_time_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_native_ci(monkeypatch)
    package, archive_root = _write_candidate(tmp_path)

    result = _stamp(package, tmp_path)

    output_package = Path(result["package"])
    assert output_package.is_file()
    assert result["product_version"] == PRODUCT_VERSION
    with zipfile.ZipFile(output_package) as archive:
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
        rollback = archive.read(
            f"{archive_root}/Rollback-Phase2Prebuilt.ps1"
        ).decode("utf-8-sig")

    assert updated["product_version"] == PRODUCT_VERSION
    assert updated["delivery_surface"] == "existing-native-wpf-desktop"
    assert updated["ui_framework"] == "WPF"
    assert updated["entry_executable"] == "Picotoo Pet AI.exe"
    assert updated["integration_target"] == "TaskCenter"
    assert updated["github_repository"] == "jerryjwres-hue/picotoopet-v2.0"
    assert updated["browser_ui"] is False
    assert updated["local_http_ui"] is False
    assert updated["source_build_on_user_pc"] is False
    assert updated["native_ci_verified"] is True
    assert updated["user_install_allowed"] is True

    for script in (installer, verifier, rollback):
        assert INSTALLER_MARKER in script
        assert script.index("[CmdletBinding()]") < script.index("param()")
        assert script.index("param()") < script.index(
            "$manifest = Read-JsonUtf8 -Path $manifestPath"
        )
        assert script.index(
            "$manifest = Read-JsonUtf8 -Path $manifestPath"
        ) < script.index(INSTALLER_MARKER)
        assert '"delivery_surface" = "existing-native-wpf-desktop"' in script
        assert '"ui_framework" = "WPF"' in script
        assert '"integration_target" = "TaskCenter"' in script
        assert '"github_repository" = "jerryjwres-hue/picotoopet-v2.0"' in script
        assert '"product_version" = ' not in script
        assert '"native_ci_verified" = $true' in script
        assert '"user_install_allowed" = $true' in script
        assert '"github_run_id"' in script
        assert '"github_workflow_ref"' in script
        assert "windows-control-center-ci.yml" in script
        assert "windows-phase2-release.yml" in script
        assert "forbidden web UI payload" in script
        assert "unapproved executable payload" in script

    checksum = Path(result["sha256_file"])
    assert output_package.name in checksum.read_text(encoding="utf-8")
    build_report = json.loads(
        Path(result["build_report"]).read_text(encoding="utf-8")
    )
    assert build_report["product_version"] == PRODUCT_VERSION
    assert build_report["delivery_surface"] == "existing-native-wpf-desktop"
    assert build_report["native_ci_verified"] is True
    assert build_report["user_install_allowed"] is True
    assert build_report["github_run_id"] == "123456789"


def test_formal_stamp_output_passes_independent_zip_verifier(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_native_ci(monkeypatch)
    package, _ = _write_candidate(tmp_path)

    result = _stamp(package, tmp_path)

    report = verify_windows_package(Path(result["package"]), contract_path=CONTRACT)
    assert report["status"] == "pass"
    assert report["product_version"] == PRODUCT_VERSION
    assert report["verified_payload_files"] == 3
    assert report["github_workflow_ref"].endswith("@refs/pull/10/merge")


def test_stamp_rejects_native_package_without_run_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_native_ci(monkeypatch)
    package, _ = _write_candidate(tmp_path, include_provenance=False)

    with pytest.raises(GoalStampError, match="溯源字段"):
        _stamp(package, tmp_path)


def test_stamp_rejects_unverified_package(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_native_ci(monkeypatch)
    package, _ = _write_candidate(tmp_path, native_ci_verified=False)

    with pytest.raises(GoalStampError, match="原生 CI 证明"):
        _stamp(package, tmp_path)


def test_stamp_rejects_package_without_formal_install_and_verify_scripts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_native_ci(monkeypatch)
    package, _ = _write_candidate(tmp_path, include_scripts=False)

    with pytest.raises(GoalStampError, match="Install-Phase2Prebuilt.ps1"):
        _stamp(package, tmp_path)
