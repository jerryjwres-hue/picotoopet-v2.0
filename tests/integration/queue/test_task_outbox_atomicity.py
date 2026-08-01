"""任务状态与事务型 Outbox 一致性测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from picotoopet_core.db.database import Database
from picotoopet_core.domain.enums import TaskStatus
from picotoopet_core.domain.models import TaskCreate
from picotoopet_core.events.outbox import EventOutbox
from picotoopet_core.queue.repository import QueueRepository


class ExplodingOutbox(EventOutbox):
    """写入后主动失败，用于证明事务会整体回滚。"""

    def append_in_transaction(self, connection, **kwargs):  # type: ignore[no-untyped-def]
        """先写 Outbox，再抛错模拟进程级故障。"""

        super().append_in_transaction(connection, **kwargs)
        raise RuntimeError("simulated-outbox-failure")


def make_database(tmp_path: Path) -> Database:
    """创建已迁移的隔离数据库。"""

    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    return database


def test_create_and_transition_emit_ordered_outbox_events(tmp_path: Path) -> None:
    """任务创建与转换必须产生严格递增、可重放的事件。"""

    database = make_database(tmp_path)
    outbox   = EventOutbox(database)
    queue    = QueueRepository(database, outbox=outbox)

    created = queue.create(
        TaskCreate(task_type="create_script", idempotency_key="idem-001"),
        trace_id="trace-create",
    )
    repeated = queue.create(
        TaskCreate(task_type="create_script", idempotency_key="idem-001"),
        trace_id="trace-repeat",
    )
    cancelled = queue.transition(
        created.task_id,
        TaskStatus.CANCELLED,
        reason="owner_cancelled",
        trace_id="trace-cancel",
    )

    events = outbox.list_after(0, limit=20)

    assert repeated.task_id == created.task_id
    assert cancelled.status is TaskStatus.CANCELLED
    assert [event.sequence for event in events] == [1, 2]
    assert [event.trace_id for event in events] == ["trace-create", "trace-cancel"]
    assert [event.payload["status"] for event in events] == ["Queued", "Cancelled"]
    assert all(event.topic == "task.updated" for event in events)
    database.close()


def test_outbox_failure_rolls_back_task_and_event(tmp_path: Path) -> None:
    """Outbox 写入失败时任务和事件都不得部分提交。"""

    database = make_database(tmp_path)
    queue    = QueueRepository(database, outbox=ExplodingOutbox(database))

    with pytest.raises(RuntimeError, match="simulated-outbox-failure"):
        queue.create(TaskCreate(task_type="analysis"), trace_id="trace-rollback")

    assert database.fetchone("SELECT COUNT(*) AS count FROM tasks")["count"] == 0
    assert database.fetchone("SELECT COUNT(*) AS count FROM event_outbox")["count"] == 0
    database.close()
