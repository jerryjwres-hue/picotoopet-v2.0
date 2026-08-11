from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from picotoopet_core.db.database import Database
from picotoopet_core.production.models import (
    ProductionJobStatus,
    ProductionPlan,
    ProductionTaskPlan,
    ProductionTaskStatus,
)
from picotoopet_core.production.repository import ProductionRepository


def _repository(tmp_path: Path) -> ProductionRepository:
    # ── 每个状态合同使用独立 schema 13 durable database ──────────────────────
    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    return ProductionRepository(database)


def _plan(job_id: str, package_id: str) -> ProductionPlan:
    # ── 单 shot executable plan 足以冻结 Ready/Pending 初始语义 ──────────────
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
                positive_prompt="compact pet dryer product demonstration",
                negative_prompt_policy_id="wan22.safe-negative.v1",
                seed=1234,
                width=832,
                height=480,
                fps=24,
                frame_count=81,
            )
        ],
    )


def test_state_vocabulary_matches_frozen_20_1_design() -> None:
    # ── Job vocabulary includes explicit preflight/collecting lifecycle states ──
    job_values = {status.value for status in ProductionJobStatus}
    assert "Preflight" in job_values
    assert "Collecting" in job_values
    assert "Planned" not in job_values

    # ── Task lifecycle starts Pending; Ready is a Job state, not a Task state ───
    task_values = {status.value for status in ProductionTaskStatus}
    assert "Pending" in task_values
    assert "Ready" not in task_values


def test_saved_executable_plan_is_ready_with_pending_tasks(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    package_id = str(uuid4())
    job = repository.create_job(
        production_job_id=str(uuid4()),
        creative_package_id=package_id,
        creative_package_digest="a" * 64,
        project_key="pet-dryer-us",
        production_profile="production.comfyui.v1",
        idempotency_key="state-contract",
    )
    plan = _plan(job.production_job_id, package_id)

    repository.save_plan(job.production_job_id, plan, "b" * 64)

    # ── Plan 编译完成后 Job 可被 claim；不引入未冻结的 Planned 状态 ───────────
    saved = repository.get_job(job.production_job_id)
    assert saved.status is ProductionJobStatus.READY

    # ── 可执行 shot 在真正 attempt 前必须保持 Pending ───────────────────────
    tasks = repository.list_tasks(job.production_job_id)
    assert len(tasks) == 1
    assert tasks[0].status is ProductionTaskStatus.PENDING
