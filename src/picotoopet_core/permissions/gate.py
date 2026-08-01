"""默认拒绝的权限决策器。"""

from __future__ import annotations

from dataclasses import dataclass

from picotoopet_core.domain.enums import Classification

from .models import ActorType, Operation, PermissionRequest


class PermissionDeniedError(PermissionError):
    """权限请求被明确拒绝。"""


@dataclass(frozen=True, slots=True)
class PermissionDecision:
    allowed: bool
    reason_code: str


class PermissionGate:
    """执行 Protected 边界和主体权限矩阵。"""

    _PROTECTED_DENIED = frozenset(
        {Operation.CREATE, Operation.UPDATE, Operation.DELETE, Operation.MOVE, Operation.CLOUD_UPLOAD}
    )
    _CONTROLLED_READERS = frozenset(
        {
            ActorType.HUMAN_OPERATOR,
            ActorType.MAC_AGENT,
            ActorType.CONNECTOR,
            ActorType.MCP_TOOL,
        }
    )
    _WORKSPACE_WRITERS = frozenset(
        {
            ActorType.HUMAN_OPERATOR,
            ActorType.MAC_AGENT,
            ActorType.MCP_TOOL,
            ActorType.WINDOWS_DEVICE,
            ActorType.CONNECTOR,
        }
    )

    def authorize(self, request: PermissionRequest) -> PermissionDecision:
        """允许时返回决策，拒绝时抛出异常。"""

        if request.classification is Classification.PROTECTED:
            if request.operation in self._PROTECTED_DENIED:
                raise PermissionDeniedError("PROTECTED_MUTATION_DENIED")
            if request.operation is Operation.READ and request.actor_type in self._CONTROLLED_READERS:
                return PermissionDecision(True, "PROTECTED_CONTROLLED_READ")
            raise PermissionDeniedError("PROTECTED_DEFAULT_DENY")

        if request.operation is Operation.CLOUD_UPLOAD:
            if request.actor_type is ActorType.CLOUD_EXPORTER:
                return PermissionDecision(True, "CLOUD_EXPORTER_APPROVED_PATH")
            raise PermissionDeniedError("CLOUD_UPLOAD_REQUIRES_GATE")

        if request.operation in {Operation.CREATE, Operation.UPDATE, Operation.DELETE, Operation.MOVE}:
            if request.actor_type in self._WORKSPACE_WRITERS:
                return PermissionDecision(True, "WORKSPACE_WRITE_ALLOWED")
            raise PermissionDeniedError("WORKSPACE_WRITE_DENIED")

        if request.operation in {Operation.READ, Operation.EXECUTE}:
            return PermissionDecision(True, "LOCAL_OPERATION_ALLOWED")

        raise PermissionDeniedError("DEFAULT_DENY")
