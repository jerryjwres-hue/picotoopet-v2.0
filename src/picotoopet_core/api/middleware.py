"""低开销 Trace 与 Server-Timing ASGI 中间件。"""

from __future__ import annotations

import re
import time
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import Message, Receive, Scope, Send

_TRACE_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,100}$")


class TraceTimingMiddleware:
    """为 HTTP 请求增加 Trace ID 和单调时钟耗时。"""

    def __init__(self, app: Callable[[Scope, Receive, Send], Awaitable[None]]) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """只处理 HTTP；WebSocket 使用事件信封中的 Trace ID。"""

        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers   = Headers(scope=scope)
        requested = headers.get("x-picotoo-trace-id", "")
        trace_id  = requested if _TRACE_PATTERN.fullmatch(requested) else uuid4().hex
        started   = time.perf_counter_ns()

        state             = scope.setdefault("state", {})
        state["trace_id"] = trace_id

        async def send_with_timing(message: Message) -> None:
            """在响应头发出前计算服务端应用耗时。"""

            if message["type"] == "http.response.start":
                elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
                mutable    = MutableHeaders(scope=message)
                mutable["X-Picotoo-Trace-Id"] = trace_id
                mutable["Server-Timing"]      = f"app;dur={elapsed_ms:.3f}"
            await send(message)

        await self.app(scope, receive, send_with_timing)
