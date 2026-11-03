"""B admission using the existing pinned keys, nonces and production lease.

The owner trusts their private Windows host's measurements and Journal. A real
Ed25519 signature proves possession of its locally paired software key only.
"""
from __future__ import annotations

import hashlib
import json
from contextlib import nullcontext
from datetime import UTC, datetime
from functools import wraps

from picotoopet_core.security.worker_pairing import PairedWorkerTrust, _verify_ed25519

from .reference_assets import verify_persisted_reference_approval
from .versioned_plan import ProductionPlanV11, WorkerWitnessV11


def pilot_atomic(operation):
    """Keep v1.1 guard/read/write in one transaction; leave v1.0 unchanged.

    The existing Database RLock owns the shared connection through nested
    repository calls. Another HTTP thread cannot borrow its active transaction.
    """
    @wraps(operation)
    def locked(owner, *args, **kwargs):
        repository = getattr(owner, "repository", owner)
        production_job_id = args[0] if args else kwargs["production_job_id"]
        database = repository.database
        if not isinstance(repository.plan_for(production_job_id), ProductionPlanV11):
            return operation(owner, *args, **kwargs)
        with database._lock:
            with (nullcontext(database.connection) if database.connection.in_transaction
                  else database.transaction()):
                return operation(owner, *args, **kwargs)
    return locked


def canonical_witness(witness: WorkerWitnessV11) -> str:
    return json.dumps(witness.model_dump(mode="json"), sort_keys=True,
                      separators=(",", ":"), ensure_ascii=False)


def audit_plan_locked(repository, production_job_id: str):
    """Frozen Plan/Task identities and current revocable approval, under lock."""
    connection = repository.database.connection
    if not connection.in_transaction:
        raise ValueError("PRODUCTION_V11_WITNESS_TRANSACTION_REQUIRED")
    job = repository.get_job(production_job_id)
    plan = repository.plan_for(production_job_id)
    if not isinstance(plan, ProductionPlanV11):
        raise ValueError("PRODUCTION_V11_PLAN_REQUIRED")
    digest = hashlib.sha256(json.dumps(plan.model_dump(mode="json"), sort_keys=True,
        separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    if (job.plan_digest != digest or job.production_job_id != plan.production_job_id
        or job.creative_package_id != plan.creative_package_id
        or job.creative_package_digest != plan.creative_package_digest
        or job.project_key != plan.project_key or job.production_profile != plan.production_profile):
        raise ValueError("PRODUCTION_V11_PLAN_IDENTITY_MISMATCH")
    rows = connection.execute("SELECT * FROM production_tasks WHERE production_job_id=?",
                              (production_job_id,)).fetchall()
    tasks = {row["production_task_id"]: repository._task(row) for row in rows}
    if len(rows) != len(plan.tasks) or len(tasks) != len(plan.tasks):
        raise ValueError("PRODUCTION_V11_TASK_COVERAGE_MISMATCH")
    for planned in plan.tasks:
        task = tasks.get(planned.production_task_id)
        if (task is None or task.task_plan != planned or task.production_job_id != production_job_id
            or task.shot_id != planned.shot_id or task.order != planned.order
            or task.render_intent != planned.render_intent
            or task.execution_disposition != planned.execution_disposition
            or task.workflow_id != planned.workflow_id):
            raise ValueError("PRODUCTION_V11_TASK_SNAPSHOT_MISMATCH")
        if planned.reference_asset is not None:
            verify_persisted_reference_approval(repository.database, planned.reference_asset)
    return job, plan, tasks


def require_b_key_locked(connection, key_id: str, executor_id: str):
    key = connection.execute("SELECT * FROM production_worker_keys WHERE key_id=?", (key_id,)).fetchone()
    if (key is None or key["executor_id"] != executor_id or key["revoked_at"] is not None
        or key["trust_model"] != PairedWorkerTrust.OPERATOR_TRUSTED_PRIVATE_HOST_V1):
        raise ValueError("PRODUCTION_V11_WORKER_KEY_UNTRUSTED")
    return key


def admit_claim_locked(repository, production_job_id: str, executor_id: str,
                       witness: WorkerWitnessV11) -> str:
    connection = repository.database.connection
    job, plan, tasks = audit_plan_locked(repository, production_job_id)
    if witness.production_job_id != production_job_id:
        raise ValueError("PRODUCTION_V11_WITNESS_JOB_MISMATCH")
    if witness.executor_id != executor_id:
        raise ValueError("PRODUCTION_V11_WORKER_KEY_UNTRUSTED")
    if witness.plan_digest != job.plan_digest:
        raise ValueError("PRODUCTION_V11_WITNESS_PLAN_MISMATCH")
    require_b_key_locked(connection, witness.worker_key_id, executor_id)
    # Different job challenges may be signed concurrently by the same private
    # host. Serialize admission under this BEGIN IMMEDIATE, independently of
    # the Windows exclusive GPU lock. Strict/v1.0 leases stay unchanged.
    if connection.execute(
        "SELECT 1 FROM production_jobs j JOIN production_worker_challenges c "
        "ON c.production_job_id=j.production_job_id "
        "AND c.admitted_lease_token_digest=j.lease_token_digest "
        "WHERE j.production_job_id<>? AND j.lease_executor_id=? "
        "AND j.lease_expires_at>? AND c.consumed_at IS NOT NULL LIMIT 1",
        (production_job_id, executor_id, datetime.now(UTC).isoformat()),
    ).fetchone() is not None:
        raise ValueError("PRODUCTION_V11_WORKER_LEASE_ACTIVE")
    # First pilot requires every shot to be untouched. A known old POST or even
    # an unbound reservation must stop for reconciliation, never create retry.
    if (witness.journal_state != "NO_PRIOR_POST"
        or connection.execute("SELECT 1 FROM production_attempts WHERE production_job_id=? LIMIT 1",
                              (production_job_id,)).fetchone() is not None
        or any(task.status.value != "Pending" or task.attempt_count != 0
               or task.comfy_prompt_id is not None for task in tasks.values())):
        raise ValueError("PRODUCTION_V11_WITNESS_POST_UNCERTAIN")
    expected = {task.production_task_id: task for task in plan.tasks if task.reference_asset is not None}
    received = {entry.production_task_id: entry for entry in witness.references}
    if expected.keys() != received.keys():
        raise ValueError("PRODUCTION_V11_WITNESS_TASK_COVERAGE_INVALID")
    for task_id, task in expected.items():
        ref = task.reference_asset
        entry = received[task_id]
        if (entry.shot_id != task.shot_id or entry.asset_id != ref.asset_id
            or entry.approval_id != ref.approval_id
            or entry.approval_request_digest != ref.approval_request_digest
            or entry.source_sha256 != ref.sha256 or entry.source_bytes != ref.bytes
            or entry.source_relative_path != ref.input_relative_path
            or entry.snapshot_sha256 != ref.sha256 or entry.snapshot_bytes != ref.bytes):
            raise ValueError("PRODUCTION_V11_WITNESS_ASSET_MISMATCH")
        if (entry.snapshot_receipt_sha256 == "0" * 64 or entry.graph_digest == "0" * 64
            or not entry.snapshot_relative_path.startswith("PicotooPet/")
            or any(part in {"", ".", ".."} for part in entry.snapshot_relative_path.split("/"))):
            raise ValueError("PRODUCTION_V11_WITNESS_SNAPSHOT_INVALID")
    PairedWorkerTrust(repository.database).verify_locked(connection, witness, redeem=True)
    return canonical_witness(witness)


def require_admitted_lease_locked(repository, production_job_id: str) -> None:
    connection = repository.database.connection
    if not connection.in_transaction:
        # Keep historical expected-deny code for legacy callers, never permit
        # proof checks that can be separated from the mutation transaction.
        raise ValueError("PRODUCTION_V11_WORKER_ADAPTER_REQUIRED")
    job, plan, _ = audit_plan_locked(repository, production_job_id)
    lease = connection.execute("SELECT lease_token_digest FROM production_jobs WHERE production_job_id=?",
                               (production_job_id,)).fetchone()[0]
    row = connection.execute(
        "SELECT * FROM production_worker_challenges WHERE production_job_id=? "
        "AND admitted_lease_token_digest=? AND consumed_at IS NOT NULL",
        (production_job_id, lease),
    ).fetchone()
    if (row is None or job.status.value not in {"Claimed", "Rendering"}
        or not job.lease_expires_at or job.lease_expires_at <= datetime.now(UTC)
        or row["executor_id"] != job.lease_executor_id or row["plan_digest"] != job.plan_digest):
        raise ValueError("PRODUCTION_V11_WORKER_ADAPTER_REQUIRED")
    payload = row["admitted_witness_json"]
    if not payload or hashlib.sha256(payload.encode()).hexdigest() != row["admitted_witness_sha256"]:
        raise ValueError("PRODUCTION_V11_WORKER_ADAPTER_REQUIRED")
    witness = WorkerWitnessV11.model_validate_json(payload)
    if (witness.production_job_id != production_job_id or witness.plan_digest != job.plan_digest
        or witness.executor_id != job.lease_executor_id or witness.worker_key_id != row["key_id"]
        or hashlib.sha256(witness.nonce.encode()).hexdigest() != row["nonce_digest"]):
        raise ValueError("PRODUCTION_V11_WORKER_ADAPTER_REQUIRED")
    key = require_b_key_locked(connection, witness.worker_key_id, witness.executor_id)
    _verify_ed25519(key["public_key_hex"], witness.signature, witness.signed_payload())
