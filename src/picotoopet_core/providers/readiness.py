"""Codex CLI 可执行性和本机认证状态的非交互探测。"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .models import ProviderReadinessStatus


class CodexReadinessProbe:
    """只运行固定 `codex login status`，不返回或持久化其原始输出。"""

    def __init__(self, executable: Path | None) -> None:
        self.executable = executable

    def status(self) -> ProviderReadinessStatus:
        if self.executable is None:
            return ProviderReadinessStatus.UNAVAILABLE
        executable = self.executable.expanduser()
        if not executable.is_file() or not os.access(executable, os.X_OK):
            return ProviderReadinessStatus.UNAVAILABLE
        try:
            result = subprocess.run(
                [str(executable), "login", "status"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=self._safe_environment(),
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return ProviderReadinessStatus.UNAVAILABLE
        if result.returncode == 0:
            return ProviderReadinessStatus.READY
        return ProviderReadinessStatus.NOT_AUTHENTICATED

    @staticmethod
    def _safe_environment() -> dict[str, str]:
        allowed = ("HOME", "PATH", "TMPDIR", "LANG", "LC_ALL")
        return {
            key: value
            for key in allowed
            if (value := os.environ.get(key)) is not None
        }
