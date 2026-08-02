"""Windows Control Center 的版本化公共契约。"""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ControlCenterCapabilities(BaseModel):
    """Control Center 只启用服务端明确声明的真实能力。"""

    model_config = ConfigDict(extra="forbid")

    local_agent: bool = True
    durable_queue: bool = True
    mcp_hub: bool = True
    dashboard: bool = False
    task_detail: bool = False
    task_pause_resume: bool = False
    approval_list: bool = False
    approval_digest: bool = False
    result_list: bool = False
    result_preview: bool = False
    health_detailed: bool = False
    logs_query: bool = False
    manual_goal: bool = False
    connector_contract_v1: bool = True
    handoff_contract_v1: bool = True
    worker_status: bool = True
    local_worker: bool = False
    windows_worker: bool = False


class CapabilitiesResponse(BaseModel):
    """新旧客户端都可读取的能力和冻结合同版本快照。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "2.3.0"
    features: ControlCenterCapabilities = Field(default_factory=ControlCenterCapabilities)
    contract_versions: dict[str, str] = Field(
        default_factory=lambda: {
            "connector": "1.0.0",
            "handoff_return": "1.0.0",
        }
    )
    cloud_upload: str = "manual_approval_only"

    # 保留 2.2 顶层字段，避免旧客户端在能力协商升级期间失效。
    local_agent: bool = True
    durable_queue: bool = True
    mcp_hub: bool = True
    windows_worker: bool = False


class WorkerStatusResponse(BaseModel):
    """只读报告执行器部署状态；不会因此启动或领取任务。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "2.3.0"
    available: bool = False
    state: Literal[
        "not_deployed",
        "starting",
        "online",
        "degraded",
        "offline",
    ] = "not_deployed"
    reason: str = "worker_runtime_not_installed"
    worker_id: str | None = None
    supported_task_types: list[str] = Field(default_factory=list)
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
