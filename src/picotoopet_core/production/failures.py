"""Durable terminal failure convergence for local production attempts."""

from __future__ import annotations

from datetime import UTC, datetime

from .models import ProductionTaskFailureRequest, ProductionTaskRecord, ProductionTaskStatus
from .repository import ProductionRepository


def fail_task_durably(
    repository: ProductionRepository,
    *,
    production_job_id: str,
    production_task_id: str,
    request: ProductionTaskFailureRequest,
) -> ProductionTaskRecord:
    """Converge the active task, attempt and job to Failed under one valid lease."""

    # ── Failure writes require the same active lease as success commits ─────
    repository._require_lease(  # noqa: SLF001
        production_job_id,
        request.executor_id,
        request.lease_token,
    )
    task = repository.get_task(production_job_id, production_task_id)
    if task.status is ProductionTaskStatus.SUCCEEDED:
        raise ValueError("PRODUCTION_TASK_ALREADY_SUCCEEDED")
    if task.status is ProductionTaskStatus.FAILED:
        if task.failure_code == request.failure_code:
            return task
        raise ValueError("PRODUCTION_TASK_FAILURE_CONFLICT")
    if task.attempt_count < 1:
        raise ValueError("PRODUCTION_ATTEMPT_REQUIRED")
    if request.comfy_prompt_id is not None and task.comfy_prompt_id not in {None, request.comfy_prompt_id}:
        raise ValueError("PRODUCTION_PROMPT_ID_CONFLICT")

    timestamp = datetime.now(UTC).isoformat()
    with repository.database.transaction() as connection:
        # ── The current attempt carries the same terminal failure evidence ──
        connection.execute(
            "UPDATE production_attempts SET status='Failed',comfy_prompt_id=COALESCE(comfy_prompt_id,?),"
            "failure_code=?,error_message=?,finished_at=? "
            "WHERE production_task_id=? AND attempt_number=?",
            (
                request.comfy_prompt_id,
                request.failure_code,
                request.error_message,
                timestamp,
                production_task_id,
                task.attempt_count,
            ),
        )
        # ── Task state is terminal and cannot be confused with user cancel ──
        connection.execute(
            "UPDATE production_tasks SET status=?,comfy_prompt_id=COALESCE(comfy_prompt_id,?),"
            "failure_code=?,error_message=?,updated_at=?,finished_at=? "
            "WHERE production_job_id=? AND production_task_id=?",
            (
                ProductionTaskStatus.FAILED.value,
                request.comfy_prompt_id,
                request.failure_code,
                request.error_message,
                timestamp,
                timestamp,
                production_job_id,
                production_task_id,
            ),
        )
        # ── Job failure clears executor authority immediately and durably ───
        connection.execute(
            "UPDATE production_jobs SET status='Failed',failure_code=?,error_message=?,updated_at=?,finished_at=?,"
            "lease_executor_id=NULL,lease_token_digest=NULL,lease_expires_at=NULL "
            "WHERE production_job_id=?",
            (
                request.failure_code,
                request.error_message,
                timestamp,
                timestamp,
                production_job_id,
            ),
        )
    return repository.get_task(production_job_id, production_task_id)
