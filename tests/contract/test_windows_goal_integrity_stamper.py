from __future__ import annotations

import json
import zipfile
from pathlib import Path

from scripts.stamp_windows_goal_integrity import stamp_windows_release


ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "contracts" / "release" / "project-goal-invariants.json"


def test_stamps_native_wpf_package_and_disables_unverified_install(
    tmp_path: Path,
) -> None:
    archive_root = "candidate"
    package = tmp_path / "PicotooPet-Phase2-Windows-Prebuilt-test.zip"
    manifest = {
        "release_type": "prebuilt",
        "target": "win-x64",
        "native_ci_verified": False,
        "user_install_allowed": True,
    }
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr(
            f"{archive_root}/release-manifest.json",
            json.dumps(manifest),
        )
        archive.writestr(
            f"{archive_root}/payload/Picotoo Pet AI.exe",
            b"MZ-native-wpf",
        )
    (tmp_path / "windows-build-report.json").write_text(
        json.dumps({"status": "pass"}),
        encoding="utf-8",
    )

    report = stamp_windows_release(tmp_path, contract_path=CONTRACT)

    assert report["status"] == "pass"
    assert report["user_install_allowed"] is False
    with zipfile.ZipFile(package) as archive:
        updated = json.loads(
            archive.read(
                f"{archive_root}/release-manifest.json"
            ).decode("utf-8")
        )
    assert updated["delivery_surface"] == "existing-native-wpf-desktop"
    assert updated["ui_framework"] == "WPF"
    assert updated["entry_executable"] == "Picotoo Pet AI.exe"
    assert updated["integration_target"] == "TaskCenter"
    assert updated["browser_ui"] is False
    assert updated["local_http_ui"] is False
    assert updated["user_install_allowed"] is False

    checksum = package.with_name(package.name + ".sha256.txt")
    assert package.name in checksum.read_text(encoding="utf-8")
    build_report = json.loads(
        (tmp_path / "windows-build-report.json").read_text(encoding="utf-8")
    )
    assert build_report["delivery_surface"] == "existing-native-wpf-desktop"
    assert build_report["user_install_allowed"] is False
