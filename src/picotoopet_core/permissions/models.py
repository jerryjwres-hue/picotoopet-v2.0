"""Permission Gate 输入模型。"""

from enum import StrEnum

from pydantic import BaseModel, Field

from picotoopet_core.domain.enums import Classification


class ActorType(StrEnum):
    HUMAN_OPERATOR   = "human_operator"
    MAC_AGENT        = "mac_agent"
    MCP_TOOL         = "mcp_tool"
    WINDOWS_DEVICE   = "windows_device"
    CONNECTOR        = "connector"
    HEALTH_SUPERVISOR = "health_supervisor"
    CLOUD_EXPORTER   = "cloud_exporter"


class Operation(StrEnum):
    READ         = "read"
    CREATE       = "create"
    UPDATE       = "update"
    DELETE       = "delete"
    MOVE         = "move"
    EXECUTE      = "execute"
    CLOUD_UPLOAD = "cloud_upload"


class PermissionRequest(BaseModel):
    actor_type: ActorType
    actor_id: str = Field(min_length=1)
    operation: Operation
    classification: Classification
    resource_id: str = Field(min_length=1)
