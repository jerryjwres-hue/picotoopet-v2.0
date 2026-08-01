import os
import plistlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy" / "macos"
SCRIPTS = ROOT / "scripts" / "mac"


def test_launchd_plists_start_core_and_health_supervisor() -> None:
    """Mac 开机登录后必须自动启动 Core，并定期恢复 Ollama 常驻。"""

    core = plistlib.loads((DEPLOY / "com.picotoopet.mac-core.plist").read_bytes())
    supervisor = plistlib.loads(
        (DEPLOY / "com.picotoopet.health-supervisor.plist").read_bytes()
    )

    assert core["Label"] == "com.picotoopet.mac-core"
    assert core["RunAtLoad"] is True
    assert core["KeepAlive"] is True
    assert core["ProgramArguments"][-1] == "serve"
    assert "current/.venv/bin/picotoopet-core" in core["ProgramArguments"][0]
    assert supervisor["Label"] == "com.picotoopet.health-supervisor"
    assert supervisor["RunAtLoad"] is True
    assert supervisor["KeepAlive"] is True
    assert supervisor["ProgramArguments"][-2:] == ["supervise", "--loop"]


def test_mac_scripts_cover_install_verify_backup_repair_and_rollback() -> None:
    """双击脚本必须覆盖安装、验证、备份、修复和版本回滚。"""

    required = {
        "INSTALL_MAC.command",
        "VERIFY_MAC.command",
        "BACKUP_MAC.command",
        "REPAIR_MAC.command",
        "ROLLBACK_MAC.command",
    }
    assert required <= {path.name for path in SCRIPTS.iterdir()}

    install = (SCRIPTS / "INSTALL_MAC.command").read_text(encoding="utf-8")
    rollback = (SCRIPTS / "ROLLBACK_MAC.command").read_text(encoding="utf-8")
    backup = (SCRIPTS / "BACKUP_MAC.command").read_text(encoding="utf-8")

    assert "security add-generic-password" in install
    assert "uv sync" in install
    assert "launchctl bootstrap" in install
    assert "versions" in install and "current" in install
    assert "previous_version.txt" in install
    assert 'VERSION="2.2.0-phase2-slice1-$(date -u +%Y%m%dT%H%M%SZ)-$$"' in install
    assert "previous_version.txt" in rollback
    assert "launchctl bootout" in rollback
    assert ".backup" in backup


@pytest.mark.skipif(
    os.name == "nt",
    reason="该测试执行 macOS launchctl/open 脚本，只能在 POSIX runner 判定。",
)
def test_verify_mac_always_writes_and_opens_report_when_a_check_fails(tmp_path: Path) -> None:
    """任一检查失败时仍须完成其余检查，并向用户展示验证报告。"""

    import subprocess

    home        = tmp_path / "home"
    runtime     = home / "Library" / "Application Support" / "PicotooPetV2"
    core        = runtime / "current" / ".venv" / "bin" / "picotoopet-core"
    fake_bin    = tmp_path / "bin"
    open_marker = tmp_path / "open-called.txt"

    core.parent.mkdir(parents=True)
    (runtime / "state").mkdir(parents=True)
    fake_bin.mkdir()

    # 模拟 health 成功、resident-check 失败，验证脚本不能在中途静默退出。
    core.write_text(
        "#!/bin/bash\n"
        "if [ \"$1\" = \"health\" ]; then echo '{\"status\":\"ok\"}'; exit 0; fi\n"
        "if [ \"$1\" = \"resident-check\" ]; then echo '{\"status\":\"error\"}'; exit 3; fi\n"
        "exit 2\n",
        encoding="utf-8",
    )
    core.chmod(0o755)

    for name in ("launchctl", "curl"):
        executable = fake_bin / name
        executable.write_text("#!/bin/bash\necho mocked-$0\nexit 0\n", encoding="utf-8")
        executable.chmod(0o755)

    opener = fake_bin / "open"
    opener.write_text(
        f"#!/bin/bash\nprintf '%s\\n' \"$*\" > {open_marker!s}\nexit 0\n",
        encoding="utf-8",
    )
    opener.chmod(0o755)

    environment         = os.environ.copy()
    environment["HOME"] = str(home)
    environment["PATH"] = f"{fake_bin}:{environment['PATH']}"

    result = subprocess.run(
        ["bash", str(SCRIPTS / "VERIFY_MAC.command")],
        capture_output=True,
        text=True,
        env=environment,
        check=False,
    )

    reports = list((runtime / "state").glob("verification-*.txt"))
    assert result.returncode == 1
    assert len(reports) == 1
    assert "resident-check" in reports[0].read_text(encoding="utf-8")
    assert "launchctl mac-core" in reports[0].read_text(encoding="utf-8")
    assert "API health" in reports[0].read_text(encoding="utf-8")
    assert "验证报告已生成" in result.stdout
    assert open_marker.is_file()


def test_mac_install_selects_and_persists_a_free_api_port() -> None:
    """8765 已被旧平台占用时，V2 安装器必须自动选择备用端口并持久化。"""

    install = (SCRIPTS / "INSTALL_MAC.command").read_text(encoding="utf-8")
    plist   = plistlib.loads((DEPLOY / "com.picotoopet.mac-core.plist").read_bytes())

    assert "runtime_port.sh" in install
    assert "select_api_port 8765 8766" in install
    assert "api-port.txt" in install
    assert "__API_PORT__" in install
    assert plist["EnvironmentVariables"]["PICOTOO_API_PORT"] == "__API_PORT__"


@pytest.mark.skipif(
    os.name == "nt",
    reason="该测试 source POSIX shell helper，只能在 POSIX runner 判定。",
)
def test_runtime_port_helper_chooses_8766_when_8765_is_busy(tmp_path: Path) -> None:
    """端口检测必须只读，且不能终止占用 8765 的旧进程。"""

    import subprocess

    helper   = SCRIPTS / "lib" / "runtime_port.sh"
    fake_lsof = tmp_path / "lsof"

    fake_lsof.write_text(
        "#!/bin/bash\n"
        "case \"$*\" in\n"
        "  *TCP:8765*) exit 0 ;;\n"
        "  *TCP:8766*) exit 1 ;;\n"
        "  *)          exit 1 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    fake_lsof.chmod(0o755)

    environment = os.environ.copy()
    environment["PICOTOO_LSOF_BIN"] = str(fake_lsof)
    result = subprocess.run(
        ["bash", "-c", f"source {helper!s}; select_api_port 8765 8766"],
        capture_output=True,
        text=True,
        env=environment,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "8766"


def test_verify_mac_uses_persisted_port_and_requires_running_launchd_state() -> None:
    """验证器必须读取实际端口，不能把 spawn scheduled 误判为服务正常。"""

    verify = (SCRIPTS / "VERIFY_MAC.command").read_text(encoding="utf-8")

    assert "api-port.txt" in verify
    assert 'API_PORT="$(cat "$STATE_DIR/api-port.txt")"' in verify
    assert "state = running" in verify
    assert 'http://127.0.0.1:${API_PORT}/api/v1/health' in verify
    assert "127.0.0.1:8765/api/v1/health" not in verify


def test_port_conflict_hotfix_is_reversible_and_does_not_kill_the_old_server() -> None:
    """当前实机修复只能迁移 V2 端口，不得终止或删除旧 PicotooPetAI 服务。"""

    hotfix = (SCRIPTS / "REPAIR_MAC_PORT_CONFLICT.command").read_text(
        encoding="utf-8"
    )

    assert "8766" in hotfix
    assert "PICOTOO_API_PORT" in hotfix
    assert "launchctl bootout" in hotfix
    assert "launchctl bootstrap" in hotfix
    assert "api-port.txt" in hotfix
    assert "kill " not in hotfix
    assert "pkill" not in hotfix
    assert "rm -rf" not in hotfix


def test_phase2_mac_upgrade_preserves_pairing_token_and_reports_new_version() -> None:
    """Phase 2 升级不得轮换已配对 Token，否则 Windows 会无故掉线。"""

    install = (SCRIPTS / "INSTALL_MAC.command").read_text(encoding="utf-8")

    assert 'VERSION="2.2.0-phase2-slice1-$(date -u +%Y%m%dT%H%M%SZ)-$$"' in install
    assert "security find-generic-password" in install
    assert "security delete-generic-password" not in install
    assert 'if ! security find-generic-password' in install
