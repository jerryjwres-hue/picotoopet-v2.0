"""Phase 2.3 Slice B Mac Core 增量交付源码合同。"""

from __future__ import annotations

from pathlib import Path

from picotoopet_core import __version__

ROOT = Path(__file__).resolve().parents[2]
MAC_BUILD = ROOT / "scripts" / "mac" / "phase23"
MAC_DEPLOY = ROOT / "deploy" / "macos" / "phase23"


def read(path: Path) -> str:
    """按 UTF-8 读取冻结交付文件。"""

    return path.read_text(encoding="utf-8")


def test_slice_b_mac_version_identity() -> None:
    """Wheel 版本和运行时健康版本必须明确进入 Slice B。"""

    pyproject = read(ROOT / "pyproject.toml")
    assert 'version = "2.3.0.dev1"' in pyproject
    assert __version__ == "2.3.0-slice-b"


def test_mac_delta_builder_requires_offline_wheelhouse() -> None:
    """构建器必须把项目及全部依赖冻结成架构专属 wheelhouse。"""

    script = read(MAC_BUILD / "Build-MacCoreSliceBDelta.sh")
    for required in (
        "python3 -m pip wheel",
        "--wheel-dir",
        "find \"$wheelhouse\" -type f ! -name '*.whl'",
        "release-manifest.json",
        "shasum -a 256",
        "tar -czf",
        "PHASE23_MAC_DELTA_BUILD=PASS",
    ):
        assert required in script


def test_mac_delta_package_verifier_rejects_unsafe_archives() -> None:
    """包级复验必须先拒绝绝对路径和目录穿越，再验证清单与脚本语法。"""

    script = read(MAC_BUILD / "Test-MacCoreSliceBDelta.sh")
    for required in (
        "tarfile",
        "is_absolute",
        '".." in path.parts',
        "verify_manifest_files",
        "bash -n",
        "PHASE23_MAC_DELTA_PACKAGE_TEST=PASS",
    ):
        assert required in script


def test_mac_delta_installer_preserves_existing_runtime_boundaries() -> None:
    """增量安装必须沿用现有事实路径、端口、令牌、数据和用户 LaunchAgent。"""

    installer = read(MAC_DEPLOY / "INSTALL_MAC_CORE_SLICE_B.command")
    for required in (
        "Library/Application Support/PicotooPetV2",
        "current/.venv/bin/python",
        "--no-index",
        "--find-links",
        "picotoopet-core==2.3.0.dev1",
        "com.picotoopet.mac-core",
        "previous-version.txt",
        "/api/v1/workers/status",
        "atomic_switch_current",
        "rollback_after_failed_activation",
    ):
        assert required in installer

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


def test_mac_delta_shared_library_uses_safe_json_and_path_validation() -> None:
    """共享函数不得使用 eval，且必须验证清单路径、哈希和已有端口。"""

    library = read(MAC_DEPLOY / "lib.sh")
    for required in (
        "read_manifest",
        "verify_manifest_files",
        "resolve_current_version",
        "read_existing_port",
        "restart_user_agent",
        "write_report",
        "verify_api_contract",
        "PICOTOO_RUNTIME_ROOT_OVERRIDE",
    ):
        assert required in library
    assert "eval " not in library
    assert "security find-generic-password" in library
    assert "shasum -a 256" in library


def test_mac_delta_verify_and_rollback_are_explicit_and_non_destructive() -> None:
    """验证与回滚必须保留失败版本，不自动删除数据库或版本目录。"""

    verifier = read(MAC_DEPLOY / "VERIFY_MAC_CORE_SLICE_B.command")
    rollback = read(MAC_DEPLOY / "ROLLBACK_MAC_CORE_SLICE_B.command")
    for required in (
        "verify_api_contract",
        "worker_status",
        "local_worker",
        "not_deployed",
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


def test_native_macos_ci_builds_and_verifies_both_architectures() -> None:
    """arm64 与 Intel 必须各自在原生 macOS Runner 生成和验证架构专属包。"""

    workflow = read(ROOT / ".github" / "workflows" / "macos-core-slice-b-ci.yml")
    for required in (
        "macos-15",
        "macos-15-intel",
        'python-version: "3.12"',
        "pytest -q",
        "ruff check",
        "Build-MacCoreSliceBDelta.sh",
        "Test-MacCoreSliceBDelta.sh",
        "Test-MacCoreSliceBFixture.sh",
        "upload-artifact",
    ):
        assert required in workflow


def test_mac_delta_scripts_contain_no_worker_execution_or_system_mutation() -> None:
    """本切片只部署状态合同，不得偷偷加入 Worker 或系统级修改。"""

    texts = []
    for directory in (MAC_BUILD, MAC_DEPLOY):
        if directory.exists():
            texts.extend(
                read(path)
                for path in directory.iterdir()
                if path.is_file()
            )
    combined = "\n".join(texts)
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
