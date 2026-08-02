"""Slice C Worker 安装包、原生 CI 和回滚边界。"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "scripts" / "mac" / "phase23-worker"
DEPLOY = ROOT / "deploy" / "macos" / "phase23-worker"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_slice_c_builder_is_arm64_offline_and_worker_explicit() -> None:
    """构建器只产出 M4/arm64 离线 Worker 包。"""

    builder = read(BUILD / "Build-MacWorkerSliceC.sh")
    for required in (
        'architecture" != "arm64"',
        "python3 -m pip wheel",
        "--wheel-dir",
        "picotoopet_core-2.3.0.dev2",
        '"runtime_version": "2.3.0-slice-c"',
        '"worker_runtime_included": True',
        '"worker_supported_task_types": ["system.noop"]',
        "release-manifest.json",
        "shasum -a 256",
        "PHASE23_MAC_WORKER_BUILD=PASS",
    ):
        assert required in builder
    assert "x86_64" not in builder


def test_slice_c_installer_is_transactional_and_inherits_incident_gates() -> None:
    """安装器必须先验证候选，再切换、启用 Worker，并能恢复组合。"""

    installer = read(DEPLOY / "INSTALL_MAC_WORKER_SLICE_C.command")
    for required in (
        "verify_manifest_files",
        'python_version="$("$current_python" --version 2>&1)"',
        '"$current_python" -m venv',
        "--no-index",
        "--find-links",
        "picotoopet-core==2.3.0.dev2",
        "verify_slice_c_candidate_contract",
        "atomic_switch_current",
        "restart_core_runtime",
        "write_worker_plist",
        "start_worker_agent",
        "wait_for_worker_state",
        "verify_worker_api_contract",
        "rollback_after_failed_activation",
        "backup_captured",
        "source_build_on_user_mac",
    ):
        assert required in installer or required in read(DEPLOY / "worker-lib.sh")
    assert 'python_version="$($current_python --version 2>&1)"' not in installer

    combined = installer + read(DEPLOY / "worker-lib.sh")
    for forbidden in (
        "sudo ",
        "/Library/LaunchDaemons",
        "security delete-generic-password",
        "pfctl",
        "socketfilterfw",
        "pip wheel",
        "dotnet build",
    ):
        assert forbidden not in combined


def test_slice_c_package_verifier_rejects_unsafe_or_unfrozen_content() -> None:
    """实际 tar.gz 必须验证外层 SHA、归档路径、清单和脚本语法。"""

    verifier = read(BUILD / "Test-MacWorkerSliceC.sh")
    for required in (
        "tarfile",
        "is_absolute",
        '".." in path.parts',
        "member.issym()",
        "verify_manifest_files",
        "worker_runtime_included",
        "worker_supported_task_types",
        "bash -n",
        "PHASE23_MAC_WORKER_PACKAGE_TEST=PASS",
    ):
        assert required in verifier


def test_slice_c_fixture_executes_noop_but_preserves_historical_analysis() -> None:
    """包级夹具必须证明 Worker 只处理 system.noop。"""

    fixture = read(BUILD / "Test-MacWorkerSliceCFixture.sh")
    for required in (
        'runtime_root="$temp_root/Application Support/PicotooPetV2"',
        '"task_type": "analysis"',
        '"task_type": "system.noop"',
        'historical.get("status") != "Queued"',
        'current.get("status") == "Completed"',
        "task_attempts",
        "PHASE23_MAC_WORKER_EXECUTION_FIXTURE=PASS",
        "PHASE23_MAC_WORKER_HISTORICAL_PROTECTION=PASS",
        "ROLLBACK_MAC_WORKER_SLICE_C.command",
        "PHASE23_MAC_WORKER_ROLLBACK_FIXTURE=PASS",
        '"source_build_on_user_mac": False',
    ):
        assert required in fixture


def test_slice_c_rollback_restores_core_and_worker_definition_without_deletion() -> None:
    """回滚必须恢复兼容组合且保留数据库、版本和报告。"""

    rollback = read(DEPLOY / "ROLLBACK_MAC_WORKER_SLICE_C.command")
    for required in (
        "slice-c-previous-version.txt",
        "slice-c-previous-worker-present.txt",
        "slice-c-previous-worker.plist",
        "stop_worker_agent",
        "atomic_switch_current",
        "restart_user_agent",
        "verify_health",
        "slice-c-rollback-from.txt",
        '"false"',
    ):
        assert required in rollback
    for forbidden in (
        'rm -rf "$runtime_root"',
        'rm -rf "$runtime_root/database"',
        "security delete-generic-password",
        "sudo ",
    ):
        assert forbidden not in rollback


def test_slice_c_native_ci_is_m4_only_and_uploads_diagnostics_separately() -> None:
    """新工作流必须只在 arm64 运行并区分失败证据与正式候选。"""

    workflow = read(ROOT / ".github" / "workflows" / "macos-worker-slice-c-ci.yml")
    for required in (
        "macos-15",
        "arm64",
        "python-version: \"3.12\"",
        "test_install_regression_registry.py",
        "test_worker_runtime_source.py",
        "test_phase23_worker_delivery.py",
        "Build-MacWorkerSliceC.sh",
        "Test-MacWorkerSliceC.sh",
        "Test-MacWorkerSliceCFixture.sh",
        "if: failure()",
        "DIAGNOSTIC",
        "Upload verified M4 Worker candidate",
    ):
        assert required in workflow
    assert "macos-15-intel" not in workflow
    assert "x86_64" not in workflow
