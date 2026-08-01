import asyncio
from pathlib import Path

from picotoopet_core.db.database import Database
from picotoopet_core.events.broker import EventBroker
from picotoopet_core.events.outbox import EventOutbox


def test_outbox_claim_ack_and_redelivery(tmp_path: Path) -> None:
    """未确认事件必须可重新领取，确认后不得重复发送。"""

    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    outbox = EventOutbox(database)
    first_id = outbox.append("task.updated", {"task_id": "1"}, trace_id="trace-1")
    second_id = outbox.append("task.updated", {"task_id": "2"}, trace_id="trace-2")

    claimed = outbox.claim("dispatcher-a", limit=1)
    assert [event.outbox_id for event in claimed] == [first_id]
    redelivered = outbox.claim("dispatcher-b", limit=2, stale_after_seconds=0)
    assert [event.outbox_id for event in redelivered] == [first_id, second_id]
    outbox.acknowledge(first_id)
    remaining = outbox.claim("dispatcher-c", limit=10, stale_after_seconds=0)
    assert [event.outbox_id for event in remaining] == [second_id]
    database.close()


async def test_broker_fans_out_to_each_subscriber() -> None:
    """每个 WebSocket 订阅者都必须收到同一事件。"""

    broker = EventBroker()
    first = broker.subscribe()
    second = broker.subscribe()
    await broker.publish({"topic": "health", "status": "ok"})

    assert await asyncio.wait_for(first.get(), timeout=1) == {"topic": "health", "status": "ok"}
    assert await asyncio.wait_for(second.get(), timeout=1) == {"topic": "health", "status": "ok"}
    broker.unsubscribe(first)
    broker.unsubscribe(second)
