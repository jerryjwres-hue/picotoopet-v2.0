"""把持久 Outbox 事件送入实时广播层。"""

from __future__ import annotations

import asyncio

from picotoopet_core.events.broker import EventBroker
from picotoopet_core.events.outbox import EventOutbox


class OutboxDispatcher:
    """以至少一次语义领取、广播和确认持久事件。"""

    def __init__(
        self,
        outbox: EventOutbox,
        broker: EventBroker,
        *,
        worker_id: str = "mac-core-outbox",
        batch_size: int = 100,
        idle_delay_seconds: float = 0.02,
    ) -> None:
        self.outbox              = outbox
        self.broker              = broker
        self.worker_id           = worker_id
        self.batch_size          = max(1, batch_size)
        self.idle_delay_seconds  = max(0.005, idle_delay_seconds)

    async def run_once(self) -> int:
        """投递一批事件并返回成功确认数量。"""

        events = self.outbox.claim(self.worker_id, limit=self.batch_size)
        for event in events:
            await self.broker.publish(event.to_envelope())
            self.outbox.acknowledge(event.outbox_id)
        return len(events)

    async def run(self, stop_event: asyncio.Event) -> None:
        """持续投递；空闲时短暂等待以降低 CPU 占用。"""

        while not stop_event.is_set():
            delivered = await self.run_once()
            if delivered:
                await asyncio.sleep(0)
                continue
            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=self.idle_delay_seconds,
                )
            except TimeoutError:
                pass
