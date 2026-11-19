"""Read-only Picotoo Studio import preview. No workflow or GPU admission."""

from fastapi import APIRouter, Depends, Request

from picotoopet_core.api.errors import ApiError
from picotoopet_core.domain.storypack import (
    StoryPackError,
    parse_storypack,
    storypack_preview,
)
from picotoopet_core.security.auth import require_auth

router = APIRouter(dependencies=[Depends(require_auth)])
STORYPACK_LIMIT = 128 * 1024
SUPPORTED_TYPES = {
    "application/json",
    "application/yaml",
    "application/x-yaml",
    "text/yaml",
    "text/x-yaml",
}


@router.post("/studio/storypacks/preview")
async def preview_storypack(request: Request) -> dict:
    """Parse a pasted StoryPack; never persist, enqueue, or authorize rendering."""
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type not in SUPPORTED_TYPES:
        raise ApiError(
            status_code=415,
            code="VALIDATION_ERROR",
            message="StoryPack 仅接受 JSON 或 YAML。",
            retryable=False,
        )

    # 限制正文，避免未经审查的超大 LLM 输出进入后台解析。
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > STORYPACK_LIMIT:
            raise ApiError(
                status_code=413,
                code="VALIDATION_ERROR",
                message="StoryPack 不能超过 128 KiB。",
                retryable=False,
            )
        content.extend(chunk)

    try:
        pack = parse_storypack(bytes(content), as_yaml=content_type != "application/json")
    except StoryPackError as exc:
        raise ApiError(
            status_code=422,
            code="VALIDATION_ERROR",
            message=str(exc)[:2000],
            retryable=False,
        ) from exc

    # 返回预览结果，但不修改 SQLite，也不调用任何 Windows 工具。
    return storypack_preview(pack)
