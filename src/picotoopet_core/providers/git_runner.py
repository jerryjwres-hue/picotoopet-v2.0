"""Provider worktree 专用的固定 Git 命令运行器。"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


class GitCommandError(RuntimeError):
    """固定 Git 操作失败。"""


class GitCommandRunner:
    """只暴露 Provider worktree 所需的固定 Git 操作。"""

    def __init__(self, repository: Path) -> None:
        self.repository = repository.expanduser().resolve(strict=True)

    def current_branch(self) -> str:
        return self._capture("branch", "--show-current").strip()

    def is_clean(self) -> bool:
        return not self._capture("status", "--porcelain").strip()

    def add_detached_worktree(self, destination: Path, base_commit: str) -> None:
        self._run(
            "worktree",
            "add",
            "--detach",
            str(destination),
            base_commit,
            timeout_seconds=60,
        )

    def remove_worktree(self, destination: Path) -> None:
        self._run(
            "worktree",
            "remove",
            str(destination),
            timeout_seconds=60,
        )

    def changed_paths(self, destination: Path) -> tuple[str, ...]:
        output = self._capture(
            "-C",
            str(destination),
            "status",
            "--porcelain=v1",
            "-z",
        )
        values = output.split("\x00")
        paths: list[str] = []
        for value in values:
            if not value:
                continue
            if len(value) < 4:
                raise GitCommandError("Git 变更记录无效。")
            path = value[3:]
            if " -> " in path:
                _, path = path.split(" -> ", maxsplit=1)
            paths.append(path)
        return tuple(paths)

    def _capture(self, *arguments: str) -> str:
        return self._run(*arguments, timeout_seconds=30)

    def _run(self, *arguments: str, timeout_seconds: int) -> str:
        command = ["git", "-C", str(self.repository), *arguments]
        result = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self._safe_environment(),
            text=True,
            encoding="utf-8",
            errors="strict",
            timeout=timeout_seconds,
            check=False,
        )
        if result.returncode != 0:
            raise GitCommandError("固定 Git 操作失败。")
        return result.stdout

    @staticmethod
    def _safe_environment() -> dict[str, str]:
        allowed = ("HOME", "PATH", "TMPDIR", "LANG", "LC_ALL")
        return {
            key: value
            for key in allowed
            if (value := os.environ.get(key)) is not None
        }
