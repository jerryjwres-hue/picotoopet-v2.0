from __future__ import annotations

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
    run_git(repository, "init", "-b", "feature/provider-test")
    run_git(repository, "config", "user.name", "PicotooPet Test")
    run_git(repository, "config", "user.email", "test@picotoopet.invalid")
    (repository / "src").mkdir()
    (repository / "src" / "base.txt").write_text("base\n", encoding="utf-8")
    run_git(repository, "add", "src/base.txt")
    run_git(repository, "commit", "-m", "base")
    return repository, run_git(repository, "rev-parse", "HEAD")


def test_worktree_create_validate_and_cleanup(tmp_path: Path) -> None:
    repository, base_commit = make_repository(tmp_path)
    worktree_root = tmp_path / "sessions"
    manager = CodexWorktreeManager(repository=repository, worktree_root=worktree_root)

    worktree = manager.create(
        session_id=str(uuid4()),
        base_commit=base_commit,
        allowed_write=("src",),
    )
    changed = worktree.path / "src" / "approved.txt"
    changed.write_text("approved change\n", encoding="utf-8")

    paths = manager.changed_paths(worktree)
    assert paths == ("src/approved.txt",)
    assert tuple(map(str, manager.validate_changed_paths(worktree, paths))) == (
        "src/approved.txt",
    )

    manager.cleanup(worktree)
    assert not worktree.path.exists()
    assert run_git(repository, "worktree", "list", "--porcelain").count("worktree ") == 1


def test_worktree_rejects_paths_outside_allowlist_links_and_too_many_files(
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
        with pytest.raises(CodexWorktreeError, match="allowed_write"):
            manager.validate_changed_paths(worktree, ("docs/outside.txt",))
        with pytest.raises(CodexWorktreeError, match="数量"):
            manager.validate_changed_paths(
                worktree,
                tuple(f"src/file-{index}.txt" for index in range(6)),
            )
        link = worktree.path / "src" / "linked.txt"
        link.symlink_to(worktree.path / "src" / "base.txt")
        with pytest.raises(CodexWorktreeError, match="symlink"):
            manager.validate_changed_paths(worktree, ("src/linked.txt",))
    finally:
        manager.cleanup(worktree)


def test_worktree_rejects_protected_or_dirty_source_repository(tmp_path: Path) -> None:
    repository, base_commit = make_repository(tmp_path)
    run_git(repository, "branch", "-m", "main")
    manager = CodexWorktreeManager(
        repository=repository,
        worktree_root=tmp_path / "sessions-main",
    )
    with pytest.raises(CodexWorktreeError, match="保护分支"):
        manager.create(
            session_id=str(uuid4()),
            base_commit=base_commit,
            allowed_write=("src",),
        )

    run_git(repository, "branch", "-m", "feature/provider-test")
    (repository / "untracked.txt").write_text("dirty\n", encoding="utf-8")
    manager = CodexWorktreeManager(
        repository=repository,
        worktree_root=tmp_path / "sessions-dirty",
    )
    with pytest.raises(CodexWorktreeError, match="clean"):
        manager.create(
            session_id=str(uuid4()),
            base_commit=base_commit,
            allowed_write=("src",),
        )
