from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

from picotoopet_core.worker.codex_worktree import (
    CodexWorktreeError,
    CodexWorktreeManager,
)


def run_git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return result.stdout.strip()


def make_repository(tmp_path: Path) -> tuple[Path, str]:
    repository = tmp_path / "repository"
    repository.mkdir()
    run_git(repository, "init", "-b", "feature/provider-capture")
    run_git(repository, "config", "user.name", "PicotooPet Test")
    run_git(repository, "config", "user.email", "test@picotoopet.invalid")
    (repository / "src").mkdir()
    (repository / "src" / "modify.txt").write_text("before modify\n", encoding="utf-8")
    (repository / "src" / "delete.txt").write_text("before delete\n", encoding="utf-8")
    run_git(repository, "add", "src/modify.txt", "src/delete.txt")
    run_git(repository, "commit", "-m", "base")
    return repository, run_git(repository, "rev-parse", "HEAD")


def test_capture_changes_returns_deterministic_add_modify_delete_payloads_and_diff(
    tmp_path: Path,
) -> None:
    repository, base_commit = make_repository(tmp_path)
    manager = CodexWorktreeManager(
        repository=repository,
        worktree_root=tmp_path / "sessions",
    )
    worktree = manager.create(
        session_id=str(uuid4()),
        base_commit=base_commit,
        allowed_write=("src",),
    )
    try:
        (worktree.path / "src" / "modify.txt").write_text(
            "after modify\n",
            encoding="utf-8",
        )
        (worktree.path / "src" / "delete.txt").unlink()
        (worktree.path / "src" / "new.txt").write_text("new file\n", encoding="utf-8")

        captured = manager.capture_changes(worktree)
        assert [change.path for change in captured.changes] == [
            "src/delete.txt",
            "src/modify.txt",
            "src/new.txt",
        ]
        assert [change.operation for change in captured.changes] == [
            "delete",
            "modify",
            "add",
        ]

        deleted, modified, added = captured.changes
        assert deleted.base_sha256 == hashlib.sha256(b"before delete\n").hexdigest()
        assert deleted.result_text is None
        assert modified.base_sha256 == hashlib.sha256(b"before modify\n").hexdigest()
        assert modified.result_text == "after modify\n"
        assert added.base_sha256 is None
        assert added.result_text == "new file\n"

        assert "src/delete.txt" in captured.review_diff
        assert "src/modify.txt" in captured.review_diff
        assert "src/new.txt" in captured.review_diff
        assert "after modify" in captured.review_diff
        assert "new file" in captured.review_diff
        assert "before delete" in captured.review_diff
    finally:
        manager.cleanup(worktree)


def test_capture_changes_rejects_rename_instead_of_guessing_operation(tmp_path: Path) -> None:
    repository, base_commit = make_repository(tmp_path)
    manager = CodexWorktreeManager(
        repository=repository,
        worktree_root=tmp_path / "sessions",
    )
    worktree = manager.create(
        session_id=str(uuid4()),
        base_commit=base_commit,
        allowed_write=("src",),
    )
    try:
        run_git(worktree.path, "mv", "src/modify.txt", "src/renamed.txt")
        with pytest.raises(CodexWorktreeError, match="rename"):
            manager.capture_changes(worktree)
    finally:
        manager.cleanup(worktree)


def test_capture_changes_rejects_non_utf8_result_file(tmp_path: Path) -> None:
    repository, base_commit = make_repository(tmp_path)
    manager = CodexWorktreeManager(
        repository=repository,
        worktree_root=tmp_path / "sessions",
    )
    worktree = manager.create(
        session_id=str(uuid4()),
        base_commit=base_commit,
        allowed_write=("src",),
    )
    try:
        (worktree.path / "src" / "new.bin").write_bytes(b"\xff\xfe\x00\x01")
        with pytest.raises(CodexWorktreeError, match="UTF-8"):
            manager.capture_changes(worktree)
    finally:
        manager.cleanup(worktree)
