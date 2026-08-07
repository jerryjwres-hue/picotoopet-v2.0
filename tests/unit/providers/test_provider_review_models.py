from __future__ import annotations

import importlib
import importlib.util
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError


MODULE = "picotoopet_core.providers.review_models"


def _load_review_models():
    assert importlib.util.find_spec(MODULE) is not None, (
        "Phase 10D-B review/adoption model module is not implemented yet"
    )
    return importlib.import_module(MODULE)


def test_review_models_are_strict_and_keep_only_safe_metadata() -> None:
    models = _load_review_models()
    artifact = models.ProviderReturnArtifactRecord(
        return_id="return-review",
        session_id="11111111-1111-1111-1111-111111111111",
        handoff_id="handoff-review",
        base_commit="a" * 40,
        change_set_digest="b" * 64,
        review_diff_digest="c" * 64,
        changed_file_count=1,
        payload_bytes=42,
        artifact_status="reviewable",
        created_at=datetime(2026, 8, 7, 15, 20, tzinfo=UTC),
    )
    assert artifact.changed_file_count == 1
    assert artifact.payload_bytes == 42

    with pytest.raises(ValidationError):
        models.ProviderReturnArtifactRecord(
            **artifact.model_dump(),
            transcript="must-not-be-stored",
        )


def test_review_decision_is_fixed_to_accept_or_reject_and_candidate_status_is_bounded() -> None:
    models = _load_review_models()
    now = datetime(2026, 8, 7, 15, 20, tzinfo=UTC)
    accepted = models.ProviderReviewDecisionRecord(
        decision_id="22222222-2222-2222-2222-222222222222",
        session_id="11111111-1111-1111-1111-111111111111",
        return_id="return-review",
        decision="accepted",
        change_set_digest="b" * 64,
        created_at=now,
    )
    assert accepted.decision == "accepted"

    with pytest.raises(ValidationError):
        models.ProviderReviewDecisionRecord(
            decision_id="33333333-3333-3333-3333-333333333333",
            session_id="11111111-1111-1111-1111-111111111111",
            return_id="return-review",
            decision="edit_and_accept",
            change_set_digest="b" * 64,
            created_at=now,
        )

    candidate = models.ProviderAdoptionCandidateRecord(
        candidate_id="44444444-4444-4444-4444-444444444444",
        session_id="11111111-1111-1111-1111-111111111111",
        return_id="return-review",
        status="queued",
        base_commit="a" * 40,
        change_set_digest="b" * 64,
        changed_file_count=1,
        validation_checks=[],
        created_at=now,
        updated_at=now,
    )
    assert candidate.status == models.ProviderAdoptionStatus.QUEUED

    with pytest.raises(ValidationError):
        models.ProviderAdoptionCandidateRecord(
            **candidate.model_dump(exclude={"status"}),
            status="merge_ready",
        )


def test_review_models_do_not_define_content_command_or_publish_fields() -> None:
    models = _load_review_models()
    field_names = set(models.ProviderReturnArtifactRecord.model_fields)
    field_names |= set(models.ProviderReviewDecisionRecord.model_fields)
    field_names |= set(models.ProviderAdoptionCandidateRecord.model_fields)

    assert not field_names.intersection(
        {
            "content",
            "payload",
            "diff",
            "patch",
            "command",
            "path_input",
            "model",
            "environment",
            "token",
            "api_key",
            "commit",
            "push",
            "pull_request",
            "merge",
            "release",
        }
    )
