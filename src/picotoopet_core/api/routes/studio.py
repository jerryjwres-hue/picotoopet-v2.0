"""Read-only Picotoo Studio import preview. No workflow or GPU admission."""

from fastapi import APIRouter, Depends, Request

from picotoopet_core.api.errors import ApiError
from picotoopet_core.domain.storypack_assets import inspect_recorded_asset_refs
from picotoopet_core.domain.storypack_fingerprints import build_shot_fingerprints
from picotoopet_core.domain.storypack_owner_subject import build_owner_review_subject
from picotoopet_core.domain.storypack import (
    StoryPackError,
    parse_storypack,
    storypack_preview,
)
from picotoopet_core.security.auth import require_auth

router = APIRouter(dependencies=[Depends(require_auth)])
# 使用既有 Studio 设备认证；候选预览没有任何生产写入权限。
from picotoopet_core.api.routes import studio_episode_preview
router.include_router(studio_episode_preview.router)
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

    # 只读核对记录是否存在，不能将数据库中有 SHA 等同于主人已批准。
    preview = storypack_preview(pack)
    preview["asset_record_checks"] = inspect_recorded_asset_refs(
        request.app.state.services.database,
        preview["unresolved_asset_refs"],
        # 只能读取 Mac Core 自主管理的内容寻址对象目录。
        managed_objects_dir=request.app.state.services.settings.paths.objects_dir,
    )
    # 指纹用于增量差异检查，不提供自动复用/自动生成权限。
    preview["fingerprint_plan"] = build_shot_fingerprints(
        pack,
        preview["storypack_sha256"],
        preview["asset_record_checks"],
    )
    # 为后续可信 Owner 审查锁定故事、素材版本和请求权限；此处绝不批准。
    preview["owner_review_subject"] = build_owner_review_subject(
        pack,
        preview["storypack_sha256"],
        preview["asset_record_checks"],
    )
    return preview
