"""Phase 2.3 Slice B Mac 增量包的静态安全边界。"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy" / "macos" / "phase23"
BUILD = ROOT / "scripts" / "mac" / "phase23"


def _combined_text() -> str:
    paths = sorted(
        path
        for directory in (DEPLOY, BUILD)
        for path in directory.iterdir()
        if path.is_file()
    )
    return "\n".join(path.read_text(encoding="utf-8") for path in paths)


def test_mac_delta_contains_no_worker_execution_or_system_modification() -> None:
    """增量包只部署状态合同，不得加入 Worker 或系统级写入。"""

    text = _combined_text()
    for forbidden in (
        "lease_next(",
        "recover_expired_leases(",
        "sudo ",
        "/Library/LaunchDaemons",
        "launchctl bootstrap system",
        "security delete-generic-password",
        "pfctl",
        "socketfilterfw",
        "curl -L",
        "pip install -e",
    ):
        assert forbidden not in text


def test_installer_preserves_existing_runtime_data_and_identity() -> None:
    """安装器必须复用现有根目录、端口和 Keychain，不重建事实源。"""

    installer = (DEPLOY / "INSTALL_MAC_CORE_SLICE_B.command").read_text(
        encoding="utf-8"
    )
    library = (DEPLOY / "lib.sh").read_text(encoding="utf-8")
    assert "Library/Application Support/PicotooPetV2" in library
    assert "Library/Application Support/PicotooPetV2/mac-core" not in library
    assert "state/api-port.txt" in library
    assert 'security find-generic-password -a "$USER" -s "PicotooPetV2.API" -w' in library
    assert 'rm -rf "$runtime_root/data"' not in installer
    assert 'rm -rf "$runtime_root/results"' not in installer
    assert 'rm -rf "$versions_root"' not in installer


def test_reports_never_serialize_api_token() -> None:
    """安装、验证和回滚报告不得包含 API 令牌字段或值。"""

    library = (DEPLOY / "lib.sh").read_text(encoding="utf-8")
    report_section = library.split("write_report()", maxsplit=1)[1]
    assert '"api_token"' not in report_section
    assert '"token"' not in report_section
    assert "source_build_on_user_mac" in report_section
    assert "worker_runtime_installed" in report_section


def test_fixture_proves_queued_task_is_unchanged() -> None:
    """隔离夹具必须比较升级前后的状态与 updated_at。"""

    fixture = (BUILD / "Test-MacCoreSliceBFixture.sh").read_text(encoding="utf-8")
    for required in (
        'after.get("status") != "Queued"',
        'after.get("updated_at") != before.get("updated_at")',
        "PHASE23_MAC_DELTA_QUEUED_PRESERVATION=PASS",
        "PHASE23_MAC_DELTA_ROLLBACK_FIXTURE=PASS",
    ):
        assert required in fixture


def test_manifest_declares_no_worker_runtime() -> None:
    """构建清单必须显式声明不包含 Worker runtime。"""

    builder = (BUILD / "Build-MacCoreSliceBDelta.sh").read_text(encoding="utf-8")
    assert '"worker_runtime_included": False' in builder
    assert '"source_build_on_user_mac": False' in builder
