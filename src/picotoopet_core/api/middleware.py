"""低开销 Trace、Server-Timing 与 Broker Return 请求边界。"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import Message, Receive, Scope, Send

_TRACE_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,100}$")
_BROKER_RETURN_PATH = re.compile(
    r"^/api/v1/broker-sessions/"
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/return$"
)


class BrokerReturnBodyLimitMiddleware:
    """在 JSON 解析前限制固定 Mock Broker Return 的媒体类型和正文大小。"""

    MAX_BODY_BYTES = 128 * 1024

    def __init__(self, app: Callable[[Scope, Receive, Send], Awaitable[None]]) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope.get("method") != "POST"
            or _BROKER_RETURN_PATH.fullmatch(str(scope.get("path", ""))) is None
        ):
            await self.app(scope, receive, send)
            return

        headers      = Headers(scope=scope)
        content_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            await self._send_error(
                scope,
                send,
                status_code=415,
                code="BROKER_OUTPUT_INVALID",
                message="Mock Broker Return 只接受 application/json。",
            )
            return

        raw_length = headers.get("content-length")
        if raw_length is not None:
            try:
                if int(raw_length) > self.MAX_BODY_BYTES:
                    await self._send_too_large(scope, send)
                    return
            except ValueError:
                await self._send_error(
                    scope,
                    send,
                    status_code=400,
                    code="BROKER_OUTPUT_INVALID",
                    message="Mock Broker Return Content-Length 无效。",
                )
                return

        messages: list[Message] = []
        total                   = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            if message["type"] != "http.request":
                continue
            total += len(message.get("body", b""))
            if total > self.MAX_BODY_BYTES:
                await self._send_too_large(scope, send)
                return
            messages.append(message)
            if not message.get("more_body", False):
                break

        position = 0

        async def replay() -> Message:
            """把已验证的有界 ASGI 正文重新交给 FastAPI。"""

            nonlocal position
            if position >= len(messages):
                return {"type": "http.request", "body": b"", "more_body": False}
            message  = messages[position]
            position += 1
            return message

        await self.app(scope, replay, send)

    async def _send_too_large(self, scope: Scope, send: Send) -> None:
        await self._send_error(
            scope,
            send,
            status_code=413,
            code="BROKER_OUTPUT_TOO_LARGE",
            message="Mock Broker Return 超过 128 KiB 安全上限。",
        )

    @staticmethod
    async def _send_error(
        scope: Scope,
        send: Send,
        *,
        status_code: int,
        code: str,
        message: str,
    ) -> None:
        state    = scope.get("state", {})
        trace_id = str(state.get("trace_id") or uuid4().hex)
        body = json.dumps(
            {
                "error": {
                    "code": code,
                    "message": message,
                    "retryable": False,
                    "trace_id": trace_id,
                }
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": status_code,
                "headers": [
                    (b"content-type", b"application/json; charset=utf-8"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


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
