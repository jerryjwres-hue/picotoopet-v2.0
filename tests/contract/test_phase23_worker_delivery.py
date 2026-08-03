"""Slice D Worker 安装包、原生 CI、诊断执行和回滚边界。"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "scripts" / "mac" / "phase23-worker"
DEPLOY = ROOT / "deploy" / "macos" / "phase23-worker"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_slice_d_builder_is_arm64_offline_and_manifest_driven() -> None:
    """构建器只产出 M4/arm64 离线 Worker 包，并从项目元数据解析 wheel。"""

    builder = read(BUILD / "Build-MacWorkerSliceC.sh")
    for required in (
        '"$(uname -m)" != "arm64"',
        "python3 -m pip wheel",
        "--wheel-dir",
        "tomllib",
        "expected exactly one picotoopet_core wheel",
        '"runtime_version": "2.3.0-slice-d-worker"',
        '"worker_runtime_included": True',
        '"system.diagnostic_snapshot"',
        '"system.noop"',
        '"diagnostic_hard_timeout_seconds": 30',
        '"diagnostic_termination_grace_seconds": 5',
        '"source_build_on_user_mac": False',
        "release-manifest.json",
        "shasum -a 256",
        "PHASE23_MAC_WORKER_BUILD=PASS",
        "PHASE23_MAC_WORKER_SLICE_D_BUILD=PASS",
    ):
        assert required in builder
    assert "picotoopet_core-2.3.0.dev2" not in builder
    assert "x86_64" not in builder


def test_slice_d_installer_is_transactional_and_manifest_driven() -> None:
    """安装器必须先验证候选，再切换、启用 Worker，并能恢复组合。"""

    installer = read(DEPLOY / "INSTALL_MAC_WORKER_SLICE_C.command")
    worker_library = read(DEPLOY / "worker-lib.sh")
    for required in (
        "verify_manifest_files",
        'python_version="$("$current_python" --version 2>&1)"',
        '"$current_python" -m venv',
        "--no-index",
        "--find-links",
        '"picotoopet-core==$package_version"',
        "verify_slice_d_candidate_contract",
        "atomic_switch_current",
        "restart_core_runtime",
        "write_worker_plist",
        "start_worker_agent",
        "wait_for_worker_state",
        "verify_worker_api_contract",
        "rollback_after_failed_activation",
        "backup_captured",
        "slice-d-previous-version.txt",
        "diagnostic_hard_timeout_seconds",
        "diagnostic_termination_grace_seconds",
    ):
        assert required in installer or required in worker_library
    assert "picotoopet-core==2.3.0.dev" not in installer
    assert 'python_version="$($current_python --version 2>&1)"' not in installer

    combined = installer + worker_library
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


def test_slice_d_package_verifier_rejects_unsafe_or_unfrozen_content() -> None:
    """实际 tar.gz 必须验证外层 SHA、归档路径、清单、唯一 wheel 和脚本语法。"""

    verifier = read(BUILD / "Test-MacWorkerSliceC.sh")
    for required in (
        "tarfile",
        "is_absolute",
        '".." in path.parts',
        "member.issym()",
        "verify_manifest_files",
        "worker_runtime_included",
        "worker_supported_task_types",
        "diagnostic_hard_timeout_seconds",
        "diagnostic_termination_grace_seconds",
        "package_version",
        "bash -n",
        "PHASE23_MAC_WORKER_PACKAGE_TEST=PASS",
        "PHASE23_MAC_WORKER_SLICE_D_PACKAGE_TEST=PASS",
    ):
        assert required in verifier


def test_slice_d_fixture_executes_diagnostic_and_preserves_analysis() -> None:
    """包级夹具必须完成真实诊断结果，并保持历史 analysis 不变。"""

    fixture = read(BUILD / "Test-MacWorkerSliceCFixture.sh")
    for required in (
        'runtime_root="$temp_root/Application Support/PicotooPetV2"',
        '"picotoopet-core==$package_version"',
        '"task_type": "analysis"',
        "/api/v1/tasks/system-diagnostic-snapshot",
        '"Idempotency-Key": "fixture-diagnostic-complete"',
        'current.get("status") == "Completed"',
        'len(result_bytes) > 64 * 1024',
        'result.get("schema_version") != "1.0"',
        '"historical_analysis_preserved": True',
        '"diagnostic_completed": True',
        '"diagnostic_result_verified": True',
        "PHASE23_MAC_WORKER_DIAGNOSTIC_FIXTURE=PASS",
        "PHASE23_MAC_WORKER_HISTORICAL_PROTECTION=PASS",
    ):
        assert required in fixture


def test_slice_d_fixture_proves_cancellation_timeout_and_no_orphans() -> None:
    """实际安装 wheel 必须证明取消、超时和进程回收。"""

    fixture = read(BUILD / "Test-MacWorkerSliceCFixture.sh")
    for required in (
        '"Idempotency-Key": "fixture-diagnostic-cancelled"',
        'current.get("status") != "Cancelled"',
        "DiagnosticCancelledError",
        "DiagnosticTimeoutError",
        "assert_reaped",
        "os.kill(pid, 0)",
        '"cancelled_process_reaped": True',
        '"timed_out_process_reaped": True',
        "PHASE23_MAC_WORKER_CANCELLATION_FIXTURE=PASS",
        "PHASE23_MAC_WORKER_SUBPROCESS_FIXTURE=PASS",
    ):
        assert required in fixture


def test_slice_d_fixture_recovers_only_supported_expired_lease() -> None:
    """过期租约恢复必须限定为 Worker 明确支持的任务类型并关闭 attempt。"""

    fixture = read(BUILD / "Test-MacWorkerSliceCFixture.sh")
    for required in (
        "recover_expired_supported_leases",
        '("system.diagnostic_snapshot", "system.noop")',
        'current.status.value != "Retrying"',
        'current.error_code != "LEASE_EXPIRED"',
        'attempt.get("status") != "Failed"',
        'attempt.get("error_code") != "LEASE_EXPIRED"',
        '"expired_supported_lease_recovered": True',
        '"expired_attempt_closed": True',
        "PHASE23_MAC_WORKER_EXPIRED_LEASE_FIXTURE=PASS",
    ):
        assert required in fixture


def test_slice_d_rollback_restores_core_and_worker_without_deletion() -> None:
    """回滚必须恢复兼容组合且保留数据库、结果、版本和报告。"""

    rollback = read(DEPLOY / "ROLLBACK_MAC_WORKER_SLICE_C.command")
    for required in (
        "slice-d-previous-version.txt",
        "slice-d-previous-worker-present.txt",
        "slice-d-previous-worker.plist",
        "stop_worker_agent",
        "atomic_switch_current",
        "restart_user_agent",
        "verify_health",
        "slice-d-rollback-from.txt",
    ):
        assert required in rollback
    for forbidden in (
        'rm -rf "$runtime_root"',
        'rm -rf "$runtime_root/database"',
        'rm -rf "$runtime_root/results"',
        "security delete-generic-password",
        "sudo ",
    ):
        assert forbidden not in rollback

    fixture = read(BUILD / "Test-MacWorkerSliceCFixture.sh")
    assert "ROLLBACK_MAC_WORKER_SLICE_C.command" in fixture
    assert "PHASE23_MAC_WORKER_ROLLBACK_FIXTURE=PASS" in fixture
    assert "PHASE23_MAC_WORKER_SLICE_D_FIXTURE=PASS" in fixture


def test_slice_d_native_ci_is_m4_only_and_uploads_diagnostics_separately() -> None:
    """工作流只在 arm64 运行，并区分失败证据与正式候选。"""

    workflow = read(ROOT / ".github" / "workflows" / "macos-worker-slice-c-ci.yml")
    for required in (
        "Mac Worker Slice D CI",
        "macos-15",
        "arm64",
        'python-version: "3.12"',
        "test_phase23_diagnostic_contract.py",
        "test_diagnostic_snapshot_api.py",
        "test_diagnostic_result_transaction.py",
        "test_diagnostic_worker_runtime.py",
        "test_diagnostic_subprocess_runner.py",
        "Build-MacWorkerSliceC.sh",
        "Test-MacWorkerSliceC.sh",
        "Test-MacWorkerSliceCFixture.sh",
        "if: failure()",
        "SliceD-DIAGNOSTIC",
        "Upload verified M4 Slice D Worker candidate",
    ):
        assert required in workflow
    assert "macos-15-intel" not in workflow
    assert "x86_64" not in workflow


def test_slice_d_ci_cannot_upload_candidate_before_full_fixture() -> None:
    """正式候选只能在真实归档诊断、取消、超时、恢复和回滚后上传。"""

    workflow = read(ROOT / ".github" / "workflows" / "macos-worker-slice-c-ci.yml")
    build = workflow.index("Build M4 arm64 offline Slice D Worker package")
    verify = workflow.index("Verify actual Slice D Worker archive and manifest")
    fixture = workflow.index("Exercise diagnostic cancellation timeout recovery and rollback")
    upload = workflow.index("Upload verified M4 Slice D Worker candidate")
    assert build < verify < fixture < upload
