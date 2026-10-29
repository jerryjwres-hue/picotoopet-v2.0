"""Native Core API and SQLite durability tests; all images/approvals synthetic."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from picotoopet_core.api.routes import reference_registration
from picotoopet_core.api.errors import install_error_handlers
from picotoopet_core.approvals.service import ApprovalError
from picotoopet_core.config.paths import RuntimePaths
from picotoopet_core.creative.store import CreativeArtifactStore
from picotoopet_core.db.database import Database
from picotoopet_core.handoffs.approvals import HandoffApprovalService
from picotoopet_core.production.reference_assets import (
    ReferenceAssetIdentityV1, approved_reference_descriptor
)
from picotoopet_core.production.reference_registration import (
    ReferenceRegistrationService, ReferenceBatchRequestV1
)
from picotoopet_core.security.auth import require_auth

SHA = "a" * 64
SOURCE = "b" * 64
GOAL = str(uuid4())
JOB = str(uuid4())
PACKAGE = str(uuid4())


@pytest.fixture()
def state(tmp_path):
    paths = RuntimePaths.from_root(tmp_path)
    store = CreativeArtifactStore(paths)
    database = Database(paths.database_file)
    database.open()
    database.apply_migrations()
    now = datetime.now(UTC).isoformat()
    manifest = {
        "schema_version": "1.0",
        "creative_package_id": PACKAGE,
        "creative_job_id": JOB,
        "source_set_digest": SOURCE,
        "project_key": f"goal-{GOAL}",
        "quality_outcome": "PASS",
        "stage_results": {
            "creative_brief.v1": {
                "schema_version": "1.0", "creative_profile": "creative.content_plan.v1",
                "selected_idea_id": "idea-001", "target_audience": "pet owners",
                "customer_problem": "drying", "value_proposition": "safer grooming",
                "primary_hook": "Dry faster", "emotional_tone": "warm",
                "content_format": "video", "duration_min_seconds": 3,
                "duration_max_seconds": 20, "message_hierarchy": ["problem", "solution"],
                "required_source_finding_refs": ["result:finding:1"],
                "required_source_evidence_ids": ["reviews:key:r1"], "prohibited_claims": [],
                "cta_intent": "learn more", "continuity_notes": ["same pet throughout"],
                "needs_deep_ai": False, "needs_human": False,
            },
            "script.v1": {
                "schema_version": "1.0", "creative_profile": "creative.content_plan.v1",
                "script_id": "script-001", "title": "A short pet story",
                "target_duration_seconds": 9,
                "beats": [
                    {"beat_id": f"beat-{i:03d}", "order": i, "duration_seconds": 3,
                     "voiceover": "Gentle pet grooming.", "on_screen_text": None,
                     "visual_intent": "pet continuity",
                     "claim_source_evidence_ids": ["reviews:key:r1"],
                     "unsupported_claim": False}
                    for i in range(1, 4)
                ],
                "cta_beat_id": "beat-003", "warnings": [],
                "needs_deep_ai": False, "needs_human": False,
            },
            "shot_plan.v1": {
                "schema_version": "1.0", "creative_profile": "creative.content_plan.v1",
                "shots": [
                    {"shot_id": shot, "beat_id": f"beat-{order:03d}",
                     "order": order, "duration_seconds": 3,
                     "subject": "the same dog", "environment": "grooming room",
                     "action": "gentle motion", "framing": "medium shot",
                     "lighting_style": "soft daylight", "continuity_keys": ["same dog"],
                     "required_facts": ["grooming"], "source_evidence_ids": ["reviews:key:r1"],
                     "text_reference": None, "production_notes": "renderer neutral",
                     "render_intent": "IMAGE_TO_VIDEO" if order < 3 else "GENERATIVE_VIDEO"}
                    for order, shot in enumerate(["shot-a", "shot-b", "shot-t"], start=1)
                ],
                "warnings": [], "needs_deep_ai": False, "needs_human": False,
            },
        },
    }
    location, digest = store.write_creative_package(PACKAGE, manifest)
    database.execute(
        "INSERT INTO autonomous_goals(goal_id,origin,intent_type,priority_class,objective,"
        "constraints_json,budget_class,status,idempotency_key,created_at,updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (GOAL, "user", "video.creative", "normal", "synthetic goal", "{}", "local",
         "Ready", "goal-case", now, now),
    )
    database.execute(
        "INSERT INTO creative_jobs(creative_job_id,project_key,creative_profile,"
        "objective_digest,source_set_digest,status,idempotency_key,created_at,updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (JOB, f"goal-{GOAL}", "creative.content_plan.v1", SHA, SOURCE,
         "creative_ready", "creative-case", now, now),
    )
    database.execute(
        "INSERT INTO creative_goal_source_sets(creative_job_id,goal_id,discovery_result_hash,"
        "synthesis_result_hash,source_set_digest,source_set_json,created_at)"
        "VALUES (?,?,?,?,?,?,?)", (JOB, GOAL, SHA, SHA, SOURCE, "{}", now),
    )
    database.execute(
        "INSERT INTO creative_packages(creative_package_id,creative_job_id,source_set_digest,"
        "package_digest,package_relpath,manifest_json,quality_outcome,created_at)"
        "VALUES (?,?,?,?,?,?,?,?)",
        (PACKAGE, JOB, SOURCE, digest, location, json.dumps(manifest), "PASS", now),
    )
    approval = HandoffApprovalService(database, None)
    service = ReferenceRegistrationService(database, approval, store)
    try:
        yield database, service, approval, store, digest
    finally:
        database.close()


def candidate(shot: str) -> dict:
    return {
        "shot_id": shot,
        "input_relative_path": f"PicotooPet/references/{SHA}/{shot}.png",
        "sha256": SHA, "bytes": 12,
        "source_reference": "USER_SUPPLIED",
        "source_digest": SOURCE,
        "rights_scope": "wan22.i2v.production.v1",
    }


def payload(digest: str) -> dict:
    return {
        "schema_version": "reference_batch.v1",
        "goal_id": GOAL,
        "creative_package_id": PACKAGE,
        "creative_package_digest": digest,
        "selected_references": [candidate("shot-a"), candidate("shot-b")],
        "user_confirms_preview_and_rights": True,
    }


def identity(batch, shot: str) -> ReferenceAssetIdentityV1:
    ref = next(x for x in batch.references if x.shot_id == shot)
    return ReferenceAssetIdentityV1(
        schema_version="reference_asset.v1", asset_id=ref.asset_id,
        goal_id=GOAL, creative_job_id=JOB, creative_package_id=PACKAGE,
        production_job_id=str(uuid4()), production_task_id=str(uuid4()),
        shot_id=shot, creative_package_digest=batch.creative_package_digest,
        input_relative_path=ref.input_relative_path, sha256=ref.sha256,
        bytes=ref.bytes, source_reference=ref.source_reference,
        source_digest=ref.source_digest, rights_scope="wan22.i2v.production.v1",
        approval_id=batch.approval_id, approval_request_digest=batch.approval_request_digest
    )


def test_batch_one_pending_approval_exact_two_shots_and_durable_restart(state):
    db, service, approval, store, digest = state
    request = ReferenceBatchRequestV1.model_validate(payload(digest))
    first = service.register(request, idempotency_key="batch-retry-key")
    second = ReferenceRegistrationService(db, approval, store).register(
        request, idempotency_key="batch-retry-key")
    assert first == second
    assert first.status == "Pending"
    assert len(first.references) == 2
    assert first.references[0].asset_id != first.references[1].asset_id
    assert first.references[0].asset_id not in (first.approval_id,)
    assert len(db.fetchall(
        "SELECT * FROM approvals WHERE approval_type='production.reference_asset.v1'", ()
    )) == 1
    assert "shot-a" in approval.get(first.approval_id).scope_summary
    # Fully close and reopen SQLite to prove the approval batch and AssetIds are durable.
    db.close()
    db.open()
    assert ReferenceRegistrationService(db, approval, store).get(first.approval_id) == first
    with pytest.raises(ValueError, match="REFERENCE_ASSET_APPROVAL_NOT_VERIFIED"):
        approved_reference_descriptor(db, identity(first, "shot-a"))

    approval.decide_for_control_center(
        approval_id=first.approval_id, decision="approve",
        request_digest=first.approval_request_digest,
        idempotency_key="explicit-real-decision-test-only",
        resolved_by="synthetic-fixture", reason="synthetic test consent",
    )
    restored = ReferenceRegistrationService(db, approval, store).get(first.approval_id)
    assert restored.status == "Approved"
    a = identity(restored, "shot-a")
    assert approved_reference_descriptor(db, a).asset_id == a.asset_id
    assert approved_reference_descriptor(db, identity(restored, "shot-b")).shot_id == "shot-b"
    with pytest.raises(ValueError, match="REFERENCE_ASSET_APPROVAL_SCOPE_MISMATCH"):
        approved_reference_descriptor(db, a.model_copy(update={"shot_id": "shot-b"}))
    with pytest.raises(ValueError, match="REFERENCE_ASSET_APPROVAL_SCOPE_MISMATCH"):
        approved_reference_descriptor(db, a.model_copy(update={"asset_id": str(uuid4())}))

    revoked = service.revoke(
        first.approval_id, request_digest=first.approval_request_digest,
        reason="explicit owner revoke",
    )
    assert revoked.status == "Revoked"
    assert service.revoke(first.approval_id, request_digest=first.approval_request_digest,
                          reason="repeat").status == "Revoked"
    with pytest.raises(ValueError, match="REFERENCE_ASSET_APPROVAL_NOT_VERIFIED"):
        approved_reference_descriptor(db, a)
    with pytest.raises(ApprovalError):
        approval.decide_for_control_center(
            approval_id=first.approval_id, decision="approve",
            request_digest=first.approval_request_digest, idempotency_key="replay",
            resolved_by="synthetic-fixture", reason="replay",
        )


def test_idempotency_conflict_invalid_shots_and_transaction_rollback(state):
    db, service, approval, store, digest = state
    base = payload(digest)
    service.register(ReferenceBatchRequestV1.model_validate(base), idempotency_key="same-key")
    changed = payload(digest)
    changed["selected_references"][1]["sha256"] = "c" * 64
    with pytest.raises(ApprovalError, match="REFERENCE_IDEMPOTENCY_CONFLICT"):
        service.register(ReferenceBatchRequestV1.model_validate(changed), idempotency_key="same-key")
    bad = payload(digest)
    bad["selected_references"][1]["shot_id"] = "shot-t"
    with pytest.raises(ApprovalError, match="REFERENCE_SHOT_NOT_I2V"):
        service.register(ReferenceBatchRequestV1.model_validate(bad), idempotency_key="new-key")
    assert len(db.fetchall("SELECT * FROM approvals", ())) == 1
    with pytest.raises(ValueError):
        ReferenceBatchRequestV1.model_validate(
            dict(payload(digest), user_confirms_preview_and_rights=False))
    with pytest.raises(ValueError):
        ReferenceBatchRequestV1.model_validate(
            dict(payload(digest), selected_references=[candidate("shot-a"), candidate("shot-a")])
        )
    with pytest.raises(ValueError):
        ReferenceBatchRequestV1.model_validate(
            dict(payload(digest), selected_references=[
                dict(candidate("shot-a"), input_relative_path="../secrets.png")]
            )
        )
    with pytest.raises(ApprovalError, match="REFERENCE_GOAL_CREATIVE_LINEAGE_MISMATCH"):
        service.register(
            ReferenceBatchRequestV1.model_validate(dict(payload(digest), goal_id=str(uuid4()))),
            idempotency_key="mismatch-goal",
        )


def test_source_artifact_tamper_rejects_new_requests(state):
    db, service, approval, store, digest = state
    row = db.fetchone("SELECT package_relpath FROM creative_packages WHERE creative_package_id=?", (PACKAGE,))
    artifact = store.resolve_managed_relative(row["package_relpath"])
    artifact.write_bytes(b"tampered")
    with pytest.raises(ApprovalError, match="REFERENCE_CREATIVE_ARTIFACT_MISMATCH"):
        service.register(ReferenceBatchRequestV1.model_validate(payload(digest)), idempotency_key="bad-artifact")
    assert len(db.fetchall("SELECT * FROM approvals", ())) == 0


def test_authenticated_route_post_get_revoke_and_pending_not_approved(state):
    db, service, approval, store, digest = state
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(reference_registration.router, prefix="/api/v1")
    app.state.services = SimpleNamespace(database=db, approvals=approval, creative_store=store)
    app.dependency_overrides[require_auth] = lambda: None  # only local synthetic HTTP fixture
    with TestClient(app) as client:
        data = client.post("/api/v1/production/references/batches",
                           json=payload(digest), headers={"Idempotency-Key": "http-test-key"})
        assert data.status_code == 201, data.text
        obj = data.json()
        assert obj["status"] == "Pending"
        assert len(obj["references"]) == 2
        again = client.post("/api/v1/production/references/batches",
                            json=payload(digest), headers={"Idempotency-Key": "http-test-key"})
        assert again.status_code == 201 and again.json() == obj
        assert client.get("/api/v1/production/references/batches/" + obj["approval_id"]).status_code == 200
        assert client.post(
            f'/api/v1/production/references/batches/{obj["approval_id"]}/revoke',
            json={"request_digest": obj["approval_request_digest"], "reason": "user explicitly revoked"},
        ).json()["status"] == "Revoked"
        assert client.post(
            f'/api/v1/production/references/batches/{obj["approval_id"]}/revoke',
            json={"request_digest": "d" * 64, "reason": "forged"},
        ).status_code == 409


def test_explicit_rejection_never_grants_references(state):
    db, service, approval, store, digest = state
    receipt = service.register(
        ReferenceBatchRequestV1.model_validate(payload(digest)),
        idempotency_key="reject-test",
    )
    approval.decide_for_control_center(
        approval_id=receipt.approval_id, decision="reject",
        request_digest=receipt.approval_request_digest,
        idempotency_key="real-review-decision-test-only",
        resolved_by="synthetic-fixture", reason="not licensed",
    )
    assert service.get(receipt.approval_id).status == "Rejected"
    with pytest.raises(ValueError, match="REFERENCE_ASSET_APPROVAL_NOT_VERIFIED"):
        approved_reference_descriptor(db, identity(receipt, "shot-a"))
    with pytest.raises(ApprovalError, match="REFERENCE_APPROVAL_TERMINAL_CONFLICT"):
        service.revoke(
            receipt.approval_id, request_digest=receipt.approval_request_digest,
            reason="cannot silently rewrite Rejected",
        )


def _v11_service(state):
    from picotoopet_core.creative.repository import CreativeRepository
    from picotoopet_core.production.repository import ProductionRepository
    from picotoopet_core.production.service import ProductionService
    from picotoopet_core.production.store import ProductionArtifactStore

    db, _, _, store, _ = state
    return ProductionService(
        repository=ProductionRepository(db),
        creative_repository=CreativeRepository(db),
        store=ProductionArtifactStore(store.paths),
    )


def _approve_batch(state):
    db, reg, approvals, store, digest = state
    batch = reg.register(
        ReferenceBatchRequestV1.model_validate(payload(digest)),
        idempotency_key="v11-batch-consent",
    )
    approvals.decide_for_control_center(
        approval_id=batch.approval_id, decision="approve",
        request_digest=batch.approval_request_digest,
        idempotency_key="v11-explicit-approval-synthetic-test",
        resolved_by="synthetic-fixture", reason="fixture only",
    )
    return reg.get(batch.approval_id)


def test_reject_reference_not_content_addressed_before_approval(state):
    from pydantic import ValidationError

    db, reg, _, _, digest = state
    clean = payload(digest)
    illegal_paths = [
        "PicotooPet/references/shot-a.png",
        f"PicotooPet/references/{'0' * 64}/shot-a.png",
        f"PicotooPet/references/{SHA}/shot-b.png",
        f"PicotooPet/references/{SHA}/shot-a.jpeg",
        f"PicotooPet/references/{SHA}/../shot-a.png",
    ]
    for bad in illegal_paths:
        source = json.loads(json.dumps(clean))
        source["selected_references"][0]["input_relative_path"] = bad
        with pytest.raises(ValidationError, match="REFERENCE_MANAGED_PATH_INVALID"):
            ReferenceBatchRequestV1.model_validate(source)
    assert db.fetchall("SELECT * FROM approvals", ()) == []


def test_v11_plan_disallows_noncanonical_approved_reference_path(state):
    from picotoopet_core.production.versioned_plan import (
        ProductionJobCreateV11Request, ProductionPlanV11,
    )
    from pydantic import ValidationError

    db, _, _, _, _ = state
    batch = _approve_batch(state)
    service = _v11_service(state)
    job = service.create_job_v11(ProductionJobCreateV11Request(
        creative_package_id=PACKAGE, idempotency_key="v11-validated-reference-sha",
        approved_reference_ids=[batch.approval_id],
    ))
    plan = service.get_plan(job.production_job_id)
    assert isinstance(plan, ProductionPlanV11)
    raw = plan.model_dump(mode="json")
    raw["tasks"][0]["reference_asset"]["input_relative_path"] = "PicotooPet/references/shot-a.png"
    raw["tasks"][0]["trusted_input_asset_ref"] = "PicotooPet/references/shot-a.png"
    with pytest.raises(ValidationError, match="PRODUCTION_V11_REFERENCE_NOT_CONTENT_ADDRESSED"):
        ProductionPlanV11.model_validate(raw)


def test_v11_actual_job_persists_approved_two_i2v_plus_t2v_and_rechecks_revocation(state):
    from picotoopet_core.production.versioned_plan import (
        ProductionJobCreateV11Request, ProductionPlanV11, ProductionTaskRecordV11,
    )

    db, registration, approvals, store, digest = state
    service = _v11_service(state)
    batch = _approve_batch(state)
    request = ProductionJobCreateV11Request(
        creative_package_id=PACKAGE, schema_version="1.1",
        idempotency_key="v11-production-idempotent",
        approved_reference_ids=[batch.approval_id],
    )
    job = service.create_job_v11(request)
    plan = service.get_plan(job.production_job_id)
    assert isinstance(plan, ProductionPlanV11)
    assert plan.schema_version == "1.1"
    assert [task.shot_id for task in plan.tasks] == ["shot-a", "shot-b", "shot-t"]
    assert [task.reference_asset is not None for task in plan.tasks] == [True, True, False]
    assert plan.tasks[2].workflow_id == "comfy.wan22.ti2v5b.t2v.v1"
    for task in plan.tasks[:2]:
        ref = task.reference_asset
        assert ref is not None
        assert ref.production_job_id == job.production_job_id
        assert ref.production_task_id == task.production_task_id
        assert ref.approval_id == batch.approval_id
        assert ref.creative_package_digest == digest
        assert ref.goal_id == GOAL
        response = service.authorize_reference_v11(job.production_job_id, task.production_task_id)
        assert response.descriptor.asset_id == ref.asset_id
        assert response.plan_digest == job.plan_digest
        stored = service.repository.get_task(job.production_job_id, task.production_task_id)
        assert isinstance(stored, ProductionTaskRecordV11)
        assert stored.task_plan.reference_asset == ref

    assert service.create_job_v11(request).production_job_id == job.production_job_id
    with pytest.raises(ValueError, match="PRODUCTION_V11_WORKER_ADAPTER_REQUIRED"):
        service.claim(job.production_job_id, "windows-executor")
    with pytest.raises(ValueError, match="PRODUCTION_V11_WORKER_ADAPTER_REQUIRED"):
        service.repository.claim_job(job.production_job_id, "windows-executor")
    assert service.repository.get_job(job.production_job_id).lease_executor_id is None
    assert all(task.attempt_count == 0 for task in service.repository.list_tasks(job.production_job_id))

    raw = db.fetchone("SELECT plan_json FROM production_jobs WHERE production_job_id=?",
                      (job.production_job_id,))["plan_json"]
    db.close()
    db.open()
    assert service.get_plan(job.production_job_id) == plan
    assert db.fetchone("SELECT plan_json FROM production_jobs WHERE production_job_id=?",
                       (job.production_job_id,))["plan_json"] == raw
    assert service.authorize_reference_v11(
        job.production_job_id, plan.tasks[0].production_task_id
    ).descriptor.approval_id == batch.approval_id

    registration.revoke(batch.approval_id,
                        request_digest=batch.approval_request_digest, reason="explicitly revoked")
    with pytest.raises(ValueError, match="REFERENCE_ASSET_APPROVAL_NOT_VERIFIED"):
        service.authorize_reference_v11(job.production_job_id, plan.tasks[0].production_task_id)
    with pytest.raises(ValueError, match="PRODUCTION_V11_WORKER_ADAPTER_REQUIRED"):
        service.claim(job.production_job_id, "windows-executor")
    assert service.get_plan(job.production_job_id) == plan  # no recompile after revoke


def test_v11_pending_rejected_and_wrong_approval_cannot_create_job(state):
    from picotoopet_core.production.versioned_plan import ProductionJobCreateV11Request
    db, reg, approvals, store, digest = state
    service = _v11_service(state)
    pending = reg.register(
        ReferenceBatchRequestV1.model_validate(payload(digest)), idempotency_key="v11-pending",
    )
    def req(key, ids):
        return ProductionJobCreateV11Request(
            creative_package_id=PACKAGE, idempotency_key=key, approved_reference_ids=ids
        )
    with pytest.raises(ValueError, match="PRODUCTION_V11_REFERENCE_NOT_APPROVED"):
        service.create_job_v11(req("unapproved-v11", [pending.approval_id]))
    approvals.decide_for_control_center(
        approval_id=pending.approval_id, decision="reject",
        request_digest=pending.approval_request_digest,
        idempotency_key="v11-explicit-reject", resolved_by="synthetic-fixture",
        reason="reject fixture",
    )
    with pytest.raises(ValueError, match="PRODUCTION_V11_REFERENCE_NOT_APPROVED"):
        service.create_job_v11(req("rejected-v11", [pending.approval_id]))
    assert db.fetchall("SELECT * FROM production_jobs", ()) == []
    with pytest.raises(ValueError):
        ProductionJobCreateV11Request(
            creative_package_id=PACKAGE, idempotency_key="duplicate-ids",
            approved_reference_ids=[pending.approval_id, pending.approval_id],
        )


def test_v11_authenticated_api_returns_exact_version_and_denies_old_worker(state):
    from picotoopet_core.api.routes import production
    from picotoopet_core.production.versioned_plan import ProductionPlanV11

    db, _, approval, store, digest = state
    batch = _approve_batch(state)
    service = _v11_service(state)
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(production.router, prefix="/api/v1")
    app.state.services = SimpleNamespace(production=service)
    app.dependency_overrides[require_auth] = lambda: None
    with TestClient(app) as client:
        response = client.post("/api/v1/production/jobs/v1.1", json={
            "schema_version": "1.1", "creative_package_id": PACKAGE,
            "production_profile": "production.comfyui.v1", "idempotency_key": "http-v11",
            "approved_reference_ids": [batch.approval_id],
        })
        assert response.status_code == 200, response.text
        job_id = response.json()["production_job_id"]
        result = client.get(f"/api/v1/production/jobs/{job_id}/plan")
        assert result.status_code == 200
        plan = ProductionPlanV11.model_validate(result.json())
        assert plan.schema_version == "1.1"
        task = plan.tasks[0]
        auth = client.get(
            f"/api/v1/production/jobs/{job_id}/tasks/{task.production_task_id}/reference-authorization"
        )
        assert auth.status_code == 200, auth.text
        assert auth.json()["descriptor"]["asset_id"] == task.reference_asset.asset_id
        assert client.post(f"/api/v1/production/jobs/{job_id}/claim",
                           json={"executor_id": "windows-p0"}).status_code == 409
        assert client.get(f"/api/v1/production/jobs/{job_id}/plan").json() == result.json()


def test_v10_plan_parser_keeps_legacy_json_and_rejects_unknown_versions(state):
    from picotoopet_core.production.compiler import compile_production_plan
    from picotoopet_core.production.versioned_plan import parse_versioned_plan
    from picotoopet_core.production.models import ProductionPlan
    db, _, _, _, digest = state
    manifest = json.loads(db.fetchone(
        "SELECT manifest_json FROM creative_packages WHERE creative_package_id=?", (PACKAGE,)
    )["manifest_json"])
    legacy = compile_production_plan(str(uuid4()), manifest, digest)
    raw = legacy.model_dump(mode="json")
    parsed = parse_versioned_plan(raw)
    assert type(parsed) is ProductionPlan
    assert parsed.model_dump(mode="json") == raw
    with pytest.raises(ValueError, match="PRODUCTION_PLAN_SCHEMA_UNSUPPORTED"):
        parse_versioned_plan(dict(raw, schema_version="1.2"))
