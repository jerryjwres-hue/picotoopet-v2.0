"""公共健康和能力接口。"""

from fastapi import APIRouter, Request

from picotoopet_core import __version__

router = APIRouter()


@router.get("/health")
def health(request: Request) -> dict[str, object]:
    """提供不含秘密的轻量健康状态。"""

    database = request.app.state.services.database
    database_ok = database.scalar("SELECT 1") == 1
    return {
        "status": "ok" if database_ok else "degraded",
        "database": "ok" if database_ok else "error",
        "version": __version__,
    }


@router.get("/capabilities")
def capabilities() -> dict[str, object]:
    """列出当前纵向切片能力，不宣称 Windows Worker 已上线。"""

    return {
        "local_agent": True,
        "durable_queue": True,
        "mcp_hub": True,
        "windows_worker": False,
        "cloud_upload": "manual_approval_only",
    }
