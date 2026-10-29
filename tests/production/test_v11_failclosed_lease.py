"""Core-only v1.1 offline lease boundary, real SQLite, zero GPU/HTTP POST.

The reference registration fixture carries a real persisted approval and PlanV11.
No fixture here represents verified Windows bytes or a durable LoadImage snapshot.
"""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest

from picotoopet_core.production.models import (
    ProductionHeartbeatRequest,
    ProductionTaskAttemptRequest,
    ProductionTaskCommitRequest,
    ProductionTaskFailureRequest,
)
from picotoopet_core.production.versioned_plan import ProductionJobCreateV11Request
from picotoopet_core.production.attempts import reserve_or_bind_attempt
from picotoopet_core.production.failures import fail_task_durably

# ── Reuse the native registration fixture: no duplicate approval authority. ──
from test_reference_registration_api import (  # noqa: E402
    PACKAGE,
    _approve_batch,
    _v11_service,
    state as reference_state,
)


@pytest.fixture()
def case(reference_state):
    # ── Approved Core row is still NOT a Windows byte/snapshot attestation. ──
    db, registration, _, _, _ = reference_state
    approval = _approve_batch(reference_state)
    service = _v11_service(reference_state)
    job = service.create_job_v11(
        ProductionJobCreateV11Request(
            creative_package_id=PACKAGE,
            idempotency_key="core-v11-offline-failclosed",
            approved_reference_ids=[approval.approval_id],
        )
    )
    return db, registration, service, job, service.get_plan(job.production_job_id), approval


def _assert_no_execution(db, job_id):
    # ── No claim token/attempt/output should survive any rejected path. ──
    row = db.fetchone(
        "SELECT lease_token_digest,lease_executor_id FROM production_jobs WHERE production_job_id=?",
        (job_id,),
    )
    assert row["lease_token_digest"] is None
    assert row["lease_executor_id"] is None
    assert db.scalar(
        "SELECT COUNT(*) FROM production_attempts WHERE production_job_id=?", (job_id,)
    ) == 0


def _attempt(db, job_id, task_id, number, executor, prompt=None, *,
             status="Running", failure=None):
    # ── A synthetic crash-state row is not a Comfy POST and cannot authorize one. ──
    db.execute(
        "INSERT INTO production_attempts("
        "production_attempt_id,production_job_id,production_task_id,attempt_number,"
        "executor_id,comfy_prompt_id,status,started_at,failure_code) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (f"synthetic-{task_id}-{number}", job_id, task_id, number,
         executor, prompt, status, datetime.now(UTC).isoformat(), failure),
    )


def test_clean_core_audit_is_not_a_production_claim(case):
    db, _, service, job, plan, _ = case
    service._audit_v11_core_before_lease(job.production_job_id, "worker-one")
    assert [task.reference_asset is not None for task in plan.tasks] == [True, True, False]
    # ── Neither normal service nor direct repository APIs may mint v1.1 lease. ──
    with pytest.raises(ValueError, match="PRODUCTION_V11_WORKER_ADAPTER_REQUIRED"):
        service.claim(job.production_job_id, "worker-one")
    with pytest.raises(ValueError, match="PRODUCTION_V11_WORKER_ADAPTER_REQUIRED"):
        service.repository.claim_job(job.production_job_id, "worker-one")
    _assert_no_execution(db, job.production_job_id)


@pytest.mark.parametrize("mutator", ["revoke", "expire", "wrong_digest", "missing_approval"])
def test_approval_mutation_revokes_core_audit_without_lease(case, mutator):
    db, registration, service, job, _, approval = case
    if mutator == "revoke":
        registration.revoke(approval.approval_id,
                            request_digest=approval.approval_request_digest,
                            reason="revoked by owner in offline fixture")
    elif mutator == "expire":
        db.execute("UPDATE approvals SET expires_at=? WHERE approval_id=?",
                   ((datetime.now(UTC) - timedelta(minutes=1)).isoformat(), approval.approval_id))
    elif mutator == "wrong_digest":
        db.execute("UPDATE approvals SET scope_json=? WHERE approval_id=?",
                   ('{"malformed":"scope"}', approval.approval_id))
    else:
        db.execute("DELETE FROM approvals WHERE approval_id=?", (approval.approval_id,))
    with pytest.raises(ValueError, match="REFERENCE_ASSET_APPROVAL_"):
        service._audit_v11_core_before_lease(job.production_job_id, "worker-one")
    with pytest.raises(ValueError, match="PRODUCTION_V11_WORKER_ADAPTER_REQUIRED"):
        service.claim(job.production_job_id, "worker-one")
    _assert_no_execution(db, job.production_job_id)


@pytest.mark.parametrize("tamper", ["plan_digest", "package_digest", "shot_identity", "task_json", "missing_task"])
def test_frozen_plan_and_task_identity_tamper_never_leases(case, tamper):
    db, _, service, job, plan, _ = case
    task_id = plan.tasks[0].production_task_id
    if tamper == "plan_digest":
        db.execute("UPDATE production_jobs SET plan_digest=? WHERE production_job_id=?",
                   ("0" * 64, job.production_job_id))
    elif tamper == "package_digest":
        db.execute("UPDATE production_jobs SET creative_package_digest=? WHERE production_job_id=?",
                   ("0" * 64, job.production_job_id))
    elif tamper == "shot_identity":
        db.execute("UPDATE production_tasks SET shot_id=? WHERE production_task_id=?",
                   ("wrong-shot", task_id))
    elif tamper == "task_json":
        raw = plan.tasks[0].model_dump(mode="json")
        raw["positive_prompt"] = "untrusted new prompt"
        db.execute("UPDATE production_tasks SET task_plan_json=? WHERE production_task_id=?",
                   (json.dumps(raw), task_id))
    else:
        db.execute("DELETE FROM production_tasks WHERE production_task_id=?", (task_id,))
    with pytest.raises(ValueError, match="PRODUCTION_V11_"):
        service._audit_v11_core_before_lease(job.production_job_id, "worker-one")
    with pytest.raises(ValueError, match="PRODUCTION_V11_WORKER_ADAPTER_REQUIRED"):
        service.claim(job.production_job_id, "worker-one")
    _assert_no_execution(db, job.production_job_id)


def test_wrong_job_and_terminal_job_never_pass_audit(case):
    db, _, service, job, _, _ = case
    with pytest.raises(KeyError):
        service._audit_v11_core_before_lease("wrong-job", "worker-one")
    db.execute("UPDATE production_jobs SET status='Failed' WHERE production_job_id=?",
               (job.production_job_id,))
    with pytest.raises(ValueError, match="PRODUCTION_V11_JOB_NOT_CLAIMABLE"):
        service._audit_v11_core_before_lease(job.production_job_id, "worker-one")


def test_unknown_unbound_attempt1_cannot_be_treated_as_pre_post(case):
    db, _, service, job, plan, _ = case
    task_id = plan.tasks[0].production_task_id
    _attempt(db, job.production_job_id, task_id, 1, "worker-one")
    db.execute("UPDATE production_tasks SET status='Running',attempt_count=1 WHERE production_task_id=?",
               (task_id,))
    with pytest.raises(ValueError, match="PRODUCTION_V11_UNBOUND_POST_UNVERIFIED"):
        service._audit_v11_core_before_lease(job.production_job_id, "worker-one")
    with pytest.raises(ValueError, match="PRODUCTION_V11_WORKER_ADAPTER_REQUIRED"):
        service.claim(job.production_job_id, "worker-one")
    assert db.scalar("SELECT COUNT(*) FROM production_attempts WHERE production_task_id=?",
                     (task_id,)) == 1


def test_unknown_prompt_and_crash_replay_do_not_allocate_attempt(case):
    db, _, service, job, plan, _ = case
    task_id = plan.tasks[0].production_task_id
    _attempt(db, job.production_job_id, task_id, 1, "worker-one", "committed-prompt")
    db.execute(
        "UPDATE production_tasks SET status='Running',attempt_count=1,comfy_prompt_id=? "
        "WHERE production_task_id=?", ("unrecognized-prompt", task_id),
    )
    with pytest.raises(ValueError, match="PRODUCTION_V11_PROMPT_UNVERIFIED"):
        service._audit_v11_core_before_lease(job.production_job_id, "worker-one")
    db.execute("UPDATE production_tasks SET comfy_prompt_id=? WHERE production_task_id=?",
               ("committed-prompt", task_id))
    service._audit_v11_core_before_lease(job.production_job_id, "worker-one")
    # ── Core-local history consistency alone is never sufficient for GPU reclaim. ──
    with pytest.raises(ValueError, match="PRODUCTION_V11_WORKER_ADAPTER_REQUIRED"):
        service.claim(job.production_job_id, "worker-one")
    assert db.scalar("SELECT COUNT(*) FROM production_attempts WHERE production_task_id=?",
                     (task_id,)) == 1


def test_unbound_attempt2_requires_same_executor_and_exact_prior_failure(case):
    db, _, service, job, plan, _ = case
    task_id = plan.tasks[0].production_task_id
    _attempt(db, job.production_job_id, task_id, 1, "worker-one", "previous-prompt",
             status="Failed", failure="COMFY_RETRYABLE_LOCAL_FAILURE")
    _attempt(db, job.production_job_id, task_id, 2, "worker-one")
    db.execute("UPDATE production_tasks SET status='Running',attempt_count=2,comfy_prompt_id=NULL "
               "WHERE production_task_id=?", (task_id,))
    with pytest.raises(ValueError, match="PRODUCTION_V11_UNBOUND_POST_UNVERIFIED"):
        service._audit_v11_core_before_lease(job.production_job_id, "wrong-worker")
    service._audit_v11_core_before_lease(job.production_job_id, "worker-one")
    with pytest.raises(ValueError, match="PRODUCTION_V11_WORKER_ADAPTER_REQUIRED"):
        service.claim(job.production_job_id, "worker-one")
    db.execute("UPDATE production_attempts SET failure_code='UNKNOWN' WHERE production_task_id=? "
               "AND attempt_number=1", (task_id,))
    with pytest.raises(ValueError, match="PRODUCTION_V11_UNBOUND_POST_UNVERIFIED"):
        service._audit_v11_core_before_lease(job.production_job_id, "worker-one")
    assert db.scalar("SELECT COUNT(*) FROM production_attempts WHERE production_task_id=?",
                     (task_id,)) == 2


def test_forged_active_lease_cannot_reserve_bind_complete_or_fail(case):
    db, _, service, job, plan, _ = case
    token = "synthetic-lease-token-not-real"
    executor = "forged-worker"
    task_id = plan.tasks[0].production_task_id
    db.execute(
        "UPDATE production_jobs SET lease_executor_id=?,lease_token_digest=?,lease_expires_at=? "
        "WHERE production_job_id=?",
        (executor, hashlib.sha256(token.encode()).hexdigest(),
         (datetime.now(UTC) + timedelta(hours=1)).isoformat(), job.production_job_id),
    )
    with pytest.raises(ValueError, match="PRODUCTION_V11_WORKER_ADAPTER_REQUIRED"):
        service.repository.heartbeat(job.production_job_id, executor, token)
    with pytest.raises(ValueError, match="PRODUCTION_V11_WORKER_ADAPTER_REQUIRED"):
        service.heartbeat(job.production_job_id, ProductionHeartbeatRequest(
            executor_id=executor, lease_token=token))
    with pytest.raises(ValueError, match="PRODUCTION_V11_WORKER_ADAPTER_REQUIRED"):
        service.mark_attempt(job.production_job_id, task_id, ProductionTaskAttemptRequest(
            executor_id=executor, lease_token=token, comfy_prompt_id=None))
    with pytest.raises(ValueError, match="PRODUCTION_V11_WORKER_ADAPTER_REQUIRED"):
        reserve_or_bind_attempt(
            service.repository, production_job_id=job.production_job_id,
            production_task_id=task_id, executor_id=executor, lease_token=token,
            comfy_prompt_id="fabricated-prompt")
    with pytest.raises(ValueError, match="PRODUCTION_V11_WORKER_ADAPTER_REQUIRED"):
        service.repository.mark_task_attempt(
            job.production_job_id, task_id, executor, token, None)
    commit = ProductionTaskCommitRequest(
        executor_id=executor, lease_token=token, comfy_prompt_id="fabricated-prompt",
        output_relpath="PicotooPet/output/fake.webm", output_sha256="d" * 64,
        output_bytes=1234, mime_type="video/webm", width=832, height=480,
        frame_count=81, fps=24,
    )
    with pytest.raises(ValueError, match="PRODUCTION_V11_WORKER_ADAPTER_REQUIRED"):
        service.repository.commit_task_result(job.production_job_id, task_id, commit)
    with pytest.raises(ValueError, match="PRODUCTION_V11_WORKER_ADAPTER_REQUIRED"):
        service.commit_task(job.production_job_id, task_id, commit)
    failed = ProductionTaskFailureRequest(
        executor_id=executor, lease_token=token, comfy_prompt_id=None,
        failure_code="SYNTHETIC_FAILURE",
    )
    with pytest.raises(ValueError, match="PRODUCTION_V11_WORKER_ADAPTER_REQUIRED"):
        fail_task_durably(service.repository, production_job_id=job.production_job_id,
                          production_task_id=task_id, request=failed)
    with pytest.raises(ValueError, match="PRODUCTION_V11_WORKER_ADAPTER_REQUIRED"):
        service.fail_task(job.production_job_id, task_id, failed)
    assert db.scalar("SELECT COUNT(*) FROM production_attempts WHERE production_job_id=?",
                     (job.production_job_id,)) == 0
    assert all(task.attempt_count == 0 for task in service.repository.list_tasks(job.production_job_id))
    assert service.repository.get_job(job.production_job_id).status.value == "Planned"


def test_audit_observes_approvals_under_single_sqlite_immediate_transaction(case, monkeypatch):
    db, _, service, job, _, _ = case
    from picotoopet_core.production import service as service_module

    observed = []
    original = service_module.verify_persisted_reference_approval

    def checked(database, reference):
        # ── Approval must not be a pre-lease stale read outside SQLite transaction. ──
        observed.append(database.connection.in_transaction)
        return original(database, reference)

    monkeypatch.setattr(service_module, "verify_persisted_reference_approval", checked)
    service._audit_v11_core_before_lease(job.production_job_id, "worker-one")
    assert observed == [True, True]
    _assert_no_execution(db, job.production_job_id)
