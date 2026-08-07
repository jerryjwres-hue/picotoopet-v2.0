"""Session 独占 Git worktree 的创建、路径检查和清理。"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from uuid import UUID

_GIT_WORKTREE_ADD = "git worktree add"
_GIT_WORKTREE_REMOVE = "git worktree remove"
_PROTECTED_BRANCH_NAMES = frozenset({"main", "master"})
_COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")


class CodexWorktreeError(RuntimeError):
    """worktree 策略或清理失败。"""


@dataclass(frozen=True, slots=True)
class CodexWorktree:
    """一个 Session 的隔离目录和允许写入范围。"""

    session_id: str
    path: Path
    base_commit: str
    allowed_write: tuple[PurePosixPath, ...]


class CodexWorktreeManager:
    """只从受信任仓库和不可变提交创建 Session 独占 worktree。"""

    def __init__(self, *, repository: Path, worktree_root: Path) -> None:
        self.repository = repository.expanduser().resolve(strict=True)
        self.worktree_root = worktree_root.expanduser().resolve()
        if not self.repository.is_dir() or self.repository.is_symlink():
            raise CodexWorktreeError("受信任仓库目录无效。")
        if not (self.repository / ".git").exists():
            raise CodexWorktreeError("受信任目录不是 Git 仓库。")
        if self.worktree_root == self.repository or self.repository in self.worktree_root.parents:
            raise CodexWorktreeError("worktree 根不能位于受信任仓库内部。")
        self.worktree_root.mkdir(parents=True, exist_ok=True)
        if self.worktree_root.is_symlink():
            raise CodexWorktreeError("worktree 根不能是 symlink。")

    def create(
        self,
        *,
        session_id: str,
        base_commit: str,
        allowed_write: tuple[str, ...],
    ) -> CodexWorktree:
        """使用 detached immutable commit 创建新 worktree。"""

        normalized_session = str(UUID(session_id))
        if not _COMMIT_PATTERN.fullmatch(base_commit):
            raise CodexWorktreeError("base_commit 必须是 40 位小写 SHA。")
        self._check_repository_state()
        roots = tuple(self._normalize_relative(value) for value in allowed_write)
        if not roots:
            raise CodexWorktreeError("allowed_write 不能为空。")
        destination = (self.worktree_root / normalized_session).resolve()
        if destination.parent != self.worktree_root:
            raise CodexWorktreeError("Session 目录逃逸。")
        if destination.exists():
            raise CodexWorktreeError("Session worktree 已存在。")

        command = [
            "git",
            "-C",
            str(self.repository),
            "worktree",
            "add",
            "--detach",
            str(destination),
            base_commit,
        ]
        self._run(command, operation=_GIT_WORKTREE_ADD)
        try:
            self._reject_links(destination)
        except Exception:
            self.cleanup(destination)
            raise
        return CodexWorktree(
            session_id=normalized_session,
            path=destination,
            base_commit=base_commit,
            allowed_write=roots,
        )

    def validate_changed_paths(
        self,
        worktree: CodexWorktree,
        changed_paths: tuple[str, ...],
    ) -> tuple[PurePosixPath, ...]:
        """拒绝 symlink、路径逃逸、保护分支名和允许根之外的变更。"""

        if len(changed_paths) > 5:
            raise CodexWorktreeError("变更文件数量超过 5。")
        normalized: list[PurePosixPath] = []
        for value in changed_paths:
            relative = self._normalize_relative(value)
            if relative.parts and relative.parts[0].lower() in _PROTECTED_BRANCH_NAMES:
                raise CodexWorktreeError("保护分支路径被拒绝。")
            if not any(relative == root or root in relative.parents for root in worktree.allowed_write):
                raise CodexWorktreeError("变更路径不在 allowed_write 中。")
            actual = (worktree.path / Path(*relative.parts)).resolve()
            if worktree.path not in actual.parents:
                raise CodexWorktreeError("变更路径逃逸 worktree。")
            if actual.is_symlink():
                raise CodexWorktreeError("symlink 变更被拒绝。")
            if actual.is_file() and actual.stat().st_size > 65536:
                raise CodexWorktreeError("变更文件超过 64 KiB。")
            normalized.append(relative)
        return tuple(normalized)

    def cleanup(self, worktree: CodexWorktree | Path) -> None:
        """删除 Git 登记和 Session 目录；失败时阻止继续执行。"""

        path = worktree.path if isinstance(worktree, CodexWorktree) else worktree
        resolved = path.expanduser().resolve()
        if resolved.parent != self.worktree_root:
            raise CodexWorktreeError("拒绝清理 worktree 根之外目录。")
        if not resolved.exists():
            return
        command = [
            "git",
            "-C",
            str(self.repository),
            "worktree",
            "remove",
            str(resolved),
        ]
        self._run(command, operation=_GIT_WORKTREE_REMOVE)
        if resolved.exists():
            shutil.rmtree(resolved)
        if resolved.exists():
            raise CodexWorktreeError("worktree cleanup 未完成。")

    def _check_repository_state(self) -> None:
        branch = self._capture(
            ["git", "-C", str(self.repository), "branch", "--show-current"]
        ).strip()
        if branch.lower() in _PROTECTED_BRANCH_NAMES:
            raise CodexWorktreeError("受信任仓库当前位于保护分支。")
        status = self._capture(
            ["git", "-C", str(self.repository), "status", "--porcelain"]
        )
        if status.strip():
            raise CodexWorktreeError("受信任仓库不是 clean 状态。")

    @staticmethod
    def _normalize_relative(value: str) -> PurePosixPath:
        if not value or "\\" in value or "\x00" in value:
            raise CodexWorktreeError("相对路径无效。")
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or "." in path.parts:
            raise CodexWorktreeError("相对路径逃逸。")
        if any(":" in part for part in path.parts):
            raise CodexWorktreeError("盘符路径被拒绝。")
        return path

    @staticmethod
    def _reject_links(root: Path) -> None:
        for path in root.rglob("*"):
            if path.is_symlink():
                raise CodexWorktreeError("worktree 包含 symlink。")

    @staticmethod
    def _run(command: list[str], *, operation: str) -> None:
        result = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            timeout=60,
            check=False,
        )
        if result.returncode != 0:
            raise CodexWorktreeError(f"{operation} 失败。")

    @staticmethod
    def _capture(command: list[str]) -> str:
        result = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            timeout=30,
            check=False,
        )
        if result.returncode != 0:
            raise CodexWorktreeError("Git 仓库检查失败。")
        return result.stdout
