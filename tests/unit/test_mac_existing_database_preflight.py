"""Mac installer never takes over existing newer SQLite databases."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
INSTALL = ROOT / "scripts" / "mac" / "INSTALL_MAC.command"


def test_preflight_refuses_existing_24_migrations_before_any_runtime_changes(tmp_path: Path) -> None:
    """安装脚本必须在修改 symlink、Keychain 和 launchd 之前就拒绝现有 v24 数据库。"""
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("Bash not installed")

    # 只运行真实安装器的只读预检片段，其余安装步骤完全不会执行。
    original = INSTALL.read_text(encoding="utf-8")
    start = original.index("# 只读预检必须先于任何版本指针")
    end = original.index('mkdir -p "$VERSIONS_ROOT"', start)
    preflight = original[start:end]
    runtime = tmp_path / "home" / "Library" / "Application Support" / "PicotooPetV2"
    database = runtime / "database" / "core.db"
    database.parent.mkdir(parents=True)
    database.write_bytes(b"EXISTING_DATABASE_MUST_NOT_BE_CHANGED")
    test_bin = tmp_path / "bin"
    test_bin.mkdir()
    fake_sqlite = test_bin / "sqlite3"
    fake_sqlite.write_text("#!/bin/sh\nprintf '24\\n'\n", encoding="utf-8")
    fake_sqlite.chmod(0o755)
    environment = os.environ.copy()
    environment["PATH"] = f"{test_bin}:{environment['PATH']}"
    script = (
        'set -euo pipefail\nRUNTIME_ROOT="' + str(runtime) + '"\n'
        + preflight
        + 'echo "MUST_NOT_REACH_INSTALL"\n'
    )
    outcome = subprocess.run(
        [bash, "-c", script],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
        timeout=10,
    )
    assert outcome.returncode != 0
    assert "STOP=UNSUPPORTED_DATABASE_VERSION_24" in outcome.stderr
    assert "MUST_NOT_REACH_INSTALL" not in outcome.stdout
    assert database.read_bytes() == b"EXISTING_DATABASE_MUST_NOT_BE_CHANGED"
    assert not (runtime / "versions").exists()
    assert not (runtime / "current").exists()


def test_install_preflight_order_and_frozen_version_compatibility() -> None:
    """受支持的迁移不能用 SELECT MAX(version) 代替逐表安全检查。"""
    text = INSTALL.read_text(encoding="utf-8")
    assert text.index("# 只读预检必须先于任何版本指针") < text.index('mkdir -p "$VERSIONS_ROOT"')
    assert "sqlite3 -readonly" in text
    assert "STOP=UNSUPPORTED_DATABASE_VERSION_" in text
    assert "STOP=INCOMPATIBLE_MIGRATION_004" in text
    assert text.index("STOP=INCOMPATIBLE_MIGRATION_004") < text.index('ln -sfn "$TARGET" "$CURRENT.next"')

