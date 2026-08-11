from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from picotoopet_core.db.database import Database
from picotoopet_core.production.models import (
    ProductionPlan,
    ProductionTaskAttemptRequest,
    ProductionTaskPlan,
)
from picotoopet_core.production.repository import ProductionRepository
from picotoopet_core.production.service import ProductionService


def _service(tmp_path: Path) -> tuple[ProductionService, ProductionRepository, str, str]:
    # ── Durable Core fixture with one executable task ────────────────────────
    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    repository = ProductionRepository(database)
    package_id = str(uuid4())
    job = repository.create_job(
        production_job_id=str(uuid4()),
        creative_package_id=package_id,
        creative_package_digest="a" * 64,
        project_key="pet-dryer-us",
        production_profile="production.comfyui.v1",
        idempotency_key="attempt-reservation",
    )
    task = ProductionTaskPlan(
        production_task_id=str(uuid4()),
        shot_id="shot-001",
        order=1,
        render_intent="GENERATIVE_VIDEO",
        execution_disposition="Executable",
        workflow_id="comfy.wan22.ti2v5b.t2v.v1",
        positive_prompt="compact pet dryer demonstration",
        negative_prompt_policy_id="wan22.safe-negative.v1",
        seed=1234,
        width=832,
        height=480,
        fps=24,
        frame_count=81,
    )
    repository.save_plan(
        job.production_job_id,
        ProductionPlan(
            schema_version="1.0",
            production_profile="production.comfyui.v1",
            production_job_id=job.production_job_id,
            creative_package_id=package_id,
            creative_package_digest="a" * 64,
            project_key="pet-dryer-us",
            tasks=[task],
        ),
        "b" * 64,
    )
    service = ProductionService(
        repository=repository,
        creative_repository=None,  # type: ignore[arg-type]  # attempt path is production-only.
        store=None,                # type: ignore[arg-type]  # attempt path writes no package.
    )
    return service, repository, job.production_job_id, task.production_task_id


def test_reserve_then_bind_prompt_id_consumes_only_one_attempt(tmp_path: Path) -> None:
    service, repository, job_id, task_id = _service(tmp_path)
    claim = service.claim(job_id, "pc-gpu-1")

    reserved = service.mark_attempt(
        job_id,
        task_id,
        ProductionTaskAttemptRequest(
            executor_id="pc-gpu-1",
            lease_token=claim.lease_token,
            comfy_prompt_id=None,
        ),
    )
    assert reserved.attempt_count == 1
    assert reserved.comfy_prompt_id is None

    bound = service.mark_attempt(
        job_id,
        task_id,
        ProductionTaskAttemptRequest(
            executor_id="pc-gpu-1",
            lease_token=claim.lease_token,
            comfy_prompt_id="prompt-1",
        ),
    )
    assert bound.attempt_count == 1
    assert bound.comfy_prompt_id == "prompt-1"
    assert repository.database.scalar(
        "SELECT COUNT(*) FROM production_attempts WHERE production_task_id=?",
        (task_id,),
    ) == 1
    assert repository.database.scalar(
        "SELECT comfy_prompt_id FROM production_attempts WHERE production_task_id=? AND attempt_number=1",
        (task_id,),
    ) == "prompt-1"
