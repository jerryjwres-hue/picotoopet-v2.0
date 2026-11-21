"""#296: never overwrite the real 2.3 / schema-24 Mac Core with the reduced V3.1 schema."""

from __future__ import annotations

import re
import sqlite3
import shutil

import pytest
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PREFLIGHT = ROOT / "scripts/mac/lib/check_install_database.py"
INSTALL = ROOT / "scripts/mac/INSTALL_MAC.command"
LAUNCHD = ROOT / "deploy/macos/com.picotoopet.mac-core.plist"


def _historical_db(tmp_path: Path, version: int = 24, *, foreign_v4: bool = False) -> Path:
    """合成与实机相同 3,685 条历史任务和 6 条审批，测试期间不碰真实 Core。"""

    database = tmp_path / "Application Support" / "PicotooPetV2" / "database" / "core.db"
    database.parent.mkdir(parents=True)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        connection.executemany(
            "INSERT INTO schema_migrations VALUES (?, 'historical')",
            [(n,) for n in range(1, version + 1)],
        )
        connection.execute("CREATE TABLE tasks (task_id TEXT PRIMARY KEY, status TEXT NOT NULL)")
        connection.executemany(
            "INSERT INTO tasks VALUES (?, 'historical')",
            [(f"task-{n:04}",) for n in range(3685)],
        )
        connection.execute("CREATE TABLE approvals (approval_id TEXT PRIMARY KEY)")
        connection.executemany(
            "INSERT INTO approvals VALUES (?)", [(f"approval-{n}",) for n in range(6)]
        )
        connection.execute("CREATE TABLE handoffs (handoff_id TEXT PRIMARY KEY)")
        if not foreign_v4:
            connection.execute("CREATE TABLE returns (return_id TEXT PRIMARY KEY)")
        else:
            connection.execute(
                "CREATE TABLE owner_production_hold (hold_id INTEGER PRIMARY KEY)"
            )
        if version >= 24:
            connection.execute(
                "CREATE TABLE creative_goal_source_sets (creative_job_id TEXT PRIMARY KEY)"
            )
    return database


def _run(
    database: Path,
    backup_dir: Path | None = None,
    *,
    require_existing: bool = False,
) -> subprocess.CompletedProcess[str]:
    """始终运行真实安装器调用的独立 SQLite 兼容检查程序。"""

    command = [sys.executable, str(PREFLIGHT), "--database", str(database)]
    if backup_dir is not None:
        command.extend(["--backup-dir", str(backup_dir)])
    if require_existing:
        command.append("--require-existing")
    return subprocess.run(command, text=True, capture_output=True, check=False, timeout=30)


def test_schema24_backup_preserves_historical_tasks_and_approvals(tmp_path: Path) -> None:
    """实机重要数据规模的 synthetic fixture 必须 100% 留存。"""

    source = _historical_db(tmp_path)
    original_bytes = source.read_bytes()
    backups = tmp_path / "SQLite Backups"
    result = _run(source, backups)
    assert result.returncode == 0, result.stderr
    assert "SCHEMA=COMPATIBLE_24 TASKS=3685 APPROVALS=6" in result.stdout
    assert "DATABASE_BACKUP=PASS" in result.stdout
    assert source.read_bytes() == original_bytes
    snapshots = list(backups.glob("pre-v31-compat-schema24-*.db"))
    assert len(snapshots) == 1
    with sqlite3.connect(snapshots[0]) as connection:
        assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 3685
        assert connection.execute("SELECT COUNT(*) FROM approvals").fetchone()[0] == 6
        assert connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 24
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name='owner_production_hold'"
        ).fetchone()[0] == 0


def test_fourth_migration_mismatch_refuses_before_backup(tmp_path: Path) -> None:
    """新版候选误用 v4 代表 Owner HOLD；在 2.3 的 v4 必须有 returns。"""

    source = _historical_db(tmp_path, version=4, foreign_v4=True)
    original_bytes = source.read_bytes()
    backups = tmp_path / "backups"
    result = _run(source, backups)
    assert result.returncode == 2
    assert "STOP=DATABASE_COMPATIBILITY:INCOMPATIBLE_MIGRATION_TABLE_SIGNATURE" in result.stderr
    assert not backups.exists()
    assert source.read_bytes() == original_bytes


def test_future_migration_refuses_without_mutation(tmp_path: Path) -> None:
    """未知的 schema 25 不会被只认识 24 的 Core 静默降级。"""

    source = _historical_db(tmp_path, version=25)
    original_bytes = source.read_bytes()
    result = _run(source)
    assert result.returncode == 2
    assert "UNSUPPORTED_SCHEMA_MIGRATIONS" in result.stderr
    assert source.read_bytes() == original_bytes


def test_new_install_only_reports_new_database(tmp_path: Path) -> None:
    """首次安装允许没有 DB，但只读预检本身不得新建空库。"""

    source = tmp_path / "new" / "core.db"
    result = _run(source)
    assert result.returncode == 0
    assert "DATABASE=NEW" in result.stdout
    assert not source.exists()


def test_upgrade_preflight_precedes_version_switch_and_launchd() -> None:
    """Mac 安装程序先检验数据并完成在线备份，才允许碰 Keychain/current/launchd。"""

    source = INSTALL.read_text(encoding="utf-8")
    assert source.index('python3 "$DB_COMPAT" --database "$DATABASE_FILE"') < source.index(
        'mkdir -p "$VERSIONS_ROOT"'
    )
    assert source.index('--backup-dir "$RUNTIME_ROOT/backups"') < source.index(
        'security find-generic-password'
    )
    assert source.index('--backup-dir "$RUNTIME_ROOT/backups"') < source.index(
        'mv -h "$CURRENT.next" "$CURRENT"'
    )
    assert "2.2.0-phase2-slice1" not in source
    assert "PRODUCT_VERSION" in source
    assert 'launchctl print "gui/$UID/$label"' in source
    assert 'launchctl bootstrap "gui/$UID" "$LAUNCH_AGENTS/$label.plist"' in source

    # Windows 只能通过 SSH loopback 或可信 HTTPS 与 Core 通信。
    plist = LAUNCHD.read_text(encoding="utf-8")
    assert "<key>PICOTOO_API_HOST</key>" in plist
    assert "<string>127.0.0.1</string>" in plist


def test_actual_schema24_created_by_23_core_is_compatible(tmp_path: Path) -> None:
    """结合真实 2.3 的迁移代码验证，而非只依赖手写 SQLite 表结构。"""

    from picotoopet_core.db.database import CURRENT_SCHEMA_VERSION, Database

    assert CURRENT_SCHEMA_VERSION == 24
    path = tmp_path / "real-schema24.db"
    db = Database(path)
    db.open()
    try:
        db.apply_migrations()
    finally:
        db.close()
    check = _run(path)
    assert check.returncode == 0, check.stderr
    assert "SCHEMA=COMPATIBLE_24" in check.stdout


def test_installed_core_requires_existing_database(tmp_path: Path) -> None:
    """恢复现场已有 current 链接时，缺失历史数据库必须 STOP，绝不初始化空库。"""

    source = tmp_path / "database" / "core.db"
    result = _run(source, require_existing=True)
    assert result.returncode == 2
    assert "STOP=DATABASE_COMPATIBILITY:MISSING_EXISTING_DATABASE" in result.stderr
    assert not source.exists()
    installer = INSTALL.read_text(encoding="utf-8")
    assert 'DB_REQUIRE=(--require-existing)' in installer
    assert '"${DB_REQUIRE[@]}"' in installer


def test_dangling_database_symlink_is_not_fresh_install(tmp_path: Path) -> None:
    """无论 Unix 链接目标是否存在，都不得误判成安全的新 DB。"""

    source = tmp_path / "core.db"
    try:
        source.symlink_to(tmp_path / "missing-target.db")
    except (OSError, NotImplementedError):
        pytest.skip("This runner cannot create symlinks")
    result = _run(source)
    assert result.returncode == 2
    assert "UNSAFE_EXISTING_DATABASE" in result.stderr


def test_installer_product_version_regex_matches_real_runtime() -> None:
    """解析实际安装脚本的 Bash 正则，防止双反斜杠让 2.3.27.1 无法安装。"""

    if shutil.which("bash") is None:
        pytest.skip("Bash unavailable on runner")
    installer = INSTALL.read_text(encoding="utf-8")
    line = next(
        line for line in installer.splitlines()
        if line.startswith('if [[ ! "$PRODUCT_VERSION" =~ ')
    )
    pattern = line.removeprefix('if [[ ! "$PRODUCT_VERSION" =~ ').removesuffix(' ]]; then')
    for version, expected in (("2.3.27.1", 0), ("2.2.0", 1), ("2x3x27x1", 1)):
        result = subprocess.run(
            ["bash", "-c", f'PRODUCT_VERSION={version}; [[ "$PRODUCT_VERSION" =~ {pattern} ]]'],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == expected, (version, result.stderr)
    assert 'VERSION="${PRODUCT_VERSION}-v31-compat-' in installer
    assert '-${BASHPID}"' in installer


def test_core_only_upgrade_never_launches_supervisor_or_worker() -> None:
    """当前阶段允许 Core 升级，但不得将 Health Supervisor、Worker 或 GPU 自动启动。"""

    installer = INSTALL.read_text(encoding="utf-8")
    assert 'label=com.picotoopet.mac-core' in installer
    assert 'for name in ("com.picotoopet.mac-core.plist",):' in installer
    assert 'label=com.picotoopet.health-supervisor' not in installer
    assert 'com.picotoopet.health-supervisor.plist"' not in installer
    assert "picotoopet-core worker" not in installer
    rollback = (ROOT / "scripts/mac/ROLLBACK_MAC.command").read_text(encoding="utf-8")
    assert "com.picotoopet.health-supervisor" not in rollback


def test_23_production_authority_survives_v31_ui_integration() -> None:
    """V3.1 Studio 不得整文件覆盖真实 2.3 的生产、审批和 Worker 入口。"""

    app = (ROOT / "src/picotoopet_core/api/app.py").read_text(encoding="utf-8")
    for route in (
        "production.router",
        "autonomous_goals.router",
        "creative_intelligence.router",
        "postproduction.router",
        "owner_structured_reviews.router",
        "workers.router",
    ):
        assert re.search(r"app\.include_router\(\s*" + re.escape(route), app)

    production = (
        ROOT / "src/picotoopet_core/api/routes/production.py"
    ).read_text(encoding="utf-8")
    for endpoint in (
        "/production/jobs/{production_job_id}/worker-challenge",
        "/production/jobs/{production_job_id}/witness/preflight",
        "/production/jobs/{production_job_id}/claim",
    ):
        assert endpoint in production
