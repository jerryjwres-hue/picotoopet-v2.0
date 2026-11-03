"""Issue #203: sealed Creative v2 package + approved per-shot references -> NEW v1.1 I2V plan.

Real SQLite, real Creative v2 package (built through the real Goal handler and the scripted Ollama
transport), real ProductionService.create_job_v11. Approval rows are synthetic, written in the exact
``reference_consent_batch.v1`` shape the registration service persists. Nothing here verifies
Windows bytes, starts a lease, or reaches Comfy/GPU; those remain UNVERIFIED.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from director_fixtures import OllamaDouble, Runtime, open_runtime
from test_local_goal_live_route import (
    ORDINARY,
    THREE_SHOT,
    _creative_task,
    _GoalFacts,
    _v1_outputs,
    _v2_outputs,
)

from picotoopet_core.approvals.service import ApprovalService
from picotoopet_core.creative.execution import CreativeIntelligenceCoordinator
from picotoopet_core.production.models import ProductionJobCreateRequest
from picotoopet_core.production.profile import I2V_WORKFLOW_ID
from picotoopet_core.production.repository import ProductionRepository
from picotoopet_core.production.service import ProductionService
from picotoopet_core.production.store import ProductionArtifactStore
from picotoopet_core.production.versioned_plan import (
    ProductionJobCreateV11Request,
    ProductionPlanV11,
)

RIGHTS = "wan22.i2v.production.v1"


class Case:
    def __init__(self, rt: Runtime, facts: _GoalFacts, outputs_for) -> None:  # type: ignore[no-untyped-def]
        result = facts.coordinator(rt).handler(facts.task())
        self.job_id = result.summary["creative_job_id"]
        ref = rt.source_ref_for(self.job_id)
        double = OllamaDouble(outputs_for(ref))
        CreativeIntelligenceCoordinator(
            database=rt.database, queue=rt.queue, repository=rt.repository,
            source_normalizer=rt.source, store=rt.store, adapter=double.adapter,
            configured_model_id="gpt-oss:20b",
        ).handler(_creative_task(rt, self.job_id))
        record = rt.service.get_package(self.job_id)
        assert record is not None
        self.rt, self.goal_id, self.package = rt, facts.goal_id, record
        self.shots = [s["shot_id"] for s in record.manifest["stage_results"]["shot_plan.v1"]["shots"]]
        self.service = ProductionService(
            repository=ProductionRepository(rt.database), creative_repository=rt.repository,
            store=ProductionArtifactStore(rt.store.paths),
        )

    def approval(self, shots, *, status="Approved", expires=None, rights=RIGHTS, goal_id=None,
                 digest=None, job_id=None, attest=True, resolved=True) -> str:
        approval_id = str(uuid4())
        now = datetime.now(UTC)
        references = [
            {"asset_id": str(uuid4()), "shot_id": shot,
             "input_relative_path": f"PicotooPet/references/{chr(97 + i) * 64}/{shot}.png",
             "sha256": chr(97 + i) * 64, "bytes": 1024 + i,
             "source_reference": "USER_SUPPLIED", "source_digest": "e" * 64}
            for i, shot in enumerate(shots)
        ]
        scope = {
            "schema_version": "reference_consent_batch.v1", "batch_id": str(uuid4()),
            "goal_id": goal_id or self.goal_id,
            "creative_job_id": job_id or self.job_id,
            "creative_package_id": self.package.creative_package_id,
            "creative_package_digest": digest or self.package.package_digest,
            "rights_scope": rights, "explicit_rights_attestation": attest,
            "byte_provenance": "WINDOWS_CLIENT_CLAIM_NOT_CORE_HASHED",
            "reference_count": len(references), "shot_ids": ",".join(shots),
            "references": references,
        }
        self.rt.database.execute(
            "INSERT INTO approvals (approval_id,task_id,approval_type,scope_json,status,"
            "token_hash,requested_by,expires_at,requested_at,resolved_by,resolved_at,"
            "decision_reason) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (approval_id, None, "production.reference_asset.v1",
             json.dumps(scope, sort_keys=True), status, "z" * 64, "synthetic-fixture",
             (expires or now + timedelta(days=1)).isoformat(), now.isoformat(),
             "synthetic-fixture-not-a-real-user" if resolved else None,
             now.isoformat() if resolved else None, "unit-test-only" if resolved else None),
        )
        return approval_id

    def request(self, approvals, key="bridge-key") -> ProductionJobCreateV11Request:
        return ProductionJobCreateV11Request(
            creative_package_id=self.package.creative_package_id,
            idempotency_key=key, approved_reference_ids=list(approvals),
        )

    def counts(self) -> tuple[int, int]:
        db = self.rt.database
        return (db.scalar("SELECT COUNT(*) FROM production_jobs"),
                db.scalar("SELECT COUNT(*) FROM production_attempts"))

    def stored_package(self) -> tuple[str, str]:
        row = self.rt.database.fetchone(
            "SELECT package_digest,manifest_json FROM creative_packages WHERE creative_package_id=?",
            (self.package.creative_package_id,))
        return row["package_digest"], row["manifest_json"]


@pytest.fixture
def case(tmp_path):  # type: ignore[no-untyped-def]
    rt = open_runtime(tmp_path)
    yield Case(rt, _GoalFacts(rt, THREE_SHOT), _v2_outputs)
    rt.database.close()


def test_sealed_v2_package_is_t2v_until_three_approved_references_create_a_new_i2v_plan(
    case: Case,
) -> None:
    stage = case.package.manifest["stage_results"]
    assert {s["render_intent"] for s in stage["shot_plan.v1"]["shots"]} == {"GENERATIVE_VIDEO"}
    before = case.stored_package()

    ids = [case.approval(case.shots[:2]), case.approval(case.shots[2:])]
    job = case.service.create_job_v11(case.request(ids))
    plan = case.service.get_plan(job.production_job_id)

    assert isinstance(plan, ProductionPlanV11) and plan.schema_version == "1.1"
    assert [t.shot_id for t in plan.tasks] == case.shots
    assert {t.render_intent for t in plan.tasks} == {"IMAGE_TO_VIDEO"}
    assert {t.workflow_id for t in plan.tasks} == {I2V_WORKFLOW_ID}
    assert len({t.production_task_id for t in plan.tasks}) == 3
    assert len({t.reference_asset.asset_id for t in plan.tasks}) == 3
    for task in plan.tasks:
        ref = task.reference_asset
        assert ref is not None and ref.shot_id == task.shot_id
        assert ref.production_task_id == task.production_task_id
        assert ref.creative_package_digest == case.package.package_digest
        assert ref.input_relative_path == task.trusted_input_asset_ref
        assert ref.rights_scope == RIGHTS and ref.goal_id == case.goal_id
        assert ref.approval_id in ids
    assert plan.creative_package_digest == case.package.package_digest
    assert job.plan_digest == case.service._digest(plan.model_dump(mode="json"))

    # The sealed Creative Package is byte-identical and still says T2V.
    assert case.stored_package() == before
    assert case.counts() == (1, 0)
    assert case.service.authorize_reference_v11(
        job.production_job_id, plan.tasks[0].production_task_id
    ).reference_asset.shot_id == case.shots[0]

    # Same request replays to the same frozen job; a different approval set conflicts.
    assert case.service.create_job_v11(case.request(ids)).production_job_id == job.production_job_id
    other = case.approval(case.shots)
    with pytest.raises(ValueError, match="PRODUCTION_V11_IDEMPOTENCY_CONFLICT"):
        case.service.create_job_v11(case.request([other]))
    assert case.counts() == (1, 0)

    # An Approved row is not a GPU lease: the v1.1 claim stays disabled; no attempt exists.
    with pytest.raises(ValueError, match="PRODUCTION_V11_WORKER_ADAPTER_REQUIRED"):
        case.service.claim(job.production_job_id, "worker-one")
    assert case.counts() == (1, 0)


def test_existing_frozen_t2v_plan_is_unchanged_by_a_later_bridge_job(case: Case) -> None:
    legacy = case.service.create_job(ProductionJobCreateRequest(
        creative_package_id=case.package.creative_package_id, idempotency_key="legacy-t2v",
    ))
    frozen = case.service.get_plan(legacy.production_job_id).model_dump(mode="json")
    assert {t["render_intent"] for t in frozen["tasks"]} == {"GENERATIVE_VIDEO"}

    bridged = case.service.create_job_v11(case.request([case.approval(case.shots)]))
    assert bridged.production_job_id != legacy.production_job_id
    again = case.service.get_job(legacy.production_job_id)
    assert again.plan_digest == legacy.plan_digest
    assert case.service.get_plan(legacy.production_job_id).model_dump(mode="json") == frozen


def test_no_approval_or_partial_coverage_fails_closed_without_downgrade(case: Case) -> None:
    with pytest.raises(ValueError, match="at least 1 item"):  # request model rejects no approvals
        case.request([])
    with pytest.raises(ValueError, match="PRODUCTION_V11_BRIDGE_FULL_COVERAGE_REQUIRED"):
        case.service.create_job_v11(case.request([case.approval(case.shots[:2])], key="two"))
    with pytest.raises(ValueError, match="PRODUCTION_V11_BRIDGE_FULL_COVERAGE_REQUIRED"):
        case.service.create_job_v11(case.request(
            [case.approval([*case.shots[:2], "shot-not-in-package"])], key="foreign"))
    assert case.counts() == (0, 0)


def test_duplicate_grant_for_one_shot_is_rejected(case: Case) -> None:
    ids = [case.approval(case.shots), case.approval(case.shots[:1])]
    with pytest.raises(ValueError, match="PRODUCTION_V11_DUPLICATE_SHOT_GRANT"):
        case.service.create_job_v11(case.request(ids))
    assert case.counts() == (0, 0)


@pytest.mark.parametrize(
    ("override", "code"),
    [
        ({"status": "Pending"}, "PRODUCTION_V11_REFERENCE_NOT_APPROVED"),
        ({"status": "Revoked"}, "PRODUCTION_V11_REFERENCE_NOT_APPROVED"),
        ({"status": "Rejected"}, "PRODUCTION_V11_REFERENCE_NOT_APPROVED"),
        ({"expires": datetime.now(UTC) - timedelta(minutes=1)},
         "PRODUCTION_V11_REFERENCE_NOT_APPROVED"),
        ({"rights": "other.rights.v1"}, "PRODUCTION_V11_REFERENCE_SOURCE_MISMATCH"),
        ({"attest": False}, "PRODUCTION_V11_REFERENCE_SOURCE_MISMATCH"),
        ({"goal_id": "another-goal"}, "PRODUCTION_V11_REFERENCE_SOURCE_MISMATCH"),
        ({"digest": "0" * 64}, "PRODUCTION_V11_REFERENCE_SOURCE_MISMATCH"),
        ({"job_id": "another-creative-job"}, "PRODUCTION_V11_REFERENCE_SOURCE_MISMATCH"),
        ({"resolved": False}, "REFERENCE_ASSET_APPROVAL_NOT_VERIFIED"),
    ],
)
def test_unusable_approval_rows_never_create_a_plan(case: Case, override, code) -> None:  # type: ignore[no-untyped-def]
    bad = case.approval(case.shots, **override)
    with pytest.raises(ValueError, match=code):
        case.service.create_job_v11(case.request([bad]))
    assert case.counts() == (0, 0)


def test_forged_scope_bytes_or_path_are_not_trusted(case: Case) -> None:
    approval_id = case.approval(case.shots)
    row = case.rt.database.fetchone("SELECT scope_json FROM approvals WHERE approval_id=?",
                                    (approval_id,))
    scope = json.loads(row["scope_json"])
    scope["references"][0]["input_relative_path"] = "../outside/secret.png"
    case.rt.database.execute("UPDATE approvals SET scope_json=? WHERE approval_id=?",
                             (json.dumps(scope, sort_keys=True), approval_id))
    with pytest.raises(ValueError):
        case.service.create_job_v11(case.request([approval_id]))
    assert case.counts() == (0, 0)


def test_package_whose_shot_plan_is_not_the_exact_bible_derivation_is_not_bridged(
    case: Case,
) -> None:
    row = case.rt.database.fetchone(
        "SELECT manifest_json FROM creative_packages WHERE creative_package_id=?",
        (case.package.creative_package_id,))
    manifest = json.loads(row["manifest_json"])
    manifest["stage_results"]["shot_plan.v1"]["shots"][1]["action"] = "tampered action text"
    case.rt.database.execute(
        "UPDATE creative_packages SET manifest_json=? WHERE creative_package_id=?",
        (json.dumps(manifest), case.package.creative_package_id))
    with pytest.raises(ValueError, match="PRODUCTION_V11_BRIDGE_PACKAGE_NOT_SEALED_V2"):
        case.service.create_job_v11(case.request([case.approval(case.shots)]))
    assert case.counts() == (0, 0)


def test_v1_package_without_a_bible_is_never_bridged(tmp_path) -> None:  # type: ignore[no-untyped-def]
    rt = open_runtime(tmp_path)
    try:
        v1 = Case(rt, _GoalFacts(rt, ORDINARY), _v1_outputs)
        assert "video_bible.v1" not in v1.package.manifest["stage_results"]
        with pytest.raises(ValueError, match="PRODUCTION_V11_REFERENCE_SHOT_COVERAGE_INVALID"):
            v1.service.create_job_v11(v1.request([v1.approval(v1.shots)]))
        assert v1.counts() == (0, 0)
    finally:
        rt.database.close()


def test_request_digest_helper_is_the_real_approval_digest(case: Case) -> None:
    # Guards the fixture itself: the plan must bind the digest ApprovalService computes.
    approval_id = case.approval(case.shots)
    job = case.service.create_job_v11(case.request([approval_id]))
    plan = case.service.get_plan(job.production_job_id)
    row = case.rt.database.fetchone("SELECT * FROM approvals WHERE approval_id=?", (approval_id,))
    assert {t.reference_asset.approval_request_digest for t in plan.tasks} == {
        ApprovalService._request_digest(row)}
