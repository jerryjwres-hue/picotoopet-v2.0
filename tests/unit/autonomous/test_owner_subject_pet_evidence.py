"""Owner pet evidence must stay scoped, attestable, and separate from product claims."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from picotoopet_core.autonomous.discovery import (
    ContentDiscoveryCoordinator,
    ContentDiscoveryError,
    ContentDiscoveryRequest,
)
from picotoopet_core.autonomous.evidence_ledger import CanonicalEvidenceLedger
from picotoopet_core.autonomous.goal_service import HumanGoalRequest
from picotoopet_core.autonomous.human_pipeline import HumanGoalWorkflowPlanner
from picotoopet_core.autonomous.local_creative import GoalLocalCreativeCoordinator
from picotoopet_core.autonomous.local_intelligence import LocalAnalysisResult
from picotoopet_core.autonomous.models import (
    GoalOrigin,
    GoalRecord,
    GoalStatus,
    PriorityClass,
)
from picotoopet_core.autonomous.owner_subject_evidence import (
    OwnerSubjectEvidenceIntake,
    OwnerSubjectEvidencePacket,
    OwnerSubjectReview,
)
from picotoopet_core.db.database import Database
from picotoopet_core.domain.enums import TaskStatus
from picotoopet_core.domain.models import TaskRecord
from picotoopet_core.research.models import ResearchSearchResult


OBJECTIVE = (
    "pet-only story featuring one family dog. exactly 3 shots. "
    "Each shot 4 seconds. quality-first story."
)


def _packet(key: str = "pet:maotai") -> OwnerSubjectEvidencePacket:
    """Synthetic facts only; no real user animal image or personal data is uploaded."""
    return OwnerSubjectEvidencePacket(
        subject_key=key,
        photo_sha256_claim="a" * 64,
        claims=[
            {"kind": "visible_identity", "statement": "Owner says the dog has dark fur and cream eyebrows."},
            {"kind": "visible_scene", "statement": "Owner says the first photograph shows the dog resting on the floor."},
            {"kind": "creative_intent", "statement": "Owner proposes a gentle blink followed by a natural breath."},
        ],
    )


def _database(tmp_path: Path) -> Database:
    db = Database(tmp_path / "runtime" / "database" / "core.db")
    db.open()
    db.apply_migrations()
    return db


def _task(task_type: str, payload: dict[str, object]) -> TaskRecord:
    now = datetime.now(UTC)
    return TaskRecord(
        task_id="owner-subject-local-test",
        task_type=task_type,
        status=TaskStatus.RUNNING,
        priority=100,
        resource_tag="workflow:synthetic-owner",
        payload=payload,
        attempt_count=1,
        max_attempts=2,
        timeout_seconds=420,
        created_at=now,
        updated_at=now,
    )


class FakeSearch:
    def search(self, *, query: str, limit: int, timeout_seconds: int) -> ResearchSearchResult:
        return ResearchSearchResult(query=query, limit=limit, output="Synthetic public search text.")


class FakeLocal:
    def __init__(self) -> None:
        self.requests = []

    def analyze(self, request):
        self.requests.append(request)
        return LocalAnalysisResult(
            role=request.role,
            summary="Synthetic owner-scoped pet story.",
            confidence=0.75,
            findings=["Owner has approved a bounded appearance and setting description."],
            recommended_actions=["Prepare a supported shot plan."],
            evidence_ids=request.evidence_ids,
        )


def test_owner_preview_exact_digest_confirmation_and_immutable_replay(tmp_path: Path) -> None:
    db = _database(tmp_path)
    try:
        packet = _packet()
        intake = OwnerSubjectEvidenceIntake(CanonicalEvidenceLedger(db))
        preview = intake.preview(packet)
        assert preview["photo_bytes_verified"] is False
        assert preview["owner_confirmation_required"] is True
        assert db.scalar("SELECT COUNT(*) FROM canonical_evidence") == 0

        with pytest.raises(ValueError, match="DIGEST_MISMATCH"):
            intake.ingest(OwnerSubjectReview(
                packet=packet, reviewed_digest="f" * 64, owner_confirmed=True,
            ))
        assert db.scalar("SELECT COUNT(*) FROM canonical_evidence") == 0

        reviewed = OwnerSubjectReview(
            packet=packet, reviewed_digest=packet.digest(), owner_confirmed=True,
        )
        records = intake.ingest(reviewed)
        assert len(records) == 3
        assert [r.evidence_id for r in intake.ingest(reviewed)] == [
            r.evidence_id for r in records
        ]
        assert db.scalar("SELECT COUNT(*) FROM canonical_evidence") == 3
        assert all(r.subject_key == "pet:maotai" for r in records)
        assert all(r.provenance["photo_bytes_verified"] is False for r in records)
        assert {r.value["claim_kind"] for r in records} == {
            "visible_identity", "visible_scene", "creative_intent",
        }
        assert records[2].trust_level.value == "E"
    finally:
        db.close()


def test_owner_claims_and_goal_scope_fail_closed() -> None:
    with pytest.raises(ValidationError):
        OwnerSubjectEvidencePacket(
            subject_key="pet:maotai",
            photo_sha256_claim="a" * 64,
            claims=_packet().claims[:2],
        )
    with pytest.raises(ValidationError):
        OwnerSubjectReview(
            packet=_packet(), reviewed_digest=_packet().digest(), owner_confirmed=False,
        )
    with pytest.raises(ValidationError):
        _packet("product:maotai")
    with pytest.raises(ValidationError):
        HumanGoalRequest(
            goal_type="product.research_to_video",
            objective=OBJECTIVE,
            owner_subject_key="pet:maotai",
        )
    with pytest.raises(ValidationError):
        HumanGoalRequest(
            goal_type="video.creative",
            objective="A commercial video for a dog collar.",
            owner_subject_key="pet:maotai",
        )
    with pytest.raises(ValidationError):
        ContentDiscoveryRequest(
            objective="Do not make a pet-only story.",
            owner_subject_key="pet:maotai",
        )
    with pytest.raises(ValidationError):
        ContentDiscoveryRequest(
            objective=OBJECTIVE,
            owner_subject_key="pet:maotai",
            connected_product_keys=("product-id",),
        )


def test_owner_subject_evidence_reaches_discovery_without_product_spoofing(
    tmp_path: Path,
) -> None:
    db = _database(tmp_path)
    try:
        ledger = CanonicalEvidenceLedger(db)
        intake = OwnerSubjectEvidenceIntake(ledger)
        packet = _packet()
        local = FakeLocal()
        coordinator = ContentDiscoveryCoordinator(
            search=FakeSearch(),
            local=local,
            owner_evidence=ledger,
        )
        task = _task("autonomous.discovery.v1", {
            "objective": OBJECTIVE, "read_only": True,
            "max_candidates": 10, "owner_subject_key": "pet:maotai",
        })
        with pytest.raises(ContentDiscoveryError, match="OWNER_SUBJECT_GROUNDING_MISSING"):
            coordinator.handler(task)
        assert not local.requests

        intake.ingest(OwnerSubjectReview(
            packet=packet, reviewed_digest=packet.digest(), owner_confirmed=True,
        ))
        result = coordinator.handler(task)
        document = result.result_document
        assert document is not None
        owner = document["connected_evidence"]
        assert len(owner) == 3
        assert all(x["subject_key"] == "pet:maotai" for x in owner)
        assert all("product_key" not in x for x in owner)
        assert all(x["photo_bytes_verified"] is False for x in owner)
        assert {x["evidence_id"] for x in owner} <= set(document["evidence_ids"])
        assert "Owner subject: pet:maotai" in local.requests[-1].text
    finally:
        db.close()


def test_explicit_owner_subject_scope_is_in_frozen_discovery_plan() -> None:
    now = datetime.now(UTC)
    goal = GoalRecord(
        goal_id="goal-owner-1",
        origin=GoalOrigin.HUMAN,
        intent_type="video.creative",
        priority_class=PriorityClass.P1,
        objective=OBJECTIVE,
        constraints={
            "depth": "quick", "read_only_research": True,
            "local_video_preferred": True, "owner_subject_key": "pet:maotai",
        },
        budget_class="local-first",
        pinned=False,
        status=GoalStatus.READY,
        idempotency_key="owner-pet-test",
        created_at=now,
        updated_at=now,
    )
    workflow = HumanGoalWorkflowPlanner().plan(goal)
    assert workflow.steps[0].payload["owner_subject_key"] == "pet:maotai"

    old = goal.model_copy(update={"constraints": {
        "depth": "quick", "read_only_research": True,
        "local_video_preferred": True,
    }})
    assert "owner_subject_key" not in HumanGoalWorkflowPlanner().plan(old).steps[0].payload


def test_creative_preserves_owner_statement_vs_proposed_motion() -> None:
    """Original synthesis findings stay unverified; owner claims carry exact evidence IDs."""
    packet = _packet()
    expected = ["owner-identity", "owner-scene", "owner-motion"]
    kinds = ["visible_identity", "visible_scene", "creative_intent"]
    discovery = {
        "connected_evidence": [
            {
                "evidence_id": evidence_id,
                "subject_key": "pet:maotai",
                "source": "owner_attestation",
                "origin": "manual",
                "evidence_type": f"pet.owner.{kind}",
                "trust_level": "E" if kind == "creative_intent" else "D",
                "photo_bytes_verified": False,
                "reviewed_packet_sha256": packet.digest(),
                "text_excerpt": claim.statement,
                "numeric_value": None,
            }
            for evidence_id, kind, claim in zip(expected, kinds, packet.claims, strict=True)
        ],
        "search_evidence": [],
    }
    synthesis = {
        "goal_id": "goal-owner-1",
        "evidence_ids": [expected[0]],
        "findings": ["An unverified analysis inference unrelated to owner testimony."],
    }
    goal = SimpleNamespace(
        goal_id="goal-owner-1",
        intent_type="video.creative",
        constraints={"owner_subject_key": "pet:maotai", "local_video_preferred": True},
        objective=OBJECTIVE,
    )
    captured = {}
    service = SimpleNamespace(
        repository=SimpleNamespace(
            database=SimpleNamespace(fetchone=lambda *_args: None)
        ),
        create_goal_job=lambda **kw: (
            captured.update(kw) or SimpleNamespace(creative_job_id="created-1")
        ),
    )
    coordinator = GoalLocalCreativeCoordinator.__new__(GoalLocalCreativeCoordinator)
    coordinator.creative = service
    coordinator.goal = lambda goal_id: goal
    coordinator.step_result = lambda *a, **kw: (
        discovery if kw["label"] == "discovery" else synthesis
    )
    coordinator._hash_for_step = lambda *a, **kw: (
        "d" * 64 if a[1] == "research-evidence" else "e" * 64
    )
    result = coordinator.handler(_task("autonomous.goal_creative.v1", {
        "goal_id": "goal-owner-1",
    }))
    assert result.summary["creative_job_id"] == "created-1"
    items = [x.finding for x in captured["source_set"].findings]
    assert items[0]["claim_status"] == "unverified_inference"
    assert {x["claim_status"] for x in items[1:]} == {
        "owner_attested", "creative_intent",
    }
    assert all(x["photo_bytes_verified"] is False for x in items[1:])
    assert set(expected) == set(captured["source_set"].evidence_ids)


def test_authenticated_owner_review_intake_is_separate_from_goal_and_gpu(
    tmp_path: Path,
) -> None:
    """The API previews first; even a reviewed commit creates no Goal or approval."""
    from fastapi.testclient import TestClient
    from picotoopet_core.api.app import create_app
    from picotoopet_core.config.models import AppSettings
    from picotoopet_core.config.paths import RuntimePaths

    token = "0123456789abcdef0123456789abcdef"
    app = create_app(AppSettings(
        paths=RuntimePaths.from_root(tmp_path / "api-runtime"), api_token=token,
    ))
    client = TestClient(app)
    packet = _packet().model_dump(mode="json")
    route = "/api/v1/autonomous/owner-subject-evidence"
    assert client.post(route + "/preview", json=packet).status_code == 401

    authorized = {"Authorization": f"Bearer {token}"}
    preview = client.post(route + "/preview", json=packet, headers=authorized)
    assert preview.status_code == 200
    digest = preview.json()["packet_digest"]
    assert preview.json()["photo_bytes_verified"] is False

    denied = client.post(route + "/commit", headers=authorized, json={
        "packet": packet, "reviewed_digest": "f" * 64, "owner_confirmed": True,
    })
    assert denied.status_code == 409
    accepted = client.post(route + "/commit", headers=authorized, json={
        "packet": packet, "reviewed_digest": digest, "owner_confirmed": True,
    })
    assert accepted.status_code == 201
    assert accepted.json()["goal_created"] is False
    assert accepted.json()["production_approval_granted"] is False
    assert len(accepted.json()["evidence_ids"]) == 3

    replay = client.post(route + "/commit", headers=authorized, json={
        "packet": packet, "reviewed_digest": digest, "owner_confirmed": True,
    })
    assert replay.status_code == 201
    assert replay.json()["evidence_ids"] == accepted.json()["evidence_ids"]
