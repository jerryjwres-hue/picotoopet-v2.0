from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from picotoopet_core.providers.publication_models import (
    ProviderPublicationCandidateRecord,
    ProviderPublicationStatus,
)


def make_record(**updates: object) -> ProviderPublicationCandidateRecord:
    publication_id = str(uuid4())
    payload: dict[str, object] = {
        "publication_candidate_id": publication_id,
        "commit_candidate_id": str(uuid4()),
        "session_id": str(uuid4()),
        "handoff_id": str(uuid4()),
        "status": ProviderPublicationStatus.WAITING_APPROVAL,
        "repo_url": "https://github.com/jerryjwres-hue/picotoopet-v2.0",
        "repository_slug": "jerryjwres-hue/picotoopet-v2.0",
        "base_ref": "feature/safe-base",
        "base_commit": "a" * 40,
        "commit_sha": "b" * 40,
        "change_set_digest": "c" * 64,
        "remote_ref": f"refs/heads/picotoopet/commit-candidates/{publication_id}",
        "remote_branch": f"picotoopet/commit-candidates/{publication_id}",
        "approval_id": str(uuid4()),
        "pr_title_digest": "d" * 64,
        "pr_body_digest": "e" * 64,
        "pr_number": None,
        "pr_url": None,
        "pr_head_sha": None,
        "validation_checks": [],
        "failure_code": None,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
        "finished_at": None,
    }
    payload.update(updates)
    return ProviderPublicationCandidateRecord.model_validate(payload)


def test_publication_record_accepts_only_fixed_github_repo_and_namespaced_ref() -> None:
    record = make_record()
    assert record.status is ProviderPublicationStatus.WAITING_APPROVAL
    assert record.remote_ref.startswith("refs/heads/picotoopet/commit-candidates/")

    with pytest.raises(ValidationError):
        make_record(repo_url="file:///tmp/remote.git")

    with pytest.raises(ValidationError):
        make_record(remote_ref="refs/heads/main")


def test_pr_ready_requires_pr_identity() -> None:
    with pytest.raises(ValidationError):
        make_record(status=ProviderPublicationStatus.PR_READY)

    record = make_record(
        status=ProviderPublicationStatus.PR_READY,
        pr_number=42,
        pr_url="https://github.com/jerryjwres-hue/picotoopet-v2.0/pull/42",
        pr_head_sha="b" * 40,
    )
    assert record.pr_number == 42
