"""受认证的历史制作候选导入。"""

import base64
import binascii
from collections.abc import Awaitable, Callable

from fastapi import APIRouter, Depends, Request, Response
from fastapi.routing import APIRoute
from starlette.exceptions import HTTPException
from starlette.types import Message

from picotoopet_core.api.errors import ApiError
from picotoopet_core.api.thumbnails import validate_thumbnail
from picotoopet_core.domain.history_import import (
    IMPORT_LIMIT,
    EpisodeHistoryImport,
    EpisodeHistoryImported,
)
from picotoopet_core.queue.production_import import import_episode_history
from picotoopet_core.security.auth import require_auth


class _ImportTooLarge(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=413,
            detail="历史导入 JSON 不能超过 52 MiB。",
        )


class _BoundedRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Awaitable[Response]]:
        original = super().get_route_handler()

        async def bounded(request: Request) -> Response:
            remaining = IMPORT_LIMIT

            async def receive() -> Message:
                nonlocal remaining
                message = await request.receive()
                remaining -= len(message.get("body", b""))
                if remaining < 0:
                    raise _ImportTooLarge()
                return message

            try:
                return await original(Request(request.scope, receive))
            except _ImportTooLarge as exc:
                raise ApiError(
                    status_code=exc.status_code,
                    code="VALIDATION_ERROR",
                    message=exc.detail,
                    retryable=False,
                ) from exc

        return bounded


router = APIRouter(dependencies=[Depends(require_auth)], route_class=_BoundedRoute)


@router.post(
    "/episodes/import",
    status_code=201,
    response_model_exclude_none=True,
    responses={
        200: {"model": EpisodeHistoryImported, "description": "候选已导入"},
        409: {"description": "剧集规范冲突或原文件内容已变化"},
        413: {"description": "导入体积超过限制"},
        415: {"description": "缩略图须为有效的 Base64 JPEG"},
    },
)
def import_history(
    body: EpisodeHistoryImport,
    request: Request,
    response: Response,
) -> EpisodeHistoryImported:
    """登记历史素材路径、哈希和审片数据，保持本地媒体路径及原有审核决定。"""
    previews = []
    for item in body.candidates:
        if item.jpeg_base64 is None:
            previews.append(None)
            continue
        try:
            preview = base64.b64decode(item.jpeg_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ApiError(
                status_code=415,
                code="VALIDATION_ERROR",
                message="缩略图必须是有效的 Base64 JPEG。",
                retryable=False,
            ) from exc
        validate_thumbnail(preview)
        previews.append(preview)
    imported = import_episode_history(
        request.app.state.services.executor, body, previews, request.state.trace_id
    )
    if not imported.inserted_count:
        response.status_code = 200
    return imported
