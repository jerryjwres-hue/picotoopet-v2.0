"""结果元数据 REST 路由。"""

import json
from datetime import datetime

from fastapi import APIRouter, Depends, Request

from picotoopet_core.security.auth import require_auth

router = APIRouter(dependencies=[Depends(require_auth)])


@router.get("/results/{result_id}")
def get_result(result_id: str, request: Request) -> dict[str, object]:
    """读取结果清单，不直接暴露任意文件路径。"""

    row = request.app.state.services.database.fetchone(
        "SELECT * FROM results WHERE result_id = ?",
        (result_id,),
    )
    if row is None:
        raise KeyError(f"结果不存在：{result_id}")
    return {
        "result_id": row["result_id"],
        "project_id": row["project_id"],
        "task_id": row["task_id"],
        "result_type": row["result_type"],
        "object_hash": row["object_hash"],
        "manifest": json.loads(row["manifest_json"]),
        "schema_version": row["schema_version"],
        "created_at": datetime.fromisoformat(row["created_at"]),
    }
