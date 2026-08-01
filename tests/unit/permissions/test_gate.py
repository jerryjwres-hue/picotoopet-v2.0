import pytest

from picotoopet_core.domain.enums import Classification
from picotoopet_core.permissions.gate import PermissionDeniedError, PermissionGate
from picotoopet_core.permissions.models import ActorType, Operation, PermissionRequest


def test_protected_data_allows_controlled_read_but_rejects_mutation_and_upload() -> None:
    """Protected 数据即使由人工操作，也不得写入、删除或直接上传。"""

    gate = PermissionGate()
    gate.authorize(
        PermissionRequest(
            actor_type=ActorType.HUMAN_OPERATOR,
            actor_id="owner",
            operation=Operation.READ,
            classification=Classification.PROTECTED,
            resource_id="evidence-1",
        )
    )

    for operation in (Operation.UPDATE, Operation.DELETE, Operation.MOVE, Operation.CLOUD_UPLOAD):
        with pytest.raises(PermissionDeniedError):
            gate.authorize(
                PermissionRequest(
                    actor_type=ActorType.HUMAN_OPERATOR,
                    actor_id="owner",
                    operation=operation,
                    classification=Classification.PROTECTED,
                    resource_id="evidence-1",
                )
            )


def test_workspace_agent_can_create_internal_result() -> None:
    """Mac Agent 可以在 V2 Workspace 创建内部结果。"""

    PermissionGate().authorize(
        PermissionRequest(
            actor_type=ActorType.MAC_AGENT,
            actor_id="mac-core",
            operation=Operation.CREATE,
            classification=Classification.INTERNAL,
            resource_id="result-1",
        )
    )
