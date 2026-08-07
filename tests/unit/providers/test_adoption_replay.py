from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

from picotoopet_core.providers.artifact_store import (
    ProviderArtifactError,
    ProviderReturnArtifactStore,
)
from picotoopet_core.providers.change_set import ProviderChangeInput


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


def make_repository(tmp_path: Path) -> tuple[Path, str]:
    repository = tmp_path / "repo"
    repository.mkdir()
    run_git(repository, "init", "-b", "feature/adoption-test")
    run_git(repository, "config", "user.name", "PicotooPet Test")
    run_git(repository, "config", "user.email", "test@picotoopet.invalid")
    (repository / "docs").mkdir()
    (repository / "docs" / "modify.txt").write_text("before\n", encoding="utf-8")
    (repository / "docs" / "delete.txt").write_text("delete me\n", encoding="utf-8")
    run_git(repository, "add", ".")
    run_git(repository, "commit", "-m", "base")
    return repository, run_git(repository, "rev-parse", "HEAD")


def make_artifact(root: Path, base_commit: str) -> tuple[ProviderReturnArtifactStore, str, str]:
    store = ProviderReturnArtifactStore(root)
    base_modify = hashlib.sha256(b"before\n").hexdigest()
    base_delete = hashlib.sha256(b"delete me\n").hexdigest()
    stored = store.write(
        return_id="return-adoption",
        base_commit=base_commit,
        changes=[
            ProviderChangeInput(
                operation="modify",
                path="docs/modify.txt",
                base_sha256=base_modify,
                result_text="after\n",
            ),
            ProviderChangeInput(
                operation="delete",
                path="docs/delete.txt",
                base_sha256=base_delete,
            ),
            ProviderChangeInput(
                operation="add",
                path="docs/new.txt",
                result_text="new\n",
            ),
        ],
        review_diff="review diff\n",
    )
    return store, stored.change_set_digest, stored.return_id


def test_adoption_replay_applies_exact_artifact_runs_static_checks_and_cleans_worktree(
    tmp_path: Path,
) -> None:
    from picotoopet_core.providers.adoption_execution import AdoptionArtifactApplier

    repository, base_commit = make_repository(tmp_path)
    store, digest, return_id = make_artifact(tmp_path / "artifacts", base_commit)
    worktree_root = tmp_path / "adoption-worktrees"
    applier = AdoptionArtifactApplier(
        repository=repository,
        worktree_root=worktree_root,
        artifact_store=store,
    )
    result = applier.apply(
        candidate_id=str(uuid4()),
        return_id=return_id,
        base_commit=base_commit,
        change_set_digest=digest,
        allowed_write=("docs",),
    )

    assert result.changed_file_count == 3
    assert result.validation_checks == ["base_hashes", "result_hashes", "git_diff_check", "utf8"]
    assert len(result.candidate_digest) == 64
    assert list(worktree_root.iterdir()) == []
    assert run_git(repository, "status", "--porcelain") == ""
    assert run_git(repository, "rev-parse", "HEAD") == base_commit
    assert len(run_git(repository, "log", "--oneline").splitlines()) == 1


def test_adoption_replay_rejects_base_file_hash_mismatch_and_still_cleans(tmp_path: Path) -> None:
    from picotoopet_core.providers.adoption_execution import (
        AdoptionArtifactApplier,
        AdoptionExecutionError,
    )

    repository, base_commit = make_repository(tmp_path)
    store = ProviderReturnArtifactStore(tmp_path / "artifacts")
    stored = store.write(
        return_id="return-bad-base",
        base_commit=base_commit,
        changes=[
            ProviderChangeInput(
                operation="modify",
                path="docs/modify.txt",
                base_sha256="0" * 64,
                result_text="after\n",
            )
        ],
        review_diff="review diff\n",
    )
    worktree_root = tmp_path / "adoption-worktrees"
    applier = AdoptionArtifactApplier(
        repository=repository,
        worktree_root=worktree_root,
        artifact_store=store,
    )

    with pytest.raises(AdoptionExecutionError, match="ADOPTION_BASE_MISMATCH"):
        applier.apply(
            candidate_id=str(uuid4()),
            return_id="return-bad-base",
            base_commit=base_commit,
            change_set_digest=stored.change_set_digest,
            allowed_write=("docs",),
        )
    assert list(worktree_root.iterdir()) == []
    assert run_git(repository, "status", "--porcelain") == ""


def test_adoption_replay_rejects_tampered_artifact_before_writing_worktree(tmp_path: Path) -> None:
    from picotoopet_core.providers.adoption_execution import (
        AdoptionArtifactApplier,
        AdoptionExecutionError,
    )

    repository, base_commit = make_repository(tmp_path)
    store, digest, return_id = make_artifact(tmp_path / "artifacts", base_commit)
    (tmp_path / "artifacts" / return_id / "payload" / "000.txt").write_text(
        "tampered\n",
        encoding="utf-8",
    )
    worktree_root = tmp_path / "adoption-worktrees"
    applier = AdoptionArtifactApplier(
        repository=repository,
        worktree_root=worktree_root,
        artifact_store=store,
    )

    with pytest.raises((AdoptionExecutionError, ProviderArtifactError), match="ARTIFACT_INVALID"):
        applier.apply(
            candidate_id=str(uuid4()),
            return_id=return_id,
            base_commit=base_commit,
            change_set_digest=digest,
            allowed_write=("docs",),
        )
    assert not worktree_root.exists() or list(worktree_root.iterdir()) == []
