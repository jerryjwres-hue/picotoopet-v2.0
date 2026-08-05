"""人工审批 REST 路由。"""

from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Header, Query, Request
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
    """旧调用方使用的一次性令牌批准参数。"""

    token: str
    reason: str = Field(min_length=1, max_length=500)


class ControlCenterApprovalDecisionBody(BaseModel):
    """Windows 审批中心的摘要绑定决策。"""

    decision: Literal["approve", "reject"]
    request_digest: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    reason: str = Field(min_length=1, max_length=500)


@router.get("/approvals", response_model=list[ApprovalRecord])
def list_approvals(
    request: Request,
    limit: int = Query(default=200, ge=1, le=200),
) -> list[ApprovalRecord]:
    """返回审批中心有界快照，不暴露明文令牌、令牌哈希或任意原始路径。"""

    return request.app.state.services.approvals.list_for_control_center(limit=limit)


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


@router.post("/approvals/{approval_id}/decision", response_model=ApprovalRecord)
def decide_from_control_center(
    approval_id: str,
    payload: ControlCenterApprovalDecisionBody,
    request: Request,
    idempotency_key: str = Header(
        min_length=1,
        max_length=200,
        alias="Idempotency-Key",
    ),
) -> ApprovalRecord:
    """校验当前请求摘要后执行幂等批准或拒绝。"""

    record = request.app.state.services.approvals.decide_for_control_center(
        approval_id=approval_id,
        decision=payload.decision,
        request_digest=payload.request_digest,
        idempotency_key=idempotency_key,
        resolved_by="owner",
        reason=payload.reason,
    )
    request.app.state.services.handoffs.reconcile_approval(record)
    return record


@router.post("/approvals/{approval_id}/approve", response_model=ApprovalRecord)
def approve(
    approval_id: str,
    payload: ApprovalDecisionBody,
    request: Request,
) -> ApprovalRecord:
    """消费一次性审批令牌。"""

    record = request.app.state.services.approvals.approve(
        approval_id=approval_id,
        token=payload.token,
        resolved_by="owner",
        reason=payload.reason,
    )
    request.app.state.services.handoffs.reconcile_approval(record)
    return record


@router.post("/approvals/{approval_id}/reject", response_model=ApprovalRecord)
def reject(
    approval_id: str,
    payload: ApprovalDecisionBody,
    request: Request,
) -> ApprovalRecord:
    """拒绝审批并取消对应等待任务。"""

    record = request.app.state.services.approvals.reject(
        approval_id=approval_id,
        token=payload.token,
        resolved_by="owner",
        reason=payload.reason,
    )
    request.app.state.services.handoffs.reconcile_approval(record)
    return record
