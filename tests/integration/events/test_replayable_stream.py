"""可重放、有界事件流测试。"""

from __future__ import annotations

import asyncio
from pathlib import Path

from picotoopet_core.db.database import Database
from picotoopet_core.events.broker import EventBroker
from picotoopet_core.events.dispatcher import OutboxDispatcher
from picotoopet_core.events.outbox import EventOutbox


def make_outbox(tmp_path: Path) -> tuple[Database, EventOutbox]:
    """创建隔离数据库与 Outbox。"""

    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    return database, EventOutbox(database)


def test_outbox_replay_starts_after_acknowledged_sequence(tmp_path: Path) -> None:
    """重放必须只返回指定序号之后的事件。"""

    database, outbox = make_outbox(tmp_path)
    outbox.append("task.updated", {"task_id": "1"}, trace_id="trace-1")
    outbox.append("task.updated", {"task_id": "2"}, trace_id="trace-2")
    outbox.append("task.updated", {"task_id": "3"}, trace_id="trace-3")

    replay = outbox.list_after(1, limit=10)

    assert [event.sequence for event in replay] == [2, 3]
    assert [event.payload["task_id"] for event in replay] == ["2", "3"]
    database.close()


async def test_broker_applies_backpressure_when_subscriber_is_full() -> None:
    """订阅者处理过慢时必须背压，不能静默丢关键事件。"""

    broker = EventBroker(subscriber_capacity=1)
    queue  = broker.subscribe()
    await broker.publish({"sequence": 1, "topic": "task.updated"})

    blocked = asyncio.create_task(
        broker.publish({"sequence": 2, "topic": "task.updated"})
    )
    await asyncio.sleep(0)
    assert blocked.done() is False

    assert (await queue.get())["sequence"] == 1
    await asyncio.wait_for(blocked, timeout=1)
    assert (await queue.get())["sequence"] == 2
    broker.unsubscribe(queue)


async def test_dispatcher_publishes_envelope_and_acknowledges(tmp_path: Path) -> None:
    """Dispatcher 成功广播后必须确认 Outbox，同时保留重放记录。"""

    database, outbox = make_outbox(tmp_path)
    broker            = EventBroker()
    dispatcher        = OutboxDispatcher(outbox, broker, worker_id="test-dispatcher")
    queue             = broker.subscribe()
    outbox_id         = outbox.append("task.updated", {"task_id": "1"}, trace_id="trace-1")

    delivered = await dispatcher.run_once()
    envelope  = await asyncio.wait_for(queue.get(), timeout=1)
    row       = database.fetchone(
        "SELECT delivered_at FROM event_outbox WHERE outbox_id = ?",
        (outbox_id,),
    )

    assert delivered == 1
    assert envelope["schema_version"] == "2.2.0"
    assert envelope["sequence"] == 1
    assert envelope["trace_id"] == "trace-1"
    assert row["delivered_at"] is not None
    assert outbox.list_after(0)[0].outbox_id == outbox_id
    broker.unsubscribe(queue)
    database.close()
