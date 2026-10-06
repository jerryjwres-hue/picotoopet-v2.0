from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from picotoopet_core.db.database import Database
from picotoopet_core.production.models import (
    ProductionPlan,
    ProductionTaskAttemptRequest,
    ProductionTaskPlan,
)
from picotoopet_core.production.repository import ProductionRepository
from picotoopet_core.production.service import ProductionService


def _service(
    tmp_path: Path,
    *,
    local_media: bool = False,
) -> tuple[ProductionService, ProductionRepository, str, str]:
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
    task_payload: dict[str, object] = dict(
        production_task_id=str(uuid4()),
        shot_id="shot-001",
        order=1,
        render_intent="TEXT_CARD" if local_media else "GENERATIVE_VIDEO",
        execution_disposition="Executable",
        execution_backend="local_media" if local_media else "comfy",
        execution_profile_id=(
            "production.local.text-card.v1"
            if local_media
            else "comfy.wan22.ti2v5b.t2v.v1"
        ),
        workflow_id=None if local_media else "comfy.wan22.ti2v5b.t2v.v1",
        local_media=(
            {
                "text_digest": "f65fb5a5c36901382688e08b4211c85d7bec28acd61049fef5e2e2e24c1eec1f",
                "text_content": "Save time with gentle airflow.",
                "text_profile_id": "production.local.text-card.v1",
            }
            if local_media
            else None
        ),
        positive_prompt="compact pet dryer demonstration",
        negative_prompt_policy_id="wan22.safe-negative.v1",
        seed=1234,
        width=832,
        height=480,
        fps=24,
        frame_count=81,
    )
    task = ProductionTaskPlan.model_validate(task_payload)
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
        "SELECT comfy_prompt_id FROM production_attempts "
        "WHERE production_task_id=? AND attempt_number=1",
        (task_id,),
    ) == "prompt-1"


def test_local_media_null_prompt_reservations_use_two_attempt_budget(tmp_path: Path) -> None:
    service, _repository, job_id, task_id = _service(tmp_path, local_media=True)
    claim = service.claim(job_id, "pc-gpu-1")
    request = ProductionTaskAttemptRequest(
        executor_id="pc-gpu-1",
        lease_token=claim.lease_token,
        comfy_prompt_id=None,
    )

    first = service.mark_attempt(job_id, task_id, request)
    second = service.mark_attempt(job_id, task_id, request)

    assert first.attempt_count == 1
    assert first.comfy_prompt_id is None
    assert second.attempt_count == 2
    assert second.comfy_prompt_id is None
    with pytest.raises(ValueError, match="PRODUCTION_ATTEMPT_BUDGET_EXHAUSTED"):
        service.mark_attempt(job_id, task_id, request)
