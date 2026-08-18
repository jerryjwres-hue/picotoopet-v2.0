"""Authenticated product-facing Goal Center routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Query, Request, status

from picotoopet_core.api.errors import ApiError
from picotoopet_core.autonomous.goal_service import (
    GoalTemplate,
    HumanGoalRequest,
    HumanGoalService,
)
from picotoopet_core.autonomous.models import GoalRecord
from picotoopet_core.security.auth import require_auth

router = APIRouter(dependencies=[Depends(require_auth)])


def _service(request: Request) -> HumanGoalService:
    services = request.app.state.services
    return HumanGoalService(services.autonomous_goals, services.workflows)


@router.get("/autonomous/goals/templates", response_model=list[GoalTemplate])
def list_goal_templates(request: Request) -> list[GoalTemplate]:
    return _service(request).templates()


@router.post(
    "/autonomous/goals",
    response_model=GoalRecord,
    status_code=status.HTTP_201_CREATED,
)
def create_human_goal(
    payload: HumanGoalRequest,
    request: Request,
    idempotency_key: str = Header(
        min_length=1,
        max_length=200,
        alias="Idempotency-Key",
    ),
) -> GoalRecord:
    try:
        return _service(request).create(payload, idempotency_key=idempotency_key)
    except ValueError as error:
        raise ApiError(
            status_code=409,
            code="AUTONOMOUS_GOAL_CONFLICT",
            message=str(error),
            retryable=False,
        ) from error


@router.get("/autonomous/goals", response_model=list[GoalRecord])
def list_human_goals(
    request: Request,
    limit: int = Query(default=200, ge=1, le=500),
) -> list[GoalRecord]:
    return _service(request).list(limit=limit)


@router.get("/autonomous/goals/{goal_id}", response_model=GoalRecord)
def get_human_goal(goal_id: str, request: Request) -> GoalRecord:
    try:
        return _service(request).get(goal_id)
    except KeyError as error:
        raise ApiError(
            status_code=404,
            code="AUTONOMOUS_GOAL_NOT_FOUND",
            message="未找到对应目标。",
            retryable=False,
        ) from error
