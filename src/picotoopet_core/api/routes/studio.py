"""V3.1 Studio read-only StoryPack preview on the canonical Mac Core 2.3 APIs."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response

from picotoopet_core.api.errors import ApiError
from picotoopet_core.domain.storypack import StoryPackError, parse_storypack, storypack_preview
from picotoopet_core.domain.storypack_assets import inspect_recorded_asset_refs
from picotoopet_core.domain.storypack_fingerprints import build_shot_fingerprints
from picotoopet_core.domain.storypack_goal_intake import build_storypack_goal_intake
from picotoopet_core.domain.storypack_owner_subject import build_owner_review_subject
from picotoopet_core.security.auth import require_auth

# 只使用原 2.3 设备 Bearer；这不是 Owner / MASTER 身份或 GPU 授权。
router = APIRouter(dependencies=[Depends(require_auth)])
STORYPACK_LIMIT = 128 * 1024


@router.post("/studio/storypacks/preview")
async def preview_storypack(request: Request, response: Response) -> dict:
    """只校验 StoryPack 与已登记资产的字节证据，不创建生产任务。"""

    response.headers["Cache-Control"] = "no-store, private"
    response.headers["Pragma"] = "no-cache"

    # 当前 2.3 适配层先明确支持 JSON；不悄悄引入 PyYAML 或旧 Episode 执行器。
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        raise ApiError(
            status_code=415,
            code="STORYPACK_JSON_ONLY",
            message="2.3 兼容预览目前仅接受 application/json。",
            retryable=False,
        )

    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > STORYPACK_LIMIT:
            raise ApiError(
                status_code=413,
                code="STORYPACK_TOO_LARGE",
                message="StoryPack 输入不能超过 128 KiB。",
                retryable=False,
            )
        body.extend(chunk)

    try:
        pack = parse_storypack(bytes(body))
    except StoryPackError as exc:
        raise ApiError(
            status_code=422,
            code="STORYPACK_VALIDATION_FAILED",
            message=str(exc)[:1200],
            retryable=False,
        ) from exc

    preview = storypack_preview(pack)
    preview["asset_record_checks"] = inspect_recorded_asset_refs(
        request.app.state.services.database,
        preview["unresolved_asset_refs"],
        # 只能验证 Core 托管的 SHA 命名对象，绝不访问用户提交的 source_path。
        managed_objects_dir=request.app.state.services.settings.paths.objects_dir,
    )
    preview["fingerprint_plan"] = build_shot_fingerprints(
        pack, preview["storypack_sha256"], preview["asset_record_checks"]
    )
    preview["owner_review_subject"] = build_owner_review_subject(
        pack, preview["storypack_sha256"], preview["asset_record_checks"]
    )

    # 仅构造现有 HumanGoalService 的可审阅输入；不创建 Goal、Workflow 或 Task。
    # 草稿到正式 Creative Package 的来源验证和 Production 门禁仍由原 2.3 服务完成。
    preview["canonical_goal_intake"] = build_storypack_goal_intake(
        pack, preview["storypack_sha256"]
    )

    # 预览成功≠合法 ProductionPlan；旧 V3.1 Episode 无法代替 2.3 的审批与 Claim。
    preview["core23_compatibility"] = {
        "contract": "picotoo.studio-2.3.storypack-preview.v1",
        "mode": "READ_ONLY",
        "executable_plan": False,
        "owner_authorized": False,
        "worker_admitted": False,
        "gpu_post_authorized": False,
        "can_queue": False,
    }
    return preview
