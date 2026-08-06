from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DESKTOP = ROOT / "windows" / "desktop"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def test_windows_release_stamper_declares_native_wpf_goal_fields() -> None:
    stamper = _read(ROOT / "scripts" / "stamp_windows_goal_integrity.py")
    verifier = _read(ROOT / "scripts" / "verify_project_goal_integrity.py")
    contract = _read(
        ROOT / "contracts" / "release" / "project-goal-invariants.json"
    )

    required_contract_values = (
        '"source_build_on_user_pc": false',
        '"delivery_surface": "existing-native-wpf-desktop"',
        '"ui_framework": "WPF"',
        '"entry_executable": "Picotoo Pet AI.exe"',
        '"integration_target": "TaskCenter"',
        '"browser_ui": false',
        '"local_http_ui": false',
        '"github_repository": "jerryjwres-hue/picotoopet-v2.0"',
        '"required_native_ci_provenance_fields"',
        '"product_version"',
        '"value": "2.3.12.5"',
    )
    for declaration in required_contract_values:
        assert declaration in contract

    required_runtime_controls = (
        "PICOTOO_GOAL_INTEGRITY_GATE_V1",
        "Install-Phase2Prebuilt.ps1",
        "Verify-Phase2Prebuilt.ps1",
        "native_ci_verified",
        "user_install_allowed",
        "github_run_id",
        "github_run_attempt",
        "github_workflow_ref",
        "source_head",
        "build_commit",
        "forbidden web UI payload",
        "product_version",
    )
    for declaration in required_runtime_controls:
        assert declaration in stamper
        assert declaration in verifier

    assert 'manifest["native_ci_verified"] = True' in stamper
    assert 'manifest["user_install_allowed"] = True' in stamper
    assert "output_package" in stamper
    assert "project-goal-integrity-report.json" in stamper
    assert '"installer_goal_gate": "pass"' in stamper
    assert '"installer_goal_gate": "pass"' in verifier


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
    assert "tests/release/test_windows_native_ci_provenance.py" in workflow
    assert "goal-integrity-report.json" in workflow
    assert "project-goal-integrity-report.json" in workflow
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


def test_only_existing_native_wpf_executable_is_formal_entrypoint() -> None:
    builder = _read(DESKTOP / "scripts" / "Build-Phase2WindowsRelease.ps1")
    stamper = _read(ROOT / "scripts" / "stamp_windows_goal_integrity.py")
    contract = _read(ROOT / "contracts" / "release" / "project-goal-invariants.json")

    assert '$appExecutable  = Join-Path $payloadRoot "Picotoo Pet AI.exe"' in builder
    assert '"entry_executable": "Picotoo Pet AI.exe"' in contract
    assert "allowed_payload_executable_paths" in contract
    assert "forbidden web UI payload" in stamper
