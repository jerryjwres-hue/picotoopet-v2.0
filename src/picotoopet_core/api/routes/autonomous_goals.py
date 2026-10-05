"""Authenticated product-facing Goal Center routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Query, Request, status
from fastapi.responses import FileResponse, PlainTextResponse

from picotoopet_core.api.errors import ApiError
from picotoopet_core.autonomous.goal_handoff_access import (
    GoalHandoffAccess,
    GoalHandoffMetadata,
    HandoffAccessError,
)
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


def _handoff_access(request: Request) -> GoalHandoffAccess:
    services = request.app.state.services
    return GoalHandoffAccess(
        paths=services.settings.paths,
        goals=services.autonomous_goals,
        workflows=services.workflows,
        result_records=services.result_records,
        result_store=services.results,
    )


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


@router.get(
    "/autonomous/goals/{goal_id}/handoff",
    response_model=GoalHandoffMetadata,
)
def get_goal_handoff(goal_id: str, request: Request) -> GoalHandoffMetadata:
    try:
        return _handoff_access(request).metadata(goal_id)
    except HandoffAccessError as error:
        _raise_handoff_api_error(error)


@router.get("/autonomous/goals/{goal_id}/handoff/download", response_class=FileResponse)
def download_goal_handoff(goal_id: str, request: Request) -> FileResponse:
    try:
        access = _handoff_access(request)
        metadata = access.metadata(goal_id)
        package = access.verified_package(goal_id)
        return FileResponse(
            package,
            media_type="application/zip",
            filename=metadata.package_name,
        )
    except HandoffAccessError as error:
        _raise_handoff_api_error(error)


@router.get("/autonomous/goals/{goal_id}/handoff/prompt", response_class=PlainTextResponse)
def get_goal_handoff_prompt(goal_id: str, request: Request) -> PlainTextResponse:
    try:
        prompt = _handoff_access(request).fixed_prompt(goal_id)
        return PlainTextResponse(prompt, media_type="text/plain; charset=utf-8")
    except HandoffAccessError as error:
        _raise_handoff_api_error(error)


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


def _raise_handoff_api_error(error: HandoffAccessError) -> None:
    missing = str(error) == "goal not found"
    raise ApiError(
        status_code=404 if missing else 409,
        code="AUTONOMOUS_GOAL_NOT_FOUND" if missing else "AUTONOMOUS_HANDOFF_NOT_READY",
        message="未找到对应目标。" if missing else "交接包尚未完成或未通过完整性验证。",
        retryable=not missing,
    ) from error
