from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from picotoopet_core.db.database import Database
from picotoopet_core.production.models import (
    ProductionPlan,
    ProductionTaskCommitRequest,
    ProductionTaskPlan,
)
from picotoopet_core.production.repository import ProductionRepository


def _repository(tmp_path: Path) -> ProductionRepository:
    # ── Durable database for restart/reclaim behavior ───────────────────────
    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    return ProductionRepository(database)


def _plan(job_id: str, package_id: str) -> ProductionPlan:
    # ── Single deterministic executable shot ────────────────────────────────
    return ProductionPlan(
        schema_version="1.0",
        production_profile="production.comfyui.v1",
        production_job_id=job_id,
        creative_package_id=package_id,
        creative_package_digest="a" * 64,
        project_key="pet-dryer-us",
        tasks=[
            ProductionTaskPlan(
                production_task_id=str(uuid4()),
                shot_id="shot-001",
                order=1,
                render_intent="GENERATIVE_VIDEO",
                execution_disposition="Executable",
                workflow_id="comfy.wan22.ti2v5b.t2v.v1",
                positive_prompt="compact pet dryer in a clean grooming area",
                negative_prompt_policy_id="wan22.safe-negative.v1",
                seed=1234,
                width=832,
                height=480,
                fps=24,
                frame_count=81,
            )
        ],
    )


def test_reclaim_returns_durable_task_snapshot_so_succeeded_shot_is_not_rerendered(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    package_id = str(uuid4())
    job = repository.create_job(
        production_job_id=str(uuid4()),
        creative_package_id=package_id,
        creative_package_digest="a" * 64,
        project_key="pet-dryer-us",
        production_profile="production.comfyui.v1",
        idempotency_key="restart-recovery",
    )
    plan = _plan(job.production_job_id, package_id)
    repository.save_plan(job.production_job_id, plan, "b" * 64)

    first_claim = repository.claim_job(job.production_job_id, "pc-gpu-1", lease_seconds=120)
    task_id = plan.tasks[0].production_task_id
    repository.mark_task_attempt(
        job.production_job_id,
        task_id,
        "pc-gpu-1",
        first_claim.lease_token,
        "prompt-1",
    )
    repository.commit_task_result(
        job.production_job_id,
        task_id,
        ProductionTaskCommitRequest(
            executor_id="pc-gpu-1",
            lease_token=first_claim.lease_token,
            comfy_prompt_id="prompt-1",
            output_relpath="PicotooPet/job/shot-001.webm",
            output_sha256="c" * 64,
            output_bytes=1024,
            mime_type="video/webm",
            width=832,
            height=480,
            frame_count=81,
            fps=24,
        ),
    )

    # ── Simulate process loss and lease expiry before Windows resumes ───────
    expired = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    repository.database.execute(
        "UPDATE production_jobs SET lease_expires_at=? WHERE production_job_id=?",
        (expired, job.production_job_id),
    )

    resumed = repository.claim_job(job.production_job_id, "pc-gpu-2", lease_seconds=120)

    assert len(resumed.tasks) == 1
    assert resumed.tasks[0].production_task_id == task_id
    assert resumed.tasks[0].status == "Succeeded"
    assert resumed.tasks[0].output_sha256 == "c" * 64
