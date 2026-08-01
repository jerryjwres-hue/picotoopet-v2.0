"""公共健康和能力接口。"""

from fastapi import APIRouter, Request

from picotoopet_core import __version__
from picotoopet_core.api.contracts import (
    CapabilitiesResponse,
    ControlCenterCapabilities,
)

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


@router.get("/capabilities", response_model=CapabilitiesResponse)
def capabilities() -> CapabilitiesResponse:
    """返回显式能力；未实现功能保持关闭且不伪造运行状态。"""

    features = ControlCenterCapabilities()
    return CapabilitiesResponse(
        features=features,
        contract_versions={
            "connector": "1.0.0",
            "handoff_return": "1.0.0",
        },
        # 兼容 2.2 客户端仍读取的顶层字段。
        local_agent=features.local_agent,
        durable_queue=features.durable_queue,
        mcp_hub=features.mcp_hub,
        windows_worker=features.windows_worker,
    )
