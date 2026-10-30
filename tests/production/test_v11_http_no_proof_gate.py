"""HTTP boundary regression: no Windows witness means no Core v1.1 GPU authority.

A persisted user approval alone does not prove a Windows snapshot or old Comfy state.
All requests travel through the actual FastAPI route and real SQLite repository.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from picotoopet_core.api.errors import install_error_handlers
from picotoopet_core.api.routes import production
from picotoopet_core.production.versioned_plan import ProductionJobCreateV11Request
from picotoopet_core.security.auth import require_auth

# Reuse the actual persisted approval/plan fixture, not a forged permission boolean.
from test_reference_registration_api import (  # noqa: E402
    PACKAGE,
    _approve_batch,
    _v11_service,
    state as reference_state,
)


@pytest.fixture()
def case(reference_state):
    db, registration, _, _, _ = reference_state
    batch = _approve_batch(reference_state)
    service = _v11_service(reference_state)
    job = service.create_job_v11(
        ProductionJobCreateV11Request(
            creative_package_id=PACKAGE,
            idempotency_key="controller-http-v11-no-windows-proof",
            approved_reference_ids=[batch.approval_id],
        )
    )
    plan = service.get_plan(job.production_job_id)
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(production.router, prefix="/api/v1")
    app.state.services = SimpleNamespace(production=service)
    app.dependency_overrides[require_auth] = lambda: None
    return db, registration, batch, job, plan, app


def _assert_never_claimed(db, job_id):
    row = db.fetchone(
        "SELECT lease_token_digest,lease_executor_id FROM production_jobs "
        "WHERE production_job_id=?",
        (job_id,),
    )
    assert row["lease_token_digest"] is None
    assert row["lease_executor_id"] is None
    assert db.scalar(
        "SELECT COUNT(*) FROM production_attempts WHERE production_job_id=?",
        (job_id,),
    ) == 0


def test_http_bearer_approved_v11_still_denies_every_gpu_mutation(case):
    db, _, _, job, plan, app = case
    root = f"/api/v1/production/jobs/{job.production_job_id}"
    task = next(t for t in plan.tasks if t.reference_asset is not None)
    task_root = f"{root}/tasks/{task.production_task_id}"
    lease = {"executor_id": "windows-production-test", "lease_token": "f" * 32}
    with TestClient(app) as client:
        # Read-only authorization proves Core approval, NOT Windows file bytes.
        auth = client.get(f"{task_root}/reference-authorization")
        assert auth.status_code == 200, auth.text
        assert auth.json()["plan_digest"] == job.plan_digest

        attempts = [
            (f"{root}/claim", {"executor_id": lease["executor_id"]}),
            (f"{root}/heartbeat", lease),
            (f"{task_root}/attempt", {**lease, "comfy_prompt_id": None}),
            (f"{task_root}/attempt", {**lease, "comfy_prompt_id": "fake-prompt"}),
            (
                f"{task_root}/failure",
                {**lease, "failure_code": "SYNTHETIC_FAILURE", "comfy_prompt_id": None},
            ),
            (
                f"{task_root}/result",
                {
                    **lease,
                    "comfy_prompt_id": "fake-prompt",
                    "output_relpath": "PicotooPet/output/fake.webm",
                    "output_sha256": "b" * 64,
                    "output_bytes": 1024,
                    "mime_type": "video/webm",
                    "width": task.width,
                    "height": task.height,
                    "frame_count": task.frame_count,
                    "fps": task.fps,
                },
            ),
        ]
        for url, request_body in attempts:
            response = client.post(url, json=request_body)
            assert response.status_code == 409, (url, response.text)
            assert response.json()["error"]["code"] == "PRODUCTION_V11_WORKER_ADAPTER_REQUIRED"
            _assert_never_claimed(db, job.production_job_id)

        # The same immutable plan must remain readable after every denied write.
        assert client.get(f"{root}/plan").json()["schema_version"] == "1.1"


def test_http_revocation_invalidates_readonly_approval_without_lease(case):
    db, registration, batch, job, plan, app = case
    root = f"/api/v1/production/jobs/{job.production_job_id}"
    task = next(t for t in plan.tasks if t.reference_asset is not None)
    with TestClient(app) as client:
        assert client.get(
            f"{root}/tasks/{task.production_task_id}/reference-authorization"
        ).status_code == 200
        registration.revoke(
            batch.approval_id,
            request_digest=batch.approval_request_digest,
            reason="revoked in synthetic HTTP fixture",
        )
        assert client.get(
            f"{root}/tasks/{task.production_task_id}/reference-authorization"
        ).status_code == 409
        assert client.post(
            f"{root}/claim", json={"executor_id": "windows-production-test"}
        ).status_code == 409
        _assert_never_claimed(db, job.production_job_id)
