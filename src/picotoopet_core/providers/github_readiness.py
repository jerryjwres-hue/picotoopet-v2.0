"""GitHub CLI 可执行性与认证状态的非交互探测。"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


class GitHubReadinessProbe:
    """只运行固定认证状态查询，不读取或持久化认证输出。"""

    def __init__(self, executable: Path | None) -> None:
        self.executable = executable

    def ready(self) -> bool:
        executable = self.executable
        if executable is None:
            return False
        resolved = executable.expanduser()
        if not resolved.is_file() or not os.access(resolved, os.X_OK):
            return False
        environment = {
            key: value
            for key in ("HOME", "PATH", "TMPDIR", "LANG", "LC_ALL")
            if (value := os.environ.get(key)) is not None
        }
        environment["GH_PROMPT_DISABLED"] = "1"
        try:
            result = subprocess.run(
                [str(resolved), "auth", "status", "--hostname", "github.com"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=environment,
                timeout=10,
                check=False,
                shell=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return result.returncode == 0
