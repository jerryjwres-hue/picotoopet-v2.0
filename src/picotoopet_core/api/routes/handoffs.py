"""Phase 10A Handoff 准备、预览和审批提交 REST 路由。"""

from fastapi import APIRouter, Depends, Header, Query, Request, status

from picotoopet_core.handoffs.models import (
    HandoffPrepareRequest,
    HandoffRecord,
    HandoffTemplate,
)
from picotoopet_core.security.auth import require_auth

router = APIRouter(dependencies=[Depends(require_auth)])


@router.get("/handoffs/templates", response_model=list[HandoffTemplate])
def list_handoff_templates(request: Request) -> list[HandoffTemplate]:
    """返回 Mac Core 发布的固定安全模板。"""

    return request.app.state.services.handoffs.templates()


@router.get("/handoffs", response_model=list[HandoffRecord])
def list_handoffs(
    request: Request,
    limit: int = Query(default=100, ge=1, le=100),
) -> list[HandoffRecord]:
    """返回最近的有界 Handoff 安全投影。"""

    return request.app.state.services.handoffs.list(limit=limit)


@router.post(
    "/handoffs/prepare",
    response_model=HandoffRecord,
    status_code=status.HTTP_201_CREATED,
)
def prepare_handoff(
    payload: HandoffPrepareRequest,
    request: Request,
    idempotency_key: str = Header(
        min_length=1,
        max_length=200,
        alias="Idempotency-Key",
    ),
) -> HandoffRecord:
    """幂等准备不执行 Provider 的确定性 Handoff 草稿。"""

    return request.app.state.services.handoffs.prepare(
        payload,
        idempotency_key=idempotency_key,
    )


@router.get("/handoffs/{handoff_id}", response_model=HandoffRecord)
def get_handoff(handoff_id: str, request: Request) -> HandoffRecord:
    """读取一个 Handoff 的固定安全投影。"""

    return request.app.state.services.handoffs.get(handoff_id)


@router.post(
    "/handoffs/{handoff_id}/submit-approval",
    response_model=HandoffRecord,
)
def submit_handoff_approval(
    handoff_id: str,
    request: Request,
    idempotency_key: str = Header(
        min_length=1,
        max_length=200,
        alias="Idempotency-Key",
    ),
) -> HandoffRecord:
    """把当前摘要幂等提交到现有 Approval Center。"""

    return request.app.state.services.handoffs.submit_for_approval(
        handoff_id,
        idempotency_key=idempotency_key,
    )
