from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from picotoopet_core.autonomous.evidence_ledger import (
    CanonicalEvidenceCreate,
    CanonicalEvidenceLedger,
    EvidenceOrigin,
    EvidenceTrust,
)
from picotoopet_core.autonomous.owner_structured_review import (
    OwnerStructuredFieldDecision,
    OwnerStructuredReviewCommitRequest,
    OwnerStructuredReviewError,
    OwnerStructuredReviewPreviewRequest,
    OwnerStructuredReviewService,
    ReviewDecision,
)
from picotoopet_core.creative.source import (
    CreativeSourceFinding,
    NormalizedCreativeSourceSet,
)
from picotoopet_core.creative.state_spine import AuthorityKind, StateFactsV1, canonical_sha256
from picotoopet_core.db.database import Database
from picotoopet_core.security.owner_principal import OwnerPrincipal

GOAL_ID = "goal-owner-review-synthetic"
JOB_ID = "creative-owner-review-synthetic"
SUBJECT = "pet:synthetic-mochi"
SOURCE_DIGEST = "1" * 64
OBJECTIVE = "Create a pet-only story with 3 shots of 4 seconds each, fixed pose and static camera."


def _database(tmp_path: Path) -> Database:
    database = Database(tmp_path / "core.sqlite3")
    database.open()
    database.apply_migrations()
    return database


def _principal(
    *, actor: str = "owner-local", subjects: tuple[str, ...] = (SUBJECT,)
) -> OwnerPrincipal:
    return OwnerPrincipal(
        actor_id=actor,
        credential_id=f"credential-{actor}",
        subject_keys=subjects,
        permissions=("owner_facts.review",),
        registry_revision=7,
    )


def _seed_goal(database: Database) -> str:
    now = datetime.now(UTC).isoformat()
    objective_digest = canonical_sha256({"objective": OBJECTIVE})
    with database.transaction() as connection:
        connection.execute(
            "INSERT INTO autonomous_goals("
            "goal_id,parent_goal_id,workflow_id,origin,intent_type,priority_class,objective,"
            "constraints_json,budget_class,pinned,score,status,idempotency_key,created_at,updated_at"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                GOAL_ID,
                None,
                None,
                "human",
                "video.creative",
                "P1",
                OBJECTIVE,
                json.dumps(
                    {"local_video_preferred": True, "owner_subject_key": SUBJECT},
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "local-first",
                0,
                None,
                "Ready",
                "synthetic-owner-review-goal",
                now,
                now,
            ),
        )
        connection.execute(
            "INSERT INTO creative_jobs("
            "creative_job_id,project_key,creative_profile,creative_objective,objective_digest,"
            "source_set_digest,status,current_stage,creative_package_id,deep_ai_handoff_id,"
            "failure_code,error_message,idempotency_key,created_at,updated_at,finished_at"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                JOB_ID,
                f"goal-{GOAL_ID}",
                "creative.content_plan.v2",
                OBJECTIVE,
                objective_digest,
                SOURCE_DIGEST,
                "Ready",
                None,
                None,
                None,
                None,
                None,
                "synthetic-owner-review-job",
                now,
                now,
                None,
            ),
        )
    return objective_digest


def _seed_legacy_owner_evidence(database: Database) -> str:
    record = CanonicalEvidenceLedger(database).ingest(
        CanonicalEvidenceCreate(
            subject_key=SUBJECT,
            evidence_type="pet.owner.visible_identity",
            source="owner_attestation",
            platform="private_mac_core",
            text_value="Synthetic owner says the pet has a white coat and amber eyes.",
            value={"claim_kind": "visible_identity"},
            trust_level=EvidenceTrust.D,
            confidence=0.8,
            captured_at=datetime.now(UTC),
            provenance={"owner_reviewed": True, "photo_bytes_verified": False},
            origin_kind=EvidenceOrigin.MANUAL,
            origin_ref="synthetic-legacy-owner-evidence",
        )
    )
    return record.evidence_id


def _seed_source_set(database: Database, evidence_id: str) -> None:
    source = NormalizedCreativeSourceSet(
        project_key=f"goal-{GOAL_ID}",
        result_package_ids=[],
        result_digests=[],
        findings=[
            CreativeSourceFinding(
                source_finding_ref="synthetic:finding:1",
                result_package_id="goal-synthesis",
                result_digest="2" * 64,
                work_package_id="goal-synthesis",
                finding_rank=1,
                finding_digest="3" * 64,
                finding={"rank": 1, "evidence_ids": [evidence_id]},
                evidence_ids=[evidence_id],
            )
        ],
        evidence_ids=[evidence_id],
        source_set_digest=SOURCE_DIGEST,
    )
    with database.transaction() as connection:
        connection.execute(
            "INSERT INTO creative_goal_source_sets("
            "creative_job_id,goal_id,discovery_result_hash,synthesis_result_hash,"
            "source_set_digest,source_set_json,created_at) VALUES (?,?,?,?,?,?,?)",
            (
                JOB_ID,
                GOAL_ID,
                "4" * 64,
                "5" * 64,
                SOURCE_DIGEST,
                source.model_dump_json(),
                datetime.now(UTC).isoformat(),
            ),
        )


@pytest.fixture
def review_database(tmp_path: Path) -> Database:
    database = _database(tmp_path)
    _seed_goal(database)
    evidence_id = _seed_legacy_owner_evidence(database)
    _seed_source_set(database, evidence_id)
    yield database
    database.close()


def _corrections() -> list[OwnerStructuredFieldDecision]:
    values: dict[str, object] = {
        "subject_lock.subject_id": "mochi",
        "subject_lock.species": "cat",
        "subject_lock.breed_or_type": "domestic short hair",
        "subject_lock.coat_or_appearance": "white short coat with amber eyes",
        "subject_lock.distinguishing_marks": ["amber eyes", "teal scarf"],
        "pose_lock.body_pose": "seated upright with all four paws supported",
        "pose_lock.head_direction": "head facing forward",
        "pose_lock.support_surface": "cream cushion on a low wooden bench",
        "scene_lock.environment": "quiet reading nook beside one window",
        "scene_lock.lighting": "soft daylight from camera left",
        "scene_lock.temporary_accessories": ["teal scarf"],
        "camera_lock.allowed_framings": ["locked medium shot", "locked close-up"],
        "allowed_events": ["BLINK_AND_REOPEN", "SUBTLE_BREATHING"],
    }
    return [
        OwnerStructuredFieldDecision(
            field_path=field_path,
            decision=ReviewDecision.CORRECT,
            corrected_value=value,
        )
        for field_path, value in values.items()
    ]


def _preview_request(service: OwnerStructuredReviewService, principal: OwnerPrincipal):
    proposal = service.proposal(GOAL_ID, principal)
    request = OwnerStructuredReviewPreviewRequest(
        goal_id=GOAL_ID,
        review_actor_id=principal.actor_id,
        proposal_digest=proposal.proposal_digest,
        decisions=_corrections(),
    )
    return request, service.preview(request, principal)


def test_proposal_is_deterministic_and_does_not_promote_legacy_free_text(
    review_database: Database,
) -> None:
    service = OwnerStructuredReviewService(review_database)
    first = service.proposal(GOAL_ID, _principal())
    second = service.proposal(GOAL_ID, _principal())

    assert first == second
    assert first.subject_key == SUBJECT
    assert first.source_set_digest == SOURCE_DIGEST
    assert first.fields["subject_lock.species"].status == "UNKNOWN"
    assert first.fields["subject_lock.coat_or_appearance"].value is None
    assert len(first.source_evidence) == 1
    assert first.source_evidence[0].trust_level == "D"
    assert first.source_evidence[0].photo_bytes_verified is False
    assert "white coat" not in first.model_dump_json()


def test_preview_builds_strict_state_facts_with_core_assigned_authority_and_no_write(
    review_database: Database,
) -> None:
    service = OwnerStructuredReviewService(review_database)
    principal = _principal()
    proposal = service.proposal(GOAL_ID, principal)
    before = review_database.scalar("SELECT COUNT(*) FROM canonical_evidence")

    preview = service.preview(
        OwnerStructuredReviewPreviewRequest(
            goal_id=GOAL_ID,
            review_actor_id=principal.actor_id,
            proposal_digest=proposal.proposal_digest,
            decisions=_corrections(),
        ),
        principal,
    )

    assert preview.outcome == "READY"
    assert preview.reason_codes == ()
    assert preview.state_facts is not None
    facts = StateFactsV1.model_validate(preview.state_facts.model_dump(mode="json"))
    assert facts.subject_key == SUBJECT
    assert facts.pose_lock.fixed is True
    assert facts.camera_lock.movement == "STATIC"
    assert {binding.authority_kind for binding in facts.subject_lock.evidence_bindings} == {
        AuthorityKind.OWNER_ATTESTATION
    }
    assert {binding.authority_kind for binding in facts.pose_lock.evidence_bindings} == {
        AuthorityKind.OWNER_CREATIVE_INTENT
    }
    assert review_database.scalar("SELECT COUNT(*) FROM canonical_evidence") == before


def test_preview_missing_or_unknown_field_needs_human_without_writes(
    review_database: Database,
) -> None:
    service = OwnerStructuredReviewService(review_database)
    principal = _principal()
    proposal = service.proposal(GOAL_ID, principal)
    decisions = _corrections()[:-1]
    decisions.append(
        OwnerStructuredFieldDecision(
            field_path="allowed_events",
            decision=ReviewDecision.UNKNOWN,
        )
    )
    before = review_database.scalar("SELECT COUNT(*) FROM canonical_evidence")

    preview = service.preview(
        OwnerStructuredReviewPreviewRequest(
            goal_id=GOAL_ID,
            review_actor_id=principal.actor_id,
            proposal_digest=proposal.proposal_digest,
            decisions=decisions,
        ),
        principal,
    )

    assert preview.outcome == "NEEDS_HUMAN"
    assert preview.state_facts is None
    assert preview.reason_codes == ("OWNER_REVIEW_FIELD_UNKNOWN:allowed_events",)
    assert review_database.scalar("SELECT COUNT(*) FROM canonical_evidence") == before


def test_preview_rejects_actor_mismatch_and_duplicate_or_poisoned_fields(
    review_database: Database,
) -> None:
    service = OwnerStructuredReviewService(review_database)
    principal = _principal()
    proposal = service.proposal(GOAL_ID, principal)
    request = OwnerStructuredReviewPreviewRequest(
        goal_id=GOAL_ID,
        review_actor_id="owner-other",
        proposal_digest=proposal.proposal_digest,
        decisions=_corrections(),
    )

    with pytest.raises(OwnerStructuredReviewError) as mismatch:
        service.preview(request, principal)
    assert mismatch.value.status_code == 403
    assert mismatch.value.code == "OWNER_REVIEW_ACTOR_MISMATCH"

    duplicate = _corrections()
    duplicate.append(duplicate[0])
    with pytest.raises(ValidationError, match="OWNER_REVIEW_DECISION_FIELDS_DUPLICATE"):
        OwnerStructuredReviewPreviewRequest(
            goal_id=GOAL_ID,
            review_actor_id=principal.actor_id,
            proposal_digest=proposal.proposal_digest,
            decisions=duplicate,
        )
    with pytest.raises(ValidationError):
        OwnerStructuredFieldDecision(
            field_path="subject_lock.__dict__",
            decision=ReviewDecision.CORRECT,
            corrected_value="poison",
        )


def test_static_story_opt_in_is_explicit_digest_bound_and_replay_safe(
    review_database: Database,
) -> None:
    """Policy acceptance requires an owner's explicit typed choice in this review."""

    service = OwnerStructuredReviewService(review_database)
    principal = _principal()
    base_request, legacy_preview = _preview_request(service, principal)
    selected_request = base_request.model_copy(
        update={"story_policy_opt_in": "static-pet-story-v1.0.0"}
    )
    selected_preview = service.preview(selected_request, principal)

    # Consent is independent : permitted blink/breathing does not auto-select policy.
    assert legacy_preview.story_policy_opt_in is None
    assert selected_preview.outcome == "READY"
    assert selected_preview.story_policy_opt_in == "static-pet-story-v1.0.0"
    assert selected_preview.review_digest != legacy_preview.review_digest
    assert selected_preview.preview_digest != legacy_preview.preview_digest

    committed_request = OwnerStructuredReviewCommitRequest(
        preview_request=selected_request,
        source_revision_digest=selected_preview.source_revision_digest,
        review_digest=selected_preview.review_digest,
        preview_digest=selected_preview.preview_digest,
    )
    committed = service.commit(
        committed_request, principal, idempotency_key="synthetic-static-policy-opt-in"
    )
    assert committed.story_policy_opt_in == "static-pet-story-v1.0.0"
    assert (
        service.commit(
            committed_request, principal, idempotency_key="synthetic-static-policy-opt-in"
        )
        == committed
    )

    # A caller cannot replay the same approval with a policy choice silently changed.
    tampered = committed_request.model_copy(
        update={"preview_request": base_request}
    )
    with pytest.raises(OwnerStructuredReviewError) as denied:
        service.commit(tampered, principal, idempotency_key="synthetic-static-policy-opt-in")
    assert denied.value.status_code == 409
    assert denied.value.code == "OWNER_REVIEW_IDEMPOTENCY_CONFLICT"


def test_static_story_opt_in_rejects_missing_temporal_or_framing_support(
    review_database: Database,
) -> None:
    """Policy opt-in is not ready without both source-authorized events and framings."""

    service = OwnerStructuredReviewService(review_database)
    principal = _principal()
    base_request, _ = _preview_request(service, principal)
    for field, rejected in (
        ("allowed_events", ["SUBTLE_BREATHING"]),
        ("camera_lock.allowed_framings", ["locked medium shot"]),
    ):
        revised = [
            item.model_copy(update={"corrected_value": rejected})
            if item.field_path == field else item
            for item in base_request.decisions
        ]
        selected = base_request.model_copy(
            update={
                "story_policy_opt_in": "static-pet-story-v1.0.0",
                "decisions": revised,
            }
        )
        result = service.preview(selected, principal)
        assert result.outcome == "NEEDS_HUMAN"
        assert "OWNER_REVIEW_STATIC_POLICY_PREREQUISITES_INVALID" in result.reason_codes
        assert result.state_facts is None

def test_commit_is_atomic_source_bound_and_exactly_replay_safe(
    review_database: Database,
) -> None:
    service = OwnerStructuredReviewService(review_database)
    principal = _principal()
    preview_request, preview = _preview_request(service, principal)
    legacy = review_database.fetchone(
        "SELECT evidence_id,raw_hash,value_json,provenance_json FROM canonical_evidence"
    )
    before = review_database.scalar("SELECT COUNT(*) FROM canonical_evidence")
    request = OwnerStructuredReviewCommitRequest(
        preview_request=preview_request,
        source_revision_digest=preview.source_revision_digest,
        review_digest=preview.review_digest,
        preview_digest=preview.preview_digest,
    )

    first = service.commit(request, principal, idempotency_key="synthetic-commit-one")
    after_first = review_database.scalar("SELECT COUNT(*) FROM canonical_evidence")
    second = service.commit(request, principal, idempotency_key="synthetic-commit-one")

    assert first == second
    assert first.facts_digest == preview.state_facts.facts_digest
    assert first.preview_digest == preview.preview_digest
    assert after_first > before
    assert review_database.scalar("SELECT COUNT(*) FROM canonical_evidence") == after_first
    assert (
        review_database.fetchone(
            "SELECT evidence_id,raw_hash,value_json,provenance_json FROM canonical_evidence "
            "WHERE evidence_id=?",
            (legacy["evidence_id"],),
        )
        == legacy
    )

    facts = preview.state_facts
    bindings = (
        facts.subject_lock.evidence_bindings
        + facts.pose_lock.evidence_bindings
        + facts.scene_lock.evidence_bindings
        + facts.camera_lock.evidence_bindings
    )
    assert all(
        review_database.fetchone(
            "SELECT evidence_id FROM canonical_evidence WHERE evidence_id=?",
            (binding.evidence_id,),
        )
        is not None
        for binding in bindings
    )


def test_exact_replay_rechecks_current_subject_scope_and_credential(
    review_database: Database,
) -> None:
    """An old idempotency key must not outlive the current subject or credential grant."""

    service = OwnerStructuredReviewService(review_database)
    principal = _principal()
    preview_request, preview = _preview_request(service, principal)
    request = OwnerStructuredReviewCommitRequest(
        preview_request=preview_request,
        source_revision_digest=preview.source_revision_digest,
        review_digest=preview.review_digest,
        preview_digest=preview.preview_digest,
    )
    key = "synthetic-replay-current-authority"
    first = service.commit(request, principal, idempotency_key=key)
    assert service.commit(request, principal, idempotency_key=key) == first

    # Revoked subject scope : same valid actor and exact payload must get 403, not old data.
    revoked = principal.model_copy(update={"subject_keys": ("pet:another-pet",)})
    with pytest.raises(OwnerStructuredReviewError) as denied:
        service.commit(request, revoked, idempotency_key=key)
    assert denied.value.status_code == 403

    # Rotated credential    : a different valid credential for the same actor is not
    #                         the same approval identity or idempotent replay.
    rotated = principal.model_copy(update={"credential_id": "credential-rotated"})
    with pytest.raises(OwnerStructuredReviewError) as mismatch:
        service.commit(request, rotated, idempotency_key=key)
    assert mismatch.value.status_code == 409
    assert mismatch.value.code == "OWNER_REVIEW_IDEMPOTENCY_CONFLICT"


def test_preview_digest_is_bound_to_credential_identity(
    review_database: Database,
) -> None:
    """A second credential sharing an actor must obtain a new preview for its own decision."""

    service = OwnerStructuredReviewService(review_database)
    principal = _principal()
    preview_request, original = _preview_request(service, principal)
    same_actor_other_credential = principal.model_copy(
        update={"credential_id": "credential-rotated"}
    )
    rotated = service.preview(preview_request, same_actor_other_credential)
    assert rotated.proposal_digest == original.proposal_digest
    assert rotated.review_digest != original.review_digest
    assert rotated.preview_digest != original.preview_digest


def test_commit_rejects_idempotency_mutation_and_stale_source(
    review_database: Database,
) -> None:
    service = OwnerStructuredReviewService(review_database)
    principal = _principal()
    preview_request, preview = _preview_request(service, principal)
    request = OwnerStructuredReviewCommitRequest(
        preview_request=preview_request,
        source_revision_digest=preview.source_revision_digest,
        review_digest=preview.review_digest,
        preview_digest=preview.preview_digest,
    )
    service.commit(request, principal, idempotency_key="synthetic-replay-conflict")
    mutated = request.model_copy(update={"preview_digest": "f" * 64})

    with pytest.raises(OwnerStructuredReviewError) as replay:
        service.commit(mutated, principal, idempotency_key="synthetic-replay-conflict")
    assert replay.value.status_code == 409
    assert replay.value.code == "OWNER_REVIEW_IDEMPOTENCY_CONFLICT"

    # Create a fresh preview, then change the subject's evidence revision before commit.
    fresh_request, fresh_preview = _preview_request(service, principal)
    stale_commit = OwnerStructuredReviewCommitRequest(
        preview_request=fresh_request,
        source_revision_digest=fresh_preview.source_revision_digest,
        review_digest=fresh_preview.review_digest,
        preview_digest=fresh_preview.preview_digest,
    )
    CanonicalEvidenceLedger(review_database).ingest(
        CanonicalEvidenceCreate(
            subject_key=SUBJECT,
            evidence_type="pet.owner.visible_scene",
            source="owner_attestation",
            platform="private_mac_core",
            text_value="A new synthetic owner statement changes the source revision.",
            value={"claim_kind": "visible_scene"},
            trust_level=EvidenceTrust.D,
            confidence=0.8,
            captured_at=datetime.now(UTC),
            provenance={"owner_reviewed": True, "photo_bytes_verified": False},
            origin_kind=EvidenceOrigin.MANUAL,
            origin_ref="synthetic-source-revision-change",
        )
    )
    before = review_database.scalar("SELECT COUNT(*) FROM canonical_evidence")

    with pytest.raises(OwnerStructuredReviewError) as stale:
        service.commit(stale_commit, principal, idempotency_key="synthetic-stale")
    assert stale.value.status_code == 409
    assert stale.value.code == "OWNER_REVIEW_SOURCE_STALE"
    assert review_database.scalar("SELECT COUNT(*) FROM canonical_evidence") == before


def test_proposal_rejects_typed_evidence_without_an_actual_committed_review(
    review_database: Database,
) -> None:
    rogue_review = "a" * 64
    CanonicalEvidenceLedger(review_database).ingest(
        CanonicalEvidenceCreate(
            goal_id=GOAL_ID,
            subject_key=SUBJECT,
            evidence_type="pet.owner.state_field.v1",
            source="owner_structured_review",
            platform="private_mac_core",
            value={
                "actor_id": "owner-local",
                "authority_kind": "OWNER_ATTESTATION",
                "field_path": "subject_lock.species",
                "field_value": "cat",
                "review_digest": rogue_review,
            },
            trust_level=EvidenceTrust.D,
            confidence=1.0,
            captured_at=datetime.now(UTC),
            provenance={
                "actor_id": "owner-local",
                "owner_reviewed": True,
                "review_digest": rogue_review,
                "photo_bytes_verified": False,
            },
            origin_kind=EvidenceOrigin.MANUAL,
            origin_ref="rogue-uncommitted-typed-field",
        )
    )

    proposal = OwnerStructuredReviewService(review_database).proposal(GOAL_ID, _principal())

    assert proposal.fields["subject_lock.species"].status == "UNKNOWN"


def test_commit_maps_late_origin_conflict_to_409_and_rolls_back(
    review_database: Database,
) -> None:
    service = OwnerStructuredReviewService(review_database)
    principal = _principal()
    preview_request, preview = _preview_request(service, principal)
    conflicting_path = "camera_lock.allowed_framings"
    CanonicalEvidenceLedger(review_database).ingest(
        CanonicalEvidenceCreate(
            goal_id="unrelated-goal",
            subject_key="pet:unrelated-subject",
            evidence_type="synthetic.conflict",
            source="owner_structured_review",
            platform="private_mac_core",
            text_value="Occupy the later origin with different synthetic content.",
            trust_level=EvidenceTrust.E,
            confidence=1.0,
            captured_at=datetime.now(UTC),
            provenance={"synthetic_conflict": True},
            origin_kind=EvidenceOrigin.MANUAL,
            origin_ref=(
                f"owner-structured-review:{preview.review_digest}:field:{conflicting_path}"
            ),
        )
    )
    before = review_database.scalar("SELECT COUNT(*) FROM canonical_evidence")
    request = OwnerStructuredReviewCommitRequest(
        preview_request=preview_request,
        source_revision_digest=preview.source_revision_digest,
        review_digest=preview.review_digest,
        preview_digest=preview.preview_digest,
    )

    with pytest.raises(OwnerStructuredReviewError) as conflict:
        service.commit(request, principal, idempotency_key="synthetic-late-conflict")

    assert conflict.value.status_code == 409
    assert conflict.value.code == "OWNER_REVIEW_EVIDENCE_CONFLICT"
    assert review_database.scalar("SELECT COUNT(*) FROM canonical_evidence") == before
    assert review_database.scalar(
        "SELECT COUNT(*) FROM canonical_evidence WHERE subject_key=?",
        (SUBJECT,),
    ) == 1
