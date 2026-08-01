"""人工审批 REST 路由。"""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from picotoopet_core.approvals.service import ApprovalGrant, ApprovalRecord
from picotoopet_core.security.auth import require_auth

router = APIRouter(dependencies=[Depends(require_auth)])


class ApprovalRequestBody(BaseModel):
    """审批创建参数。"""

    task_id: str
    approval_type: str
    scope: dict[str, object] = Field(default_factory=dict)
    expires_seconds: int = Field(default=600, ge=30, le=3600)


class ApprovalDecisionBody(BaseModel):
    """人工批准参数。"""

    token: str
    reason: str = Field(min_length=1)


@router.post("/approvals", response_model=ApprovalGrant)
def request_approval(payload: ApprovalRequestBody, request: Request) -> ApprovalGrant:
    """请求一次性人工批准。"""

    return request.app.state.services.approvals.request(
        task_id=payload.task_id,
        approval_type=payload.approval_type,
        scope=payload.scope,
        requested_by="api-device",
        expires_at=datetime.now(UTC) + timedelta(seconds=payload.expires_seconds),
    )


@router.post("/approvals/{approval_id}/approve", response_model=ApprovalRecord)
def approve(
    approval_id: str,
    payload: ApprovalDecisionBody,
    request: Request,
) -> ApprovalRecord:
    """消费一次性审批令牌。"""

    return request.app.state.services.approvals.approve(
        approval_id=approval_id,
        token=payload.token,
        resolved_by="owner",
        reason=payload.reason,
    )


@router.post("/approvals/{approval_id}/reject", response_model=ApprovalRecord)
def reject(
    approval_id: str,
    payload: ApprovalDecisionBody,
    request: Request,
) -> ApprovalRecord:
    """拒绝审批并取消对应等待任务。"""

    return request.app.state.services.approvals.reject(
        approval_id=approval_id,
        token=payload.token,
        resolved_by="owner",
        reason=payload.reason,
    )
