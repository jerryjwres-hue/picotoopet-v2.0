"""WebSocket 使用的有界进程内广播器。"""

from __future__ import annotations

import asyncio
from typing import Any


class EventBroker:
    """为每个订阅者维护独立有界队列并实施背压。"""

    def __init__(self, *, subscriber_capacity: int = 256) -> None:
        if subscriber_capacity < 1:
            raise ValueError("订阅者队列容量必须大于零。")
        self._subscriber_capacity = subscriber_capacity
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        """注册订阅者并返回有界事件队列。"""

        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(
            maxsize=self._subscriber_capacity
        )
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        """注销订阅者。"""

        self._subscribers.discard(queue)

    async def publish(self, event: dict[str, Any]) -> None:
        """向全部订阅者发送副本；队列满时等待而不丢关键事件。"""

        subscribers = tuple(self._subscribers)
        if not subscribers:
            return
        await asyncio.gather(*(queue.put(dict(event)) for queue in subscribers))
