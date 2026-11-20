"""Parse the double-click Mac installer without installing anything."""

from __future__ import annotations

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
