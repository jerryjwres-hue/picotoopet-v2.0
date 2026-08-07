from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from picotoopet_core.providers.commit_models import (
    ProviderCommitCandidateRecord,
    ProviderCommitStatus,
)


def make_record(**overrides: object) -> ProviderCommitCandidateRecord:
    """构造一个合法的 Commit Candidate 安全事实。"""

    commit_candidate_id = str(uuid4())
    values: dict[str, object] = {
        "commit_candidate_id": commit_candidate_id,
        "adoption_candidate_id": str(uuid4()),
        "session_id": str(uuid4()),
        "return_id": "return-model-test",
        "status": ProviderCommitStatus.WAITING_APPROVAL,
        "base_commit": "a" * 40,
        "change_set_digest": "b" * 64,
        "approval_id": str(uuid4()),
        "message_preview": f"PicotooPet adoption candidate {commit_candidate_id}",
        "message_digest": "c" * 64,
        "local_ref": f"refs/picotoopet/commit-candidates/{commit_candidate_id}",
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    values.update(overrides)
    return ProviderCommitCandidateRecord.model_validate(values)


def test_commit_candidate_model_accepts_only_fixed_namespaced_ref() -> None:
    record = make_record()
    assert record.local_ref.startswith("refs/picotoopet/commit-candidates/")

    with pytest.raises(ValidationError):
        make_record(local_ref="refs/heads/main")


def test_commit_candidate_model_rejects_unknown_fields_and_bad_hashes() -> None:
    valid = make_record().model_dump(mode="python")
    valid["branch"] = "feature/escape"
    with pytest.raises(ValidationError):
        ProviderCommitCandidateRecord.model_validate(valid)

    with pytest.raises(ValidationError):
        make_record(change_set_digest="not-a-digest")


def test_commit_ready_requires_closed_enum_value_not_free_text() -> None:
    assert make_record(status="commit_ready").status is ProviderCommitStatus.COMMIT_READY
    with pytest.raises(ValidationError):
        make_record(status="pushed")
