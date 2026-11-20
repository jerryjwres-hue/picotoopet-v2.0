"""Device-authenticated, one-use, TLS-required private frame ZIP retrieval.

Issuing a ticket is exclusively a scoped Owner loopback operation. Device
Bearer alone never grants permission to enumerate or fetch managed sources.
"""

from __future__ import annotations

from ipaddress import ip_address

from fastapi import APIRouter, Depends, Header, Request
from starlette.background import BackgroundTask
from starlette.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from picotoopet_core.api.errors import ApiError
from picotoopet_core.domain.frame_transfer_tickets import FrameTransferError
from picotoopet_core.security.auth import require_auth

router = APIRouter(dependencies=[Depends(require_auth)])
_UNTRUSTED_PROXY_HEADERS = (
    "forwarded", "x-forwarded-for", "x-forwarded-proto", "x-real-ip",
)


def _require_secure_delivery_peer(request: Request) -> None:
    """Allow HTTPS remote delivery or direct local testing, never LAN HTTP."""
    address = request.client.host if request.client is not None else ""
    try:
        local = ip_address(address).is_loopback
    except ValueError:
        local = False

    # 不接受代理自行声明的 HTTPS；只相信 ASGI socket 真实看到的 scheme。
    if any(name in request.headers for name in _UNTRUSTED_PROXY_HEADERS):
        raise ApiError(
            status_code=403, code="FRAME_TRANSFER_UNTRUSTED_PROXY",
            message="素材下载需要可信加密连接。", retryable=False,
        )
    if request.scope.get("scheme") != "https" and not local:
        raise ApiError(
            status_code=403, code="FRAME_TRANSFER_TLS_REQUIRED",
            message="远程素材下载必须使用加密连接。", retryable=False,
        )


@router.get("/studio/frame-transfer/download")
async def download_staged_frame_bundle(
    request: Request,
    transfer_ticket: str = Header(
        alias="X-Picotoo-Transfer-Ticket", min_length=20, max_length=160
    ),
) -> FileResponse:
    """Stream a single-use ZIP; recheck Owner revocation before first byte."""
    _require_secure_delivery_peer(request)
    registry = request.app.state.frame_transfer_tickets
    try:
        item = await run_in_threadpool(registry.consume, transfer_ticket)
    except FrameTransferError as error:
        raise ApiError(
            status_code=409, code=str(error),
            message="素材传输凭据失效、已使用或来源已改变。",
            retryable=False,
        ) from error

    return FileResponse(
        path=item.path,
        media_type="application/zip",
        filename="PicotooPet-Frame-Sources.zip",
        content_disposition_type="attachment",
        headers={
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
            "X-Content-Type-Options": "nosniff",
            "X-Picotoo-Source-Bindings-Sha256": item.manifest_sha256,
            "X-Picotoo-Bundle-Sha256": item.bundle_sha256,
        },
        background=BackgroundTask(registry.finish, item.path),
    )
