"""Provider worktree 专用的固定 Git 命令运行器。"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


class GitCommandError(RuntimeError):
    """固定 Git 操作失败。"""


@dataclass(frozen=True, slots=True)
class GitChangeEntry:
    """Git porcelain 中一个结构化路径变化。"""

    status: str
    path: str
    source_path: str | None = None


class GitCommandRunner:
    """只暴露 Provider/adoption worktree 所需的固定 Git 操作。"""

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
        """固定强制删除 Session worktree，避免 Provider 变更阻止清理。"""

        self._run(
            "worktree",
            "remove",
            "--force",
            str(destination),
            timeout_seconds=60,
        )

    def change_entries(self, destination: Path) -> tuple[GitChangeEntry, ...]:
        """读取固定 porcelain v1 记录并保留 rename/copy 事实。"""

        output = self._capture(
            "-C",
            str(destination),
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "-z",
        )
        values = output.split("\x00")
        entries: list[GitChangeEntry] = []
        index = 0
        while index < len(values):
            value = values[index]
            index += 1
            if not value:
                continue
            if len(value) < 4:
                raise GitCommandError("Git 变更记录无效。")
            status = value[:2]
            path = value[3:]
            source_path = None
            if "R" in status or "C" in status:
                if index >= len(values) or not values[index]:
                    raise GitCommandError("Git rename/copy 记录无效。")
                source_path = values[index]
                index += 1
            entries.append(GitChangeEntry(status=status, path=path, source_path=source_path))
        return tuple(entries)

    def changed_paths(self, destination: Path) -> tuple[str, ...]:
        """兼容旧调用方，只返回最终路径。"""

        return tuple(entry.path for entry in self.change_entries(destination))

    def base_file_bytes(self, base_commit: str, path: str) -> bytes:
        """从不可变 base commit 读取单个 blob，不访问工作区正文。"""

        return self._run_bytes(
            "show",
            f"{base_commit}:{path}",
            timeout_seconds=30,
        )

    def diff_check(self, destination: Path) -> None:
        """执行固定 `git diff --check`，用于 adoption 静态校验。"""

        self._run("-C", str(destination), "diff", "--check", timeout_seconds=30)

    def _capture(self, *arguments: str) -> str:
        return self._run(*arguments, timeout_seconds=30)

    def _run(self, *arguments: str, timeout_seconds: int) -> str:
        command = ["git", "-C", str(self.repository), *arguments]
        result = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            capture_output=True,
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

    def _run_bytes(self, *arguments: str, timeout_seconds: int) -> bytes:
        command = ["git", "-C", str(self.repository), *arguments]
        result = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self._safe_environment(),
            timeout=timeout_seconds,
            check=False,
        )
        if result.returncode != 0:
            raise GitCommandError("固定 Git blob 读取失败。")
        return result.stdout

    @staticmethod
    def _safe_environment() -> dict[str, str]:
        allowed = ("HOME", "PATH", "TMPDIR", "LANG", "LC_ALL")
        return {
            key: value
            for key in allowed
            if (value := os.environ.get(key)) is not None
        }
