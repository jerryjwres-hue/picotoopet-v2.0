from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

from picotoopet_core.providers.artifact_store import ProviderReturnArtifactStore
from picotoopet_core.providers.change_set import ProviderChangeInput
from picotoopet_core.providers.commit_execution import (
    CommitExecutionError,
    ProviderLocalCommitBuilder,
)
from picotoopet_core.providers.commit_service import ProviderCommitService


def run_git(repository: Path, *arguments: str) -> str:
    """以参数向量运行测试仓库 Git，不经过 shell。"""

    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return result.stdout.strip()


def make_repository(tmp_path: Path) -> tuple[Path, str, Path, Path]:
    """创建带恶意 hook/filter witness 的干净 feature 仓库。"""

    repository = tmp_path / "repo"
    repository.mkdir()
    run_git(repository, "init", "-b", "feature/commit-test")
    run_git(repository, "config", "user.name", "PicotooPet Test")
    run_git(repository, "config", "user.email", "test@picotoopet.invalid")

    (repository / "docs").mkdir()
    (repository / "docs" / "modify.txt").write_text("before\n", encoding="utf-8")
    (repository / "docs" / "delete.txt").write_text("delete me\n", encoding="utf-8")
    (repository / ".gitattributes").write_text("docs/*.txt filter=evil\n", encoding="utf-8")
    run_git(repository, "add", ".")
    run_git(repository, "commit", "-m", "base")
    base_commit = run_git(repository, "rev-parse", "HEAD")

    hook_sentinel = tmp_path / "hook-ran.txt"
    hooks = repository / ".git" / "hooks"
    for hook_name in ("pre-commit", "commit-msg"):
        hook = hooks / hook_name
        hook.write_text(
            f"#!/bin/sh\nprintf hook > '{hook_sentinel}'\nexit 91\n",
            encoding="utf-8",
        )
        hook.chmod(0o755)

    filter_sentinel = tmp_path / "filter-ran.txt"
    filter_script = tmp_path / "evil-filter.sh"
    filter_script.write_text(
        f"#!/bin/sh\nprintf filter > '{filter_sentinel}'\ncat\n",
        encoding="utf-8",
    )
    filter_script.chmod(0o755)
    run_git(repository, "config", "filter.evil.clean", str(filter_script))
    run_git(repository, "config", "filter.evil.smudge", str(filter_script))
    return repository, base_commit, hook_sentinel, filter_sentinel


def make_artifact(
    root: Path,
    base_commit: str,
) -> tuple[ProviderReturnArtifactStore, str, str]:
    """生成 add/modify/delete 三类规范化变更。"""

    store = ProviderReturnArtifactStore(root)
    stored = store.write(
        return_id="return-commit-candidate",
        base_commit=base_commit,
        changes=[
            ProviderChangeInput(
                operation="modify",
                path="docs/modify.txt",
                base_sha256=hashlib.sha256(b"before\n").hexdigest(),
                result_text="after\n",
            ),
            ProviderChangeInput(
                operation="delete",
                path="docs/delete.txt",
                base_sha256=hashlib.sha256(b"delete me\n").hexdigest(),
            ),
            ProviderChangeInput(
                operation="add",
                path="docs/new.txt",
                result_text="new\n",
            ),
        ],
        review_diff="bounded review diff\n",
    )
    return store, stored.change_set_digest, stored.return_id


def test_local_commit_builder_avoids_hooks_filters_and_writes_only_namespaced_ref(
    tmp_path: Path,
) -> None:
    """真实 Git plumbing 必须创建 exact-parent commit，且 hooks/filters 绝不能执行。"""

    repository, base_commit, hook_sentinel, filter_sentinel = make_repository(tmp_path)
    store, digest, return_id = make_artifact(tmp_path / "artifacts", base_commit)
    worktree_root = tmp_path / "commit-worktrees"
    builder = ProviderLocalCommitBuilder(
        repository=repository,
        worktree_root=worktree_root,
        artifact_store=store,
    )
    commit_candidate_id = str(uuid4())
    adoption_candidate_id = str(uuid4())
    session_id = str(uuid4())
    heads_before = run_git(repository, "for-each-ref", "--format=%(refname) %(objectname)", "refs/heads")
    tags_before = run_git(repository, "for-each-ref", "--format=%(refname) %(objectname)", "refs/tags")
    remotes_before = run_git(
        repository,
        "for-each-ref",
        "--format=%(refname) %(objectname)",
        "refs/remotes",
    )

    result = builder.create(
        commit_candidate_id=commit_candidate_id,
        adoption_candidate_id=adoption_candidate_id,
        session_id=session_id,
        return_id=return_id,
        base_commit=base_commit,
        change_set_digest=digest,
    )

    assert not hook_sentinel.exists()
    assert not filter_sentinel.exists()
    assert run_git(repository, "rev-parse", "HEAD") == base_commit
    assert run_git(repository, "status", "--porcelain") == ""
    assert run_git(repository, "for-each-ref", "--format=%(refname) %(objectname)", "refs/heads") == heads_before
    assert run_git(repository, "for-each-ref", "--format=%(refname) %(objectname)", "refs/tags") == tags_before
    assert (
        run_git(repository, "for-each-ref", "--format=%(refname) %(objectname)", "refs/remotes")
        == remotes_before
    )
    assert result.local_ref == ProviderCommitService.local_ref(commit_candidate_id)
    assert run_git(repository, "rev-parse", "--verify", result.local_ref) == result.commit_sha
    assert run_git(repository, "rev-list", "--parents", "-n", "1", result.commit_sha).split() == [
        result.commit_sha,
        base_commit,
    ]
    assert run_git(repository, "rev-parse", f"{result.commit_sha}^{{tree}}") == result.tree_sha
    assert run_git(
        repository,
        "diff-tree",
        "--no-commit-id",
        "--name-status",
        "-r",
        base_commit,
        result.commit_sha,
    ).splitlines() == [
        "D\tdocs/delete.txt",
        "M\tdocs/modify.txt",
        "A\tdocs/new.txt",
    ]
    body = run_git(repository, "cat-file", "-p", result.commit_sha)
    assert f"PicotooPet-Adoption-Candidate: {adoption_candidate_id}" in body
    assert f"PicotooPet-Return: {return_id}" in body
    assert f"PicotooPet-Session: {session_id}" in body
    assert f"PicotooPet-Base-Commit: {base_commit}" in body
    assert f"PicotooPet-Change-Set-SHA256: {digest}" in body
    assert not worktree_root.exists() or list(worktree_root.iterdir()) == []


def test_local_commit_builder_ref_conflict_never_overwrites_existing_commit(
    tmp_path: Path,
) -> None:
    """预占 namespaced ref 指向另一提交时必须固定失败且保持原值。"""

    repository, base_commit, _, _ = make_repository(tmp_path)
    store, digest, return_id = make_artifact(tmp_path / "artifacts", base_commit)
    builder = ProviderLocalCommitBuilder(
        repository=repository,
        worktree_root=tmp_path / "commit-worktrees",
        artifact_store=store,
    )
    commit_candidate_id = str(uuid4())
    local_ref = ProviderCommitService.local_ref(commit_candidate_id)
    base_tree = run_git(repository, "rev-parse", f"{base_commit}^{{tree}}")
    conflicting_commit = run_git(
        repository,
        "commit-tree",
        base_tree,
        "-p",
        base_commit,
        "-m",
        "conflicting local commit",
    )
    run_git(repository, "update-ref", local_ref, conflicting_commit)

    with pytest.raises(CommitExecutionError, match="COMMIT_REF_CONFLICT"):
        builder.create(
            commit_candidate_id=commit_candidate_id,
            adoption_candidate_id=str(uuid4()),
            session_id=str(uuid4()),
            return_id=return_id,
            base_commit=base_commit,
            change_set_digest=digest,
        )

    assert run_git(repository, "rev-parse", "--verify", local_ref) == conflicting_commit


def test_local_commit_builder_is_idempotent_for_same_candidate_and_provenance(
    tmp_path: Path,
) -> None:
    """同一候选重复执行必须复用同一受支持 ref，而不是产生第二个提交事实。"""

    repository, base_commit, _, _ = make_repository(tmp_path)
    store, digest, return_id = make_artifact(tmp_path / "artifacts", base_commit)
    builder = ProviderLocalCommitBuilder(
        repository=repository,
        worktree_root=tmp_path / "commit-worktrees",
        artifact_store=store,
    )
    commit_candidate_id = str(uuid4())
    adoption_candidate_id = str(uuid4())
    session_id = str(uuid4())
    arguments = {
        "commit_candidate_id": commit_candidate_id,
        "adoption_candidate_id": adoption_candidate_id,
        "session_id": session_id,
        "return_id": return_id,
        "base_commit": base_commit,
        "change_set_digest": digest,
    }

    first = builder.create(**arguments)
    second = builder.create(**arguments)

    assert second.commit_sha == first.commit_sha
    assert second.tree_sha == first.tree_sha
    assert second.local_ref == first.local_ref
    refs = run_git(
        repository,
        "for-each-ref",
        "--format=%(refname)",
        "refs/picotoopet/commit-candidates",
    ).splitlines()
    assert refs == [first.local_ref]
