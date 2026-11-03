"""#205: real reference-registration API → actual ApprovalService → sealed-v2 new I2V plan.

Offline SQLite + scripted Creative outputs only. No user-image bytes, GPU, Comfy or lease.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from director_fixtures import open_runtime
from test_local_goal_live_route import ORDINARY, THREE_SHOT, _GoalFacts, _v1_outputs, _v2_outputs
from test_v2_reference_i2v_bridge import Case

from picotoopet_core.api.errors import install_error_handlers
from picotoopet_core.api.routes import reference_registration
from picotoopet_core.approvals.service import ApprovalError
from picotoopet_core.handoffs.approvals import HandoffApprovalService
from picotoopet_core.production.reference_registration import (
    ReferenceBatchRequestV1, ReferenceRegistrationService,
)
from picotoopet_core.production.versioned_plan import ProductionPlanV11
from picotoopet_core.security.auth import require_auth


def _candidates(shots: list[str]) -> list[dict[str, object]]:
    """Declare only Windows-origin SHA *claims*, never imply local Mac byte reads."""
    items: list[dict[str, object]] = []
    for i, shot in enumerate(shots, start=1):
        sha = f"{i:064x}"
        items.append({
            "shot_id": shot,
            "input_relative_path": f"PicotooPet/references/{sha}/{shot}.png",
            "sha256": sha,
            "bytes": 4096 + i,
            "source_reference": "USER_SUPPLIED",
            "source_digest": "e" * 64,
            "rights_scope": "wan22.i2v.production.v1",
        })
    return items


def _payload(case: Case, shots: list[str] | None = None) -> dict[str, object]:
    return {
        "schema_version": "reference_batch.v1",
        "goal_id": case.goal_id,
        "creative_package_id": case.package.creative_package_id,
        "creative_package_digest": case.package.package_digest,
        "selected_references": _candidates(case.shots if shots is None else shots),
        "user_confirms_preview_and_rights": True,
    }


@pytest.fixture
def live(tmp_path):
    rt = open_runtime(tmp_path)
    case = Case(rt, _GoalFacts(rt, THREE_SHOT), _v2_outputs)
    approvals = HandoffApprovalService(rt.database, None)
    register = ReferenceRegistrationService(rt.database, approvals, rt.store)
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(reference_registration.router, prefix="/api/v1")
    app.state.services = SimpleNamespace(
        database=rt.database, approvals=approvals, creative_store=rt.store,
    )
    app.dependency_overrides[require_auth] = lambda: None  # ── Synthetic auth only.
    try:
        yield case, approvals, register, app
    finally:
        rt.database.close()


def test_real_registration_pending_approved_to_new_frozen_i2v_through_http(live) -> None:
    case, approvals, register, app = live
    before = case.stored_package()
    payload = _payload(case)

    # ── Actual authenticated API route creates only a pending consent record. ──
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/production/references/batches", json=payload,
            headers={"Idempotency-Key": "v2-full-approved-request"},
        )
        assert response.status_code == 201, response.text
        pending = response.json()
        assert pending["status"] == "Pending"
        assert {r["shot_id"] for r in pending["references"]} == set(case.shots)
        assert client.post(
            "/api/v1/production/references/batches", json=payload,
            headers={"Idempotency-Key": "v2-full-approved-request"},
        ).json() == pending
        assert case.counts() == (0, 0)

        # ── Pending is not approval; new I2V plan must not exist. ──
        with pytest.raises(ValueError, match="PRODUCTION_V11_REFERENCE_NOT_APPROVED"):
            case.service.create_job_v11(case.request(
                [pending["approval_id"]], key="pending-cannot-create",
            ))
        assert case.counts() == (0, 0)

        # ── Explicit decision uses the real persisted ApprovalService scope/digest. ──
        approvals.decide_for_control_center(
            approval_id=pending["approval_id"], decision="approve",
            request_digest=pending["approval_request_digest"],
            idempotency_key="explicit-v2-approval-test",
            resolved_by="synthetic-fixture", reason="offline-test-only",
        )
        assert register.get(pending["approval_id"]).status == "Approved"

        job = case.service.create_job_v11(case.request(
            [pending["approval_id"]], key="approved-fresh-v2-i2v",
        ))
        frozen = case.service.get_plan(job.production_job_id)
        assert isinstance(frozen, ProductionPlanV11)
        assert frozen.schema_version == "1.1"
        assert [task.shot_id for task in frozen.tasks] == case.shots
        assert {task.render_intent for task in frozen.tasks} == {"IMAGE_TO_VIDEO"}
        assert len({task.production_task_id for task in frozen.tasks}) == 3
        assert all(task.reference_asset is not None for task in frozen.tasks)
        assert {task.reference_asset.approval_id for task in frozen.tasks} == {
            pending["approval_id"]
        }
        assert job.plan_digest == case.service._digest(frozen.model_dump(mode="json"))
        assert case.stored_package() == before
        assert case.counts() == (1, 0)

        # ── Revocation stops new authorizations, never silently deletes frozen history. ──
        revoked = client.post(
            "/api/v1/production/references/batches/" + pending["approval_id"] + "/revoke",
            json={"request_digest": pending["approval_request_digest"],
                  "reason": "synthetic owner revocation"},
        )
        assert revoked.status_code == 200 and revoked.json()["status"] == "Revoked"
        with pytest.raises(ValueError, match="REFERENCE_ASSET_APPROVAL_NOT_VERIFIED"):
            case.service.authorize_reference_v11(
                job.production_job_id, frozen.tasks[0].production_task_id,
            )
        assert case.counts() == (1, 0)


def test_incomplete_or_foreign_v2_refs_fail_before_writing_approval(live) -> None:
    case, _, register, _ = live
    for bad_shots in (
        case.shots[:2],
        case.shots[1:2],
        [*case.shots[:2], "foreign-shot"],
    ):
        request = ReferenceBatchRequestV1.model_validate(_payload(case, bad_shots))
        with pytest.raises(ApprovalError, match="PRODUCTION_V11_BRIDGE_FULL_COVERAGE_REQUIRED"):
            register.register(request, idempotency_key="negative-" + "-".join(bad_shots))
    assert case.rt.database.scalar("SELECT COUNT(*) FROM approvals") == 0
    assert case.counts() == (0, 0)


def test_false_goal_digest_and_managed_path_never_register(live) -> None:
    case, _, register, _ = live
    source = _payload(case)
    with pytest.raises(ApprovalError, match="REFERENCE_GOAL_CREATIVE_LINEAGE_MISMATCH"):
        register.register(
            ReferenceBatchRequestV1.model_validate({**source, "goal_id": "00000000-0000-4000-8000-000000000009"}),
            idempotency_key="wrong-goal",
        )
    with pytest.raises(ApprovalError, match="REFERENCE_CREATIVE_PACKAGE_NOT_FROZEN"):
        register.register(
            ReferenceBatchRequestV1.model_validate({**source, "creative_package_digest": "0" * 64}),
            idempotency_key="wrong-digest",
        )
    tampered = json.loads(json.dumps(source))
    tampered["selected_references"][0]["input_relative_path"] = "../unmanaged.png"
    with pytest.raises(ValueError, match="REFERENCE_MANAGED_PATH_INVALID"):
        ReferenceBatchRequestV1.model_validate(tampered)
    assert case.rt.database.scalar("SELECT COUNT(*) FROM approvals") == 0


def test_unsealed_v2_is_rejected_even_if_all_shots_present(live) -> None:
    case, _, register, _ = live
    # ── DB-only edits must fail against the original frozen source ZIP digest. ──
    row = case.rt.database.fetchone(
        "SELECT manifest_json FROM creative_packages WHERE creative_package_id=?",
        (case.package.creative_package_id,),
    )
    manifest = json.loads(row["manifest_json"])
    manifest["stage_results"]["shot_plan.v1"]["shots"][0]["action"] = "forged"
    case.rt.database.execute(
        "UPDATE creative_packages SET manifest_json=? WHERE creative_package_id=?",
        (json.dumps(manifest, sort_keys=True), case.package.creative_package_id),
    )
    with pytest.raises(ApprovalError, match="REFERENCE_CREATIVE_ARTIFACT_MISMATCH"):
        register.register(
            ReferenceBatchRequestV1.model_validate(_payload(case)),
            idempotency_key="forged-database-bible",
        )
    assert case.rt.database.scalar("SELECT COUNT(*) FROM approvals") == 0


def test_v1_t2v_packages_stay_ineligible(tmp_path) -> None:
    rt = open_runtime(tmp_path)
    try:
        case = Case(rt, _GoalFacts(rt, ORDINARY), _v1_outputs)
        register = ReferenceRegistrationService(
            rt.database, HandoffApprovalService(rt.database, None), rt.store,
        )
        with pytest.raises(ApprovalError, match="REFERENCE_SHOT_NOT_I2V_OR_NOT_IN_PACKAGE"):
            register.register(
                ReferenceBatchRequestV1.model_validate(_payload(case)),
                idempotency_key="v1-t2v-stays-blocked",
            )
        assert rt.database.scalar("SELECT COUNT(*) FROM approvals") == 0
    finally:
        rt.database.close()
