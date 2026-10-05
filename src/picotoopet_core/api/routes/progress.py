"""Read-only Superpower v1.0 task-progress REST route."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from picotoopet_core.api.errors import ApiError
from picotoopet_core.progress.models import ProgressSnapshot
from picotoopet_core.progress.repository import ProgressRepository
from picotoopet_core.security.auth import require_auth

router = APIRouter(dependencies=[Depends(require_auth)])


@router.get("/tasks/{task_id}/progress", response_model=ProgressSnapshot)
def get_task_progress(task_id: str, request: Request) -> ProgressSnapshot:
    """Return only durable Core-owned progress; never estimate from elapsed time."""

    repository = ProgressRepository(request.app.state.services.database)
    try:
        return repository.snapshot(task_id, recent_limit=50)
    except KeyError as error:
        raise ApiError(
            status_code=404,
            code="TASK_NOT_FOUND",
            message="任务不存在。",
            retryable=False,
        ) from error
