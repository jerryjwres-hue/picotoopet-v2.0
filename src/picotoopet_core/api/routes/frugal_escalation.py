"""Core-owned creation and read-only projection for frugal coding escalation."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from picotoopet_core.api.errors import ApiError
from picotoopet_core.deep_ai.frugal_repository import FrugalDecisionRecord
from picotoopet_core.providers.frugal_service import CodingEscalationPlan
from picotoopet_core.security.auth import require_auth

router = APIRouter(dependencies=[Depends(require_auth)])


class CodingEscalationCreateRequest(BaseModel):
    """Windows may submit only high-level coding intent; Core owns every authority field."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=120)
    objective: str = Field(min_length=1, max_length=1000)

    @field_validator("title", "objective")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        normalized = " ".join(value.replace("\r", "\n").split())
        if not normalized:
            raise ValueError("文本不能为空。")
        if any(ord(character) < 32 for character in normalized):
            raise ValueError("文本包含控制字符。")
        return normalized


@router.post(
    "/coding-escalations",
    response_model=CodingEscalationPlan,
    status_code=status.HTTP_201_CREATED,
)
def create_coding_escalation(
    body: CodingEscalationCreateRequest,
    request: Request,
    idempotency_key: str = Header(
        min_length=1,
        max_length=200,
        alias="Idempotency-Key",
    ),
) -> CodingEscalationPlan:
    """Persist one coding source fact and let Mac Core decide whether escalation is justified."""

    return request.app.state.services.coding_escalation.create_repository_maintenance_request(
        title=body.title,
        objective=body.objective,
        idempotency_key=idempotency_key,
    )


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
