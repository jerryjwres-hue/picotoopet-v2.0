from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from picotoopet_core.approvals.service import ApprovalError, ApprovalService
from picotoopet_core.db.database import Database
from picotoopet_core.domain.enums import CloudPolicy, TaskStatus
from picotoopet_core.domain.models import TaskCreate
from picotoopet_core.queue.repository import QueueRepository
from picotoopet_core.queue.state_machine import InvalidTransitionError


def test_scoped_approval_resumes_once_and_rejects_replay(tmp_path: Path) -> None:
    """审批令牌只能使用一次，并仅恢复对应任务。"""

    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    repository = QueueRepository(database)
    service = ApprovalService(database, repository)
    task = repository.create(
        TaskCreate(task_type="cloud_upload", cloud_policy=CloudPolicy.CLOUD_MANUAL)
    )

    grant = service.request(
        task_id=task.task_id,
        approval_type="cloud_upload",
        scope={"target": "approved-handoff.zip"},
        requested_by="mac-agent",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    approved = service.approve(
        approval_id=grant.approval_id,
        token=grant.token,
        resolved_by="owner",
        reason="approved handoff only",
    )

    assert approved.status == "Approved"
    assert repository.get(task.task_id).status is TaskStatus.QUEUED
    with pytest.raises(ApprovalError):
        service.approve(
            approval_id=grant.approval_id,
            token=grant.token,
            resolved_by="owner",
            reason="replay",
        )
    database.close()


def test_expired_approval_is_rejected(tmp_path: Path) -> None:
    """过期审批不得恢复任务。"""

    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    repository = QueueRepository(database)
    service = ApprovalService(database, repository)
    task = repository.create(
        TaskCreate(task_type="cloud_upload", cloud_policy=CloudPolicy.CLOUD_MANUAL)
    )
    grant = service.request(
        task_id=task.task_id,
        approval_type="cloud_upload",
        scope={},
        requested_by="mac-agent",
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )

    with pytest.raises(ApprovalError):
        service.approve(
            approval_id=grant.approval_id,
            token=grant.token,
            resolved_by="owner",
            reason="too late",
        )
    assert service.get(grant.approval_id).status == "Expired"
    assert repository.get(task.task_id).status is TaskStatus.WAITING_FOR_APPROVAL
    database.close()


def test_reject_cancels_waiting_task_and_cannot_be_replayed(tmp_path: Path) -> None:
    """人工拒绝后对应任务取消，审批令牌失效。"""

    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    repository = QueueRepository(database)
    service = ApprovalService(database, repository)
    task = repository.create(
        TaskCreate(task_type="cloud_upload", cloud_policy=CloudPolicy.CLOUD_MANUAL)
    )
    grant = service.request(
        task_id=task.task_id,
        approval_type="cloud_upload",
        scope={},
        requested_by="mac-agent",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )

    rejected = service.reject(
        approval_id=grant.approval_id,
        token=grant.token,
        resolved_by="owner",
        reason="not approved",
    )

    assert rejected.status == "Rejected"
    assert repository.get(task.task_id).status is TaskStatus.CANCELLED
    with pytest.raises(ApprovalError):
        service.reject(
            approval_id=grant.approval_id,
            token=grant.token,
            resolved_by="owner",
            reason="replay",
        )
    database.close()


def test_approval_and_task_transition_commit_atomically(tmp_path: Path) -> None:
    """任务状态冲突时，审批记录不得单独提交为 Approved。"""

    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    repository = QueueRepository(database)
    service = ApprovalService(database, repository)
    task = repository.create(
        TaskCreate(task_type="cloud_upload", cloud_policy=CloudPolicy.CLOUD_MANUAL)
    )
    grant = service.request(
        task_id=task.task_id,
        approval_type="cloud_upload",
        scope={"file": "handoff.zip"},
        requested_by="mac-agent",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    repository.transition(task.task_id, TaskStatus.CANCELLED, reason="owner_cancelled")

    with pytest.raises(InvalidTransitionError):
        service.approve(
            approval_id=grant.approval_id,
            token=grant.token,
            resolved_by="owner",
            reason="late approval",
        )

    assert service.get(grant.approval_id).status == "Pending"
    assert repository.get(task.task_id).status is TaskStatus.CANCELLED
    database.close()
