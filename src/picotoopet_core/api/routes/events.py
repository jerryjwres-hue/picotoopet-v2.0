"""认证、可续传的 WebSocket 事件路由。"""

from __future__ import annotations

import asyncio
import hmac
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


@router.websocket("/events")
async def events(websocket: WebSocket) -> None:
    """补发缺失事件，再持续推送实时事件与应用级 Ping/Pong。"""

    header              = websocket.headers.get("authorization", "")
    scheme, _, supplied = header.partition(" ")
    expected            = websocket.app.state.services.settings.api_token
    if scheme.lower() != "bearer" or not hmac.compare_digest(supplied, expected):
        await websocket.close(code=4401, reason="authentication required")
        return

    after_sequence_raw = websocket.query_params.get("after_sequence", "0")
    try:
        after_sequence = max(0, int(after_sequence_raw))
    except ValueError:
        await websocket.close(code=4400, reason="invalid after_sequence")
        return

    await websocket.accept()
    services  = websocket.app.state.services
    broker    = services.broker
    queue     = broker.subscribe()
    send_lock = asyncio.Lock()

    await websocket.send_json(
        {
            "topic": "connected",
            "status": "ok",
            "last_sequence": after_sequence,
        }
    )

    async def send_events() -> None:
        """先重放持久事件，再消费实时事件并跳过重复序号。"""

        last_sequence = after_sequence
        replay        = services.outbox.list_after(last_sequence, limit=2000)
        for event in replay:
            envelope = event.to_envelope()
            async with send_lock:
                await websocket.send_json(envelope)
            last_sequence = event.sequence

        while True:
            event    = await queue.get()
            sequence = event.get("sequence")
            if isinstance(sequence, int) and sequence <= last_sequence:
                continue
            async with send_lock:
                await websocket.send_json(event)
            if isinstance(sequence, int):
                last_sequence = sequence

    async def receive_control() -> None:
        """处理桌面端控制消息；当前仅提供低开销 Ping/Pong。"""

        while True:
            message: dict[str, Any] = await websocket.receive_json()
            if message.get("type") != "ping":
                continue
            async with send_lock:
                await websocket.send_json(
                    {
                        "type": "pong",
                        "nonce": message.get("nonce"),
                        "server_time": datetime.now(UTC).isoformat(),
                    }
                )

    sender   = asyncio.create_task(send_events(), name="picotoo-websocket-sender")
    receiver = asyncio.create_task(receive_control(), name="picotoo-websocket-receiver")
    try:
        done, pending = await asyncio.wait(
            {sender, receiver},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            # 客户端关闭与应用停机都可能先取消子任务；读取其异常会再次抛出取消。
            if task.cancelled():
                continue
            exception = task.exception()
            if exception is not None:
                raise exception
    except (WebSocketDisconnect, asyncio.CancelledError):
        # WebSocket 断开或连接生命周期取消均进入同一幂等清理路径。
        pass
    finally:
        sender.cancel()
        receiver.cancel()
        await asyncio.gather(sender, receiver, return_exceptions=True)
        broker.unsubscribe(queue)
