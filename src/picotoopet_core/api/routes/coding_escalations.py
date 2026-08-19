"""Read-only Frugal coding escalation decision API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from picotoopet_core.api.errors import ApiError
from picotoopet_core.deep_ai.frugal_repository import FrugalDecisionRecord
from picotoopet_core.security.auth import require_auth

router = APIRouter(dependencies=[Depends(require_auth)])


@router.get(
    "/coding-escalations/{goal_id}/decision",
    response_model=FrugalDecisionRecord,
)
def get_coding_escalation_decision(
    goal_id: str,
    request: Request,
) -> FrugalDecisionRecord:
    """Return the latest durable Core-owned decision without reconciling or spending."""

    try:
        return request.app.state.services.coding_escalation.decisions.latest_for_goal(goal_id)
    except KeyError as error:
        raise ApiError(
            status_code=404,
            code="CODING_ESCALATION_NOT_FOUND",
            message="Coding escalation decision 不存在。",
            retryable=False,
        ) from error
