from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DESKTOP = ROOT / "windows" / "desktop"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def test_windows_release_stamper_declares_native_wpf_goal_fields() -> None:
    stamper = _read(ROOT / "scripts" / "stamp_windows_goal_integrity.py")
    contract = _read(
        ROOT / "contracts" / "release" / "project-goal-invariants.json"
    )

    required = (
        '"source_build_on_user_pc": false',
        '"delivery_surface": "existing-native-wpf-desktop"',
        '"ui_framework": "WPF"',
        '"entry_executable": "Picotoo Pet AI.exe"',
        '"integration_target": "TaskCenter"',
        '"browser_ui": false',
        '"local_http_ui": false',
    )
    for declaration in required:
        assert declaration in contract

    assert 'manifest["user_install_allowed"] = native_verified' in stamper
    assert "PicotooPet-Phase2-Windows-Prebuilt-*.zip" in stamper
    assert "goal-integrity-stamp-report.json" in stamper


def test_windows_release_runs_goal_integrity_gate_before_artifact_upload() -> None:
    workflow = _read(ROOT / ".github" / "workflows" / "windows-phase2-release.yml")

    stamper = "scripts/stamp_windows_goal_integrity.py"
    validator = "scripts/verify_project_goal_integrity.py"
    upload = "actions/upload-artifact@v7"
    assert stamper in workflow
    assert validator in workflow
    assert "tests/contract/test_project_goal_integrity.py" in workflow
    assert "tests/contract/test_windows_goal_integrity_stamper.py" in workflow
    assert "tests/release/test_windows_goal_integrity_release_contract.py" in workflow
    assert "goal-integrity-report.json" in workflow
    assert "goal-integrity-stamp-report.json" in workflow
    assert workflow.index(stamper) < workflow.index(validator) < workflow.index(upload)


def test_windows_release_does_not_name_or_package_a_helper_surface() -> None:
    builder = _read(DESKTOP / "scripts" / "Build-Phase2WindowsRelease.ps1").lower()
    workflow = _read(ROOT / ".github" / "workflows" / "windows-phase2-release.yml").lower()

    forbidden = (
        "prebuilt-helper",
        "browser-localhost-helper",
        "picotoopet slice d.exe",
        "slicedhelper",
        "windows-helper",
    )
    for value in forbidden:
        assert value not in builder
        assert value not in workflow
