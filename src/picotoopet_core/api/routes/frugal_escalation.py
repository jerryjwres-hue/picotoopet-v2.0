"""Read-only Core projection for frugal coding escalation decisions."""

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
def get_coding_escalation_decision(goal_id: str, request: Request) -> FrugalDecisionRecord:
    """Read the immutable Core decision without advancing approval, Usage, or execution state."""

    try:
        return request.app.state.services.coding_escalation.decisions.latest_for_goal(goal_id)
    except KeyError as error:
        raise ApiError(
            status_code=404,
            code="FRUGAL_DECISION_NOT_FOUND",
            message="未找到对应 Coding Escalation 决策。",
            retryable=False,
        ) from error
