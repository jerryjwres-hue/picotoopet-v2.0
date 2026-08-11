"""Durable reserve/bind semantics for local ComfyUI attempts."""

from __future__ import annotations

from datetime import UTC, datetime

from .models import ProductionTaskRecord, ProductionTaskStatus
from .repository import ProductionRepository


def _now() -> str:
    # ── Attempt facts use the same UTC ISO representation as the repository ─
    return datetime.now(UTC).isoformat()


def reserve_or_bind_attempt(
    repository: ProductionRepository,
    *,
    production_job_id: str,
    production_task_id: str,
    executor_id: str,
    lease_token: str,
    comfy_prompt_id: str | None,
) -> ProductionTaskRecord:
    """Reserve GPU work before submit, then bind the returned prompt id without consuming another attempt."""

    # ── Lease validation remains centralized in the durable repository ──────
    repository._require_lease(production_job_id, executor_id, lease_token)  # noqa: SLF001
    task = repository.get_task(production_job_id, production_task_id)
    if task.status is ProductionTaskStatus.SUCCEEDED:
        return task
    if task.execution_disposition.value != "Executable":
        raise ValueError("PRODUCTION_TASK_NOT_EXECUTABLE")

    current = None
    if task.attempt_count > 0:
        current = repository.database.fetchone(
            "SELECT * FROM production_attempts WHERE production_task_id=? AND attempt_number=?",
            (production_task_id, task.attempt_count),
        )

    # ── Running + unbound attempt means Comfy submission was reserved first ─
    if task.status is ProductionTaskStatus.RUNNING and current is not None:
        current_prompt_id = current["comfy_prompt_id"]
        if current_prompt_id is None:
            if comfy_prompt_id is None:
                # ── Retried HTTP reservation is idempotent ──────────────────
                return task
            timestamp = _now()
            with repository.database.transaction() as connection:
                connection.execute(
                    "UPDATE production_attempts SET comfy_prompt_id=? "
                    "WHERE production_task_id=? AND attempt_number=? AND comfy_prompt_id IS NULL",
                    (comfy_prompt_id, production_task_id, task.attempt_count),
                )
                connection.execute(
                    "UPDATE production_tasks SET comfy_prompt_id=?,updated_at=? WHERE production_task_id=?",
                    (comfy_prompt_id, timestamp, production_task_id),
                )
            return repository.get_task(production_job_id, production_task_id)

        if comfy_prompt_id == current_prompt_id:
            # ── Replayed prompt binding is idempotent ────────────────────────
            return task
        if comfy_prompt_id is not None:
            raise ValueError("PRODUCTION_PROMPT_ID_CONFLICT")

        # ── A new null reservation after a bound Running attempt means the
        #    prior local render failed retryably. Close it before retry #2. ──
        if task.attempt_count >= repository.MAX_ATTEMPTS_PER_TASK:
            raise ValueError("PRODUCTION_ATTEMPT_BUDGET_EXHAUSTED")
        timestamp = _now()
        repository.database.execute(
            "UPDATE production_attempts SET status='Failed',finished_at=?,failure_code=? "
            "WHERE production_task_id=? AND attempt_number=? AND status='Running'",
            (
                timestamp,
                "COMFY_RETRYABLE_LOCAL_FAILURE",
                production_task_id,
                task.attempt_count,
            ),
        )
        repository.database.execute(
            "UPDATE production_tasks SET status=?,comfy_prompt_id=NULL,updated_at=? WHERE production_task_id=?",
            (ProductionTaskStatus.READY.value, timestamp, production_task_id),
        )
        task = repository.get_task(production_job_id, production_task_id)

    # ── A prompt id may only bind a Core-reserved attempt, never create one ─
    if comfy_prompt_id is not None:
        raise ValueError("PRODUCTION_ATTEMPT_RESERVATION_REQUIRED")

    return repository.mark_task_attempt(
        production_job_id,
        production_task_id,
        executor_id,
        lease_token,
        None,
    )
