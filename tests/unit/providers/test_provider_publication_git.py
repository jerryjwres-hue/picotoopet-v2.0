from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from picotoopet_core.providers.publication_git import (
    PublicationGitError,
    PublicationGitPublisher,
)


def run_git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return result.stdout.strip()


def make_repo_and_remote(tmp_path: Path) -> tuple[Path, Path, str, str]:
    repo = tmp_path / "repo"
    remote = tmp_path / "remote.git"
    repo.mkdir()
    run_git(repo, "init", "-b", "feature/safe-base")
    run_git(repo, "config", "user.name", "PicotooPet Test")
    run_git(repo, "config", "user.email", "test@picotoopet.invalid")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    run_git(repo, "add", "README.md")
    run_git(repo, "commit", "-m", "base")
    base = run_git(repo, "rev-parse", "HEAD")
    (repo / "README.md").write_text("candidate\n", encoding="utf-8")
    run_git(repo, "add", "README.md")
    run_git(repo, "commit", "-m", "candidate")
    candidate = run_git(repo, "rev-parse", "HEAD")
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    run_git(repo, "push", str(remote), f"{base}:refs/heads/feature/safe-base")
    return repo, remote, base, candidate


def test_publication_git_reuses_exact_ref_and_never_runs_pre_push(tmp_path: Path) -> None:
    repo, remote, base, candidate = make_repo_and_remote(tmp_path)
    sentinel = tmp_path / "pre-push-ran"
    hook = repo / ".git" / "hooks" / "pre-push"
    hook.write_text(f"#!/bin/sh\ntouch '{sentinel}'\nexit 91\n", encoding="utf-8")
    hook.chmod(0o755)
    publisher = PublicationGitPublisher(repo)
    ref = "refs/heads/picotoopet/commit-candidates/11111111-1111-1111-1111-111111111111"

    publisher.verify_base(str(remote), "feature/safe-base", base)
    checks = publisher.ensure_remote_ref(str(remote), ref, candidate)
    publisher.ensure_remote_ref(str(remote), ref, candidate)

    assert "remote_ref_exact" in checks
    assert not sentinel.exists()
    assert publisher.read_remote_ref(str(remote), ref) == candidate


def test_publication_git_never_overwrites_conflicting_ref(tmp_path: Path) -> None:
    repo, remote, _base, candidate = make_repo_and_remote(tmp_path)
    ref = "refs/heads/picotoopet/commit-candidates/22222222-2222-2222-2222-222222222222"
    run_git(repo, "push", str(remote), f"HEAD^:{ref}")
    publisher = PublicationGitPublisher(repo)

    with pytest.raises(PublicationGitError, match="PUBLICATION_REMOTE_REF_CONFLICT"):
        publisher.ensure_remote_ref(str(remote), ref, candidate)
