from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from picotoopet_core.approvals.service import ApprovalError, ApprovalService
from picotoopet_core.db.database import Database
from picotoopet_core.domain.enums import CloudPolicy, TaskStatus
from picotoopet_core.domain.models import TaskCreate
from picotoopet_core.queue.repository import QueueRepository


def make_service(tmp_path: Path) -> tuple[Database, QueueRepository, ApprovalService]:
    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    repository = QueueRepository(database)
    return database, repository, ApprovalService(database, repository)


def test_control_center_lists_safe_digest_and_idempotent_decision(tmp_path: Path) -> None:
    """审批中心必须按摘要决策，重复点击不得产生第二次副作用。"""

    database, repository, service = make_service(tmp_path)
    task = repository.create(
        TaskCreate(task_type="cloud_upload", cloud_policy=CloudPolicy.CLOUD_MANUAL)
    )
    grant = service.request(
        task_id=task.task_id,
        approval_type="cloud_upload",
        scope={"target": "approved-handoff.zip", "budget": 0},
        requested_by="mac-agent",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )

    listed = service.list_for_control_center(limit=50)
    item = next(record for record in listed if record.approval_id == grant.approval_id)
    assert item.status == "Pending"
    assert len(item.request_digest) == 64
    assert item.scope_summary == "budget=0；target=approved-handoff.zip"
    assert "token" not in item.model_dump_json().lower()

    approved = service.decide_for_control_center(
        approval_id=item.approval_id,
        decision="approve",
        request_digest=item.request_digest,
        idempotency_key="approval-click-001",
        resolved_by="owner",
        reason="批准此固定目标",
    )
    replay = service.decide_for_control_center(
        approval_id=item.approval_id,
        decision="approve",
        request_digest=item.request_digest,
        idempotency_key="approval-click-001",
        resolved_by="owner",
        reason="批准此固定目标",
    )

    assert approved.status == "Approved"
    assert replay == approved
    assert repository.get(task.task_id).status is TaskStatus.QUEUED
    with pytest.raises(ApprovalError):
        service.decide_for_control_center(
            approval_id=item.approval_id,
            decision="reject",
            request_digest=item.request_digest,
            idempotency_key="approval-click-002",
            resolved_by="owner",
            reason="冲突重放",
        )
    database.close()


def test_control_center_rejects_stale_digest_and_marks_expired_records(tmp_path: Path) -> None:
    """范围变化后的旧摘要和过期审批均不得被客户端继续批准。"""

    database, repository, service = make_service(tmp_path)
    task = repository.create(
        TaskCreate(task_type="cloud_upload", cloud_policy=CloudPolicy.CLOUD_MANUAL)
    )
    grant = service.request(
        task_id=task.task_id,
        approval_type="cloud_upload",
        scope={"target": "first.zip"},
        requested_by="mac-agent",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    item = next(
        record
        for record in service.list_for_control_center(limit=50)
        if record.approval_id == grant.approval_id
    )
    with database.transaction() as connection:
        connection.execute(
            "UPDATE approvals SET scope_json = ? WHERE approval_id = ?",
            ('{"target":"changed.zip"}', grant.approval_id),
        )

    with pytest.raises(ApprovalError, match="摘要"):
        service.decide_for_control_center(
            approval_id=grant.approval_id,
            decision="approve",
            request_digest=item.request_digest,
            idempotency_key="stale-digest",
            resolved_by="owner",
            reason="不得批准变化后的请求",
        )

    expired_task = repository.create(
        TaskCreate(task_type="cloud_upload", cloud_policy=CloudPolicy.CLOUD_MANUAL)
    )
    expired_grant = service.request(
        task_id=expired_task.task_id,
        approval_type="cloud_upload",
        scope={},
        requested_by="mac-agent",
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    expired = next(
        record
        for record in service.list_for_control_center(limit=50)
        if record.approval_id == expired_grant.approval_id
    )
    assert expired.status == "Expired"
    database.close()
