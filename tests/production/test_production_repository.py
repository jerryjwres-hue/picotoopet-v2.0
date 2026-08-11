from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from picotoopet_core.db.database import Database
from picotoopet_core.production.models import (
    ProductionJobStatus,
    ProductionPlan,
    ProductionTaskCommitRequest,
    ProductionTaskPlan,
)
from picotoopet_core.production.repository import ProductionRepository


def _repository(tmp_path: Path) -> ProductionRepository:
    # ── Durable test database ────────────────────────────────────────────────
    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    return ProductionRepository(database)


def _plan(job_id: str, package_id: str) -> ProductionPlan:
    # ── Closed deterministic plan fixture ───────────────────────────────────
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
                positive_prompt="pet dryer; studio; rotating product; medium shot; soft light; blue; factual",
                negative_prompt_policy_id="wan22.safe-negative.v1",
                seed=1234,
                width=832,
                height=480,
                fps=24,
                frame_count=81,
            )
        ],
    )


def test_repository_is_idempotent_and_lease_is_single_owner(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    package_id = str(uuid4())
    job_id = str(uuid4())
    first = repository.create_job(
        production_job_id=job_id,
        creative_package_id=package_id,
        creative_package_digest="a" * 64,
        project_key="pet-dryer-us",
        production_profile="production.comfyui.v1",
        idempotency_key="production-demo",
    )
    second = repository.create_job(
        production_job_id=str(uuid4()),
        creative_package_id=package_id,
        creative_package_digest="a" * 64,
        project_key="pet-dryer-us",
        production_profile="production.comfyui.v1",
        idempotency_key="production-demo",
    )
    assert second.production_job_id == first.production_job_id

    plan = _plan(first.production_job_id, package_id)
    repository.save_plan(first.production_job_id, plan, "b" * 64)
    claim = repository.claim_job(first.production_job_id, "pc-gpu-1", lease_seconds=120)
    assert claim.executor_id == "pc-gpu-1"
    assert claim.lease_token
    with pytest.raises(ValueError, match="PRODUCTION_LEASE_ACTIVE"):
        repository.claim_job(first.production_job_id, "pc-gpu-2", lease_seconds=120)


def test_task_attempt_budget_and_success_commit_are_immutable(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    package_id = str(uuid4())
    job = repository.create_job(
        production_job_id=str(uuid4()),
        creative_package_id=package_id,
        creative_package_digest="a" * 64,
        project_key="pet-dryer-us",
        production_profile="production.comfyui.v1",
        idempotency_key="attempt-demo",
    )
    plan = _plan(job.production_job_id, package_id)
    repository.save_plan(job.production_job_id, plan, "b" * 64)
    claim = repository.claim_job(job.production_job_id, "pc-gpu-1", lease_seconds=120)
    task_id = plan.tasks[0].production_task_id

    repository.mark_task_attempt(job.production_job_id, task_id, "pc-gpu-1", claim.lease_token, "prompt-1")
    repository.mark_task_attempt(job.production_job_id, task_id, "pc-gpu-1", claim.lease_token, "prompt-2")
    with pytest.raises(ValueError, match="PRODUCTION_ATTEMPT_BUDGET_EXHAUSTED"):
        repository.mark_task_attempt(job.production_job_id, task_id, "pc-gpu-1", claim.lease_token, "prompt-3")

    request = ProductionTaskCommitRequest(
        executor_id="pc-gpu-1",
        lease_token=claim.lease_token,
        comfy_prompt_id="prompt-2",
        output_relpath="output/picotoopet/job/shot-001.webm",
        output_sha256="c" * 64,
        output_bytes=1024,
        mime_type="video/webm",
        width=832,
        height=480,
        frame_count=81,
        fps=24,
    )
    committed = repository.commit_task_result(job.production_job_id, task_id, request)
    assert committed.status == "Succeeded"
    same = repository.commit_task_result(job.production_job_id, task_id, request)
    assert same.output_sha256 == "c" * 64
    with pytest.raises(ValueError, match="PRODUCTION_TASK_RESULT_CONFLICT"):
        repository.commit_task_result(
            job.production_job_id,
            task_id,
            request.model_copy(update={"output_sha256": "d" * 64}),
        )
