from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from picotoopet_core.db.database import Database
from picotoopet_core.handoffs.approvals import HandoffApprovalService
from picotoopet_core.handoffs.models import HandoffPrepareRequest, HandoffStatus
from picotoopet_core.handoffs.service import (
    HandoffConflict,
    HandoffPolicyError,
    HandoffService,
)
from picotoopet_core.queue.repository import QueueRepository


class MutableClock:
    """让创建、读取和过期判断共享同一个确定性 UTC 时钟。"""

    def __init__(self, current: datetime) -> None:
        self.current = current

    def __call__(self) -> datetime:
        return self.current

    def advance(self, delta: timedelta) -> None:
        self.current += delta


def make_service(
    tmp_path: Path,
    *,
    clock: MutableClock | None = None,
) -> tuple[Database, HandoffService]:
    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    queue = QueueRepository(database)
    approvals = HandoffApprovalService(database, queue)
    return database, HandoffService(database, approvals, clock=clock)


def request(
    *,
    title: str = "修复结果预览",
    objective: str = "保持同一结果刷新后的安全预览。",
) -> HandoffPrepareRequest:
    return HandoffPrepareRequest(
        template_id="picotoopet-repo-maintenance-v1",
        title=title,
        objective=objective,
        expires_seconds=1800,
    )


def test_prepare_is_deterministic_and_idempotent(tmp_path: Path) -> None:
    clock = MutableClock(datetime(2026, 8, 5, 19, 30, tzinfo=UTC))
    database, service = make_service(tmp_path, clock=clock)

    first = service.prepare(request(), idempotency_key="prepare-001")
    replay = service.prepare(request(), idempotency_key="prepare-001")

    assert replay == first
    assert first.status is HandoffStatus.PREPARED
    assert first.provider == "manual"
    assert first.base_ref != "main"
    assert first.base_commit == "5db6b1f9340ff5abe0d38bbb7b6e3ee9b48c34bb"
    assert len(first.request_digest) == 64
    assert len(first.package_digest) == 64
    assert first.planned_read_count == 1
    assert first.planned_write_count == 1
    assert first.required_tests == [
        "python-regression",
        "windows-wpf-behavior",
        "windows-formal-release",
        "mac-core-arm64",
    ]
    assert database.scalar("SELECT COUNT(*) FROM handoffs") == 1
    database.close()


def test_expiry_uses_the_same_injected_clock_as_prepare(tmp_path: Path) -> None:
    clock = MutableClock(datetime(2026, 8, 5, 19, 30, tzinfo=UTC))
    database, service = make_service(tmp_path, clock=clock)
    prepared = service.prepare(request(), idempotency_key="prepare-expiry")

    clock.advance(timedelta(seconds=1801))
    expired = service.get(prepared.handoff_id)

    assert expired.status is HandoffStatus.EXPIRED
    assert expired.updated_at == clock.current
    assert database.scalar(
        "SELECT status FROM handoffs WHERE handoff_id = ?",
        (prepared.handoff_id,),
    ) == HandoffStatus.EXPIRED.value
    database.close()


def test_reused_idempotency_key_rejects_changed_normalized_request(tmp_path: Path) -> None:
    database, service = make_service(tmp_path)
    service.prepare(request(), idempotency_key="prepare-001")

    with pytest.raises(HandoffConflict, match="Idempotency-Key"):
        service.prepare(
            request(objective="不同目标必须创建新请求。"),
            idempotency_key="prepare-001",
        )
    database.close()


def test_bound_fields_change_request_digest(tmp_path: Path) -> None:
    database, service = make_service(tmp_path)
    first = service.prepare(request(), idempotency_key="prepare-001")
    second = service.prepare(
        request(title="修复任务中心"),
        idempotency_key="prepare-002",
    )

    assert first.request_digest != second.request_digest
    assert first.package_digest != second.package_digest
    database.close()


@pytest.mark.parametrize(
    ("title", "objective"),
    [
        ("main", "不得把 protected branch 当任务目标。"),
        ("正常标题", "包含 ../ 路径逃逸。"),
        ("正常标题", "请上传 Protected 原件。"),
        ("正常标题", "token=0123456789abcdef0123456789abcdef"),
    ],
)
def test_prepare_rejects_unsafe_free_text(
    tmp_path: Path,
    title: str,
    objective: str,
) -> None:
    database, service = make_service(tmp_path)
    with pytest.raises(HandoffPolicyError):
        service.prepare(
            request(title=title, objective=objective),
            idempotency_key="prepare-unsafe",
        )
    database.close()


def test_request_model_rejects_control_characters_before_service() -> None:
    """不可见控制字符必须在进入数据库或领域服务前被拒绝。"""

    with pytest.raises(ValidationError, match="控制字符"):
        request(title="带\x00控制字符", objective="正常目标")
