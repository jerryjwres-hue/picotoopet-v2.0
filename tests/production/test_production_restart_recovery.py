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
from picotoopet_core.production.service import ProductionService


def _repository(tmp_path: Path) -> ProductionRepository:
    # ── Durable database for restart/reclaim behavior ───────────────────────
    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    return ProductionRepository(database)


def _plan(job_id: str, package_id: str) -> ProductionPlan:
    # ── Two deterministic executable shots expose partial-resume behavior ───
    tasks = []
    for order in (1, 2):
        tasks.append(
            ProductionTaskPlan(
                production_task_id=str(uuid4()),
                shot_id=f"shot-{order:03d}",
                order=order,
                render_intent="GENERATIVE_VIDEO",
                execution_disposition="Executable",
                workflow_id="comfy.wan22.ti2v5b.t2v.v1",
                positive_prompt=f"compact pet dryer demonstration {order}",
                negative_prompt_policy_id="wan22.safe-negative.v1",
                seed=1233 + order,
                width=832,
                height=480,
                fps=24,
                frame_count=81,
            )
        )
    return ProductionPlan(
        schema_version="1.0",
        production_profile="production.comfyui.v1",
        production_job_id=job_id,
        creative_package_id=package_id,
        creative_package_digest="a" * 64,
        project_key="pet-dryer-us",
        tasks=tasks,
    )


def test_reclaim_returns_full_snapshots_but_only_unfinished_resume_plan(tmp_path: Path) -> None:
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
    first_task = plan.tasks[0]
    repository.mark_task_attempt(
        job.production_job_id,
        first_task.production_task_id,
        "pc-gpu-1",
        first_claim.lease_token,
        "prompt-1",
    )
    repository.commit_task_result(
        job.production_job_id,
        first_task.production_task_id,
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

    # ── Simulate Windows process loss and lease expiry before shot two ──────
    expired = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    repository.database.execute(
        "UPDATE production_jobs SET lease_expires_at=? WHERE production_job_id=?",
        (expired, job.production_job_id),
    )

    service = ProductionService(
        repository=repository,
        creative_repository=None,  # type: ignore[arg-type]  # claim path does not touch creative facts.
        store=None,                # type: ignore[arg-type]  # partial resume does not package yet.
    )
    resumed = service.claim(job.production_job_id, "pc-gpu-2")

    # ── Audit snapshot keeps both tasks, including immutable success evidence ─
    assert len(resumed.tasks) == 2
    completed = next(item for item in resumed.tasks if item.production_task_id == first_task.production_task_id)
    assert completed.status == "Succeeded"
    assert completed.output_sha256 == "c" * 64

    # ── Resume plan contains only unfinished shot two; shot one cannot rerender ─
    assert len(resumed.plan.tasks) == 1
    assert resumed.plan.tasks[0].production_task_id == plan.tasks[1].production_task_id
    assert resumed.plan.tasks[0].shot_id == "shot-002"
