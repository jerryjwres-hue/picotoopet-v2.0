"""Phase 2.3 Mac Core Slice D 增量交付源码合同。"""

from __future__ import annotations

from pathlib import Path

from picotoopet_core import __version__

ROOT = Path(__file__).resolve().parents[2]
MAC_BUILD = ROOT / "scripts" / "mac" / "phase23"
MAC_DEPLOY = ROOT / "deploy" / "macos" / "phase23"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_internal_python_distribution_version_remains_compatible() -> None:
    """产品版本独立于当前内部 Python distribution 版本。"""

    pyproject = read(ROOT / "pyproject.toml")
    assert 'version = "2.3.0.dev2"' in pyproject
    assert __version__ == "2.3.18.1"


def test_mac_core_builder_is_manifest_driven_and_offline() -> None:
    """构建器必须生成离线 wheelhouse，并从项目元数据解析唯一 wheel。"""

    script = read(MAC_BUILD / "Build-MacCoreSliceBDelta.sh")
    for required in (
        "python3 -m pip wheel",
        "--wheel-dir",
        "tomllib",
        "expected exactly one picotoopet_core wheel",
        "release-manifest.json",
        '"runtime_version": "2.3.0-slice-d-core"',
        '"diagnostic_snapshot_api_included": True',
        '"source_build_on_user_mac": False',
        "shasum -a 256",
        "tar -czf",
        "PHASE23_MAC_DELTA_BUILD=PASS",
        "PHASE23_MAC_SLICE_D_CORE_BUILD=PASS",
    ):
        assert required in script
    assert "picotoopet_core-2.3.0.dev1" not in script


def test_mac_core_package_verifier_rejects_unsafe_archives() -> None:
    """包级复验必须拒绝路径穿越、链接和清单漂移。"""

    script = read(MAC_BUILD / "Test-MacCoreSliceBDelta.sh")
    for required in (
        "tarfile",
        "is_absolute",
        '".." in path.parts',
        "member.issym()",
        "verify_manifest_files",
        "package_version",
        "bash -n",
        "PHASE23_MAC_DELTA_PACKAGE_TEST=PASS",
        "PHASE23_MAC_SLICE_D_CORE_PACKAGE_TEST=PASS",
    ):
        assert required in script


def test_mac_core_installer_preserves_existing_runtime_and_worker() -> None:
    """安装器使用 Manifest 版本，并保留已有端口、令牌、Worker 和回滚指针。"""

    installer = read(MAC_DEPLOY / "INSTALL_MAC_CORE_SLICE_B.command")
    library = read(MAC_DEPLOY / "lib.sh")
    for required in (
        "phase23_runtime_root",
        "current/.venv/bin/python",
        'python_version="$("$current_python" --version 2>&1)"',
        "--no-index",
        "--find-links",
        '"picotoopet-core==$package_version"',
        "com.picotoopet.mac-core",
        "previous-version.txt",
        "verify_api_contract",
        "atomic_switch_current",
        "rollback_after_failed_activation",
    ):
        assert required in installer
    for required in (
        'features.get("local_worker") is not True',
        '"not_deployed", "starting", "online", "degraded", "offline"',
        '"/api/v1/tasks/system-diagnostic-snapshot"',
        '"/api/v1/tasks/{task_id}/result"',
    ):
        assert required in library
    assert "picotoopet-core==2.3.0.dev" not in installer
    assert 'python_version="$($current_python --version 2>&1)"' not in installer

    for forbidden in (
        "sudo ",
        "security delete-generic-password",
        'rm -rf "$runtime_root/data"',
        "pfctl",
        "socketfilterfw",
        "launchctl bootstrap system",
        "lease_next",
        "recover_expired_leases",
    ):
        assert forbidden not in installer


def test_mac_core_fixture_uses_real_path_and_preserves_worker_and_history() -> None:
    """真实归档夹具覆盖 Application Support、在线 Worker、历史任务与回滚。"""

    fixture = read(MAC_BUILD / "Test-MacCoreSliceBFixture.sh")
    for required in (
        'runtime_root="$temp_root/Application Support/PicotooPetV2"',
        '"picotoopet-core==$package_version"',
        '"task_type": "analysis"',
        '"existing_worker_state_preserved": True',
        '"queued_task_preserved": True',
        '"diagnostic_api_verified": True',
        '"rollback_verified": True',
        '"source_build_on_user_mac": False',
        "PHASE23_MAC_SLICE_D_CORE_FIXTURE=PASS",
    ):
        assert required in fixture


def test_mac_core_shared_library_validates_json_paths_hashes_and_api() -> None:
    """共享函数不得使用 eval，并验证清单、现有端口和 Slice D 固定 API。"""

    library = read(MAC_DEPLOY / "lib.sh")
    for required in (
        "read_manifest",
        "verify_manifest_files",
        "resolve_current_version",
        "read_existing_port",
        "restart_user_agent",
        "write_report",
        "verify_api_contract",
        "/api/v1/workers/status",
        "/api/v1/tasks/system-diagnostic-snapshot",
        "/api/v1/tasks/{task_id}/result",
        "PICOTOO_RUNTIME_ROOT_OVERRIDE",
        "Library/Application Support/PicotooPetV2",
        "hashlib.sha256",
    ):
        assert required in library
    assert "eval " not in library
    assert "security find-generic-password" in library


def test_core_verify_rejects_wrong_running_product_version() -> None:
    verifier = read(MAC_DEPLOY / "VERIFY_MAC_CORE_SLICE_B.command")
    library = read(MAC_DEPLOY / "lib.sh")
    assert "phase23_product_version" in verifier
    assert "expected_product_version" in library
    assert 'health.get("version") != expected_product_version' in library
    assert "expected=" in library
    assert "actual=" in library


def test_mac_core_verify_and_rollback_are_explicit_and_non_destructive() -> None:
    """验证与回滚必须保留失败版本、数据库和既有 Worker 状态。"""

    verifier = read(MAC_DEPLOY / "VERIFY_MAC_CORE_SLICE_B.command")
    rollback = read(MAC_DEPLOY / "ROLLBACK_MAC_CORE_SLICE_B.command")
    for required in (
        "verify_api_contract",
        "/api/v1/tasks/system-diagnostic-snapshot",
        "/api/v1/tasks/{task_id}/result",
    ):
        assert required in verifier
    for required in (
        "previous-version.txt",
        "atomic_switch_current",
        "restart_user_agent",
        "verify_api_contract",
    ):
        assert required in rollback
    assert "rm -rf" not in rollback


def test_native_mac_core_ci_accepts_slice_d_and_remains_arm64_only() -> None:
    """原生门按组件基线判定影响，仍只生成 M4/arm64 候选。"""

    workflow = read(ROOT / ".github" / "workflows" / "macos-core-slice-b-ci.yml")
    for required in (
        "Detect Core impact",
        "component-baselines.json",
        "needs.impact.outputs.core == 'true'",
        "macos-15",
        "arch: arm64",
        'python-version: "3.12"',
        "test_phase23_diagnostic_contract.py",
        "Build-MacCoreSliceBDelta.sh",
        "Test-MacCoreSliceBDelta.sh",
        "Test-MacCoreSliceBFixture.sh",
        "Export authoritative Slice D OpenAPI",
        "Upload architecture-specific package and evidence",
    ):
        assert required in workflow
    assert "macos-15-intel" not in workflow
    assert "arch: x86_64" not in workflow


def test_mac_core_user_scripts_do_not_execute_worker_or_mutate_system() -> None:
    """Core 用户交付脚本不启动 Worker、不执行构建或修改系统级配置。"""

    user_scripts = (
        MAC_DEPLOY / "INSTALL_MAC_CORE_SLICE_B.command",
        MAC_DEPLOY / "VERIFY_MAC_CORE_SLICE_B.command",
        MAC_DEPLOY / "ROLLBACK_MAC_CORE_SLICE_B.command",
        MAC_DEPLOY / "lib.sh",
    )
    combined = "\n".join(read(path) for path in user_scripts)
    for forbidden in (
        "lease_next(",
        "recover_expired_leases(",
        "sudo ",
        "/Library/LaunchDaemons",
        "security delete-generic-password",
        "pfctl",
        "socketfilterfw",
    ):
        assert forbidden not in combined
