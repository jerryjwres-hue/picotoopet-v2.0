"""Parse the double-click Mac installer without installing anything."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_INSTALLER = _ROOT / "scripts" / "mac" / "INSTALL_MAC.command"


def test_mac_installer_shell_syntax_without_running_installer() -> None:
    """确认 macOS 双击入口可以被 Bash 解析；此测试不安装/下载任何东西。"""
    shell = shutil.which("bash")
    if shell is None:
        pytest.skip("Bash is unavailable on this runner")
    completed = subprocess.run(
        [shell, "-n", str(_INSTALLER)],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr


def test_mac_launchagent_bootstrap_handles_inflight_unload(tmp_path: Path) -> None:
    """模拟 launchctl 卸载延迟以及 37 冲突；安装器必须完成受控重试。"""
    shell = shutil.which("bash")
    if shell is None:
        pytest.skip("Bash unavailable")

    # 仅执行已审查的 launchctl 段；不会安装依赖、访问 Keychain 或启动系统服务。
    source = _INSTALLER.read_text(encoding="utf-8")
    start = source.index("# 等待 launchd 异步移除旧服务完成")
    end = source.index("# 保留完整机器报告", start)
    script = "set -euo pipefail\n" + source[start:end]
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    agents = tmp_path / "LaunchAgents"
    agents.mkdir()
    state = tmp_path / "state"
    state.mkdir()
    launchctl = fake_bin / "launchctl"
    launchctl.write_text(
        "\n".join([
            "#!/bin/bash",
            "set -eu",
            'case "$1" in',
            "  bootout) exit 0 ;;",
            "  print)",
            '    name="${2##*/}"',
            '    if [ -e "$FAKE_STATE/$name.registered" ]; then exit 0; fi',
            '    if [ ! -e "$FAKE_STATE/$name.unloaded" ]; then',
            '      touch "$FAKE_STATE/$name.unloaded"',
            "      exit 0",
            "    fi",
            "    exit 113 ;;",
            "  bootstrap)",
            '    name="${3##*/}"',
            '    name="${name%.plist}"',
            '    printf "%s\\n" "$name" >> "$FAKE_STATE/bootstrap-calls"',
            '    if [ ! -e "$FAKE_STATE/$name.attempted" ]; then',
            '      touch "$FAKE_STATE/$name.attempted"',
            '      echo "Bootstrap failed: 37: Operation already in progress" >&2',
            "      exit 37",
            "    fi",
            '    touch "$FAKE_STATE/$name.registered"',
            "    exit 0 ;;",
            "esac",
            "exit 2",
        ]) + "\n",
        encoding="utf-8",
    )
    launchctl.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["FAKE_STATE"] = str(state)
    env["LAUNCH_AGENTS"] = str(agents)
    outcome = subprocess.run(
        [shell, "-c", script],
        capture_output=True, text=True, env=env, check=False, timeout=25,
    )
    assert outcome.returncode == 0, outcome.stderr
    calls = (state / "bootstrap-calls").read_text(encoding="utf-8").splitlines()
    for label in ("com.picotoopet.mac-core", "com.picotoopet.health-supervisor"):
        assert calls.count(label) == 2
        assert (state / f"{label}.registered").is_file()
