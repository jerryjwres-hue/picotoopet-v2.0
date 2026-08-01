"""运行状态和审计完整性接口。"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request

from picotoopet_core.audit.verifier import verify_audit_chain
from picotoopet_core.security.auth import require_auth

router = APIRouter(dependencies=[Depends(require_auth)])


@router.get("/status")
def status(request: Request) -> dict[str, object]:
    """返回队列和服务状态，不暴露令牌或任意文件路径。"""

    database = request.app.state.services.database
    rows = database.fetchall(
        "SELECT status, COUNT(*) AS count FROM tasks GROUP BY status ORDER BY status"
    )
    health_rows = database.fetchall(
        "SELECT service_name, status, details_json, checked_at FROM service_health "
        "ORDER BY service_name"
    )
    return {
        "task_counts": {row["status"]: int(row["count"]) for row in rows},
        "services": {
            row["service_name"]: {
                "status": row["status"],
                "details": json.loads(row["details_json"]),
                "checked_at": row["checked_at"],
            }
            for row in health_rows
        },
    }


@router.get("/audit/verify")
def audit_verify(request: Request) -> dict[str, object]:
    """验证追加式审计哈希链。"""

    result = verify_audit_chain(request.app.state.services.database)
    return {
        "valid": result.valid,
        "checked_events": result.checked_events,
        "failed_audit_id": result.failed_audit_id,
    }


@router.get("/audit/events")
def audit_events(request: Request, limit: int = 100) -> list[dict[str, object]]:
    """读取最近脱敏审计事件。"""

    bounded = max(1, min(limit, 500))
    rows = request.app.state.services.database.fetchall(
        "SELECT * FROM audit_events ORDER BY rowid DESC LIMIT ?",
        (bounded,),
    )
    return [
        {
            "audit_id": row["audit_id"],
            "trace_id": row["trace_id"],
            "actor_type": row["actor_type"],
            "actor_id": row["actor_id"],
            "action": row["action"],
            "resource_type": row["resource_type"],
            "resource_id": row["resource_id"],
            "decision": row["decision"],
            "reason_code": row["reason_code"],
            "details": json.loads(row["details_redacted_json"]),
            "event_hash": row["event_hash"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]
