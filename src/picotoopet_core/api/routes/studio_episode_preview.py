"""Read-only completed StoryPack Episode candidate, using the existing Episode schema."""

from __future__ import annotations

import json

from fastapi import APIRouter, Request
from pydantic import ValidationError

from picotoopet_core.api.errors import ApiError
from picotoopet_core.domain.episode import Episode
from picotoopet_core.domain.storypack import StoryPackV1, _unique_json_pairs
from picotoopet_core.domain.storypack_episode_candidate import (
    EpisodeCandidateError,
    complete_storypack_episode_preview,
)

router = APIRouter()
_MAX_BODY_BYTES = 512 * 1024


@router.post("/studio/storypacks/episode-candidate/preview")
async def preview_completed_storypack_episode(request: Request) -> dict:
    """Return a complete-but-UNTRUSTED Episode and budget diagnostic; no queue writes."""
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise ApiError(
            status_code=415, code="VALIDATION_ERROR",
            message="Episode 候选补全仅接受 JSON。", retryable=False,
        )
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > _MAX_BODY_BYTES:
            raise ApiError(
                status_code=413, code="VALIDATION_ERROR",
                message="Episode 补全内容超出大小限制。", retryable=False,
            )
        content.extend(chunk)
    try:
        body = json.loads(
            content.decode("utf-8-sig"), object_pairs_hook=_unique_json_pairs
        )
        if not isinstance(body, dict) or set(body) != {
            "storypack", "storypack_sha256", "completion"
        }:
            raise ValueError("unrecognized body keys")
        pack = StoryPackV1.model_validate(body["storypack"])
        result = complete_storypack_episode_preview(
            pack, body["storypack_sha256"], body["completion"]
        )
    except (UnicodeError, ValueError, TypeError, ValidationError, RecursionError) as error:
        code = error.code if isinstance(error, EpisodeCandidateError) else "EPISODE_PREVIEW_INVALID"
        raise ApiError(
            status_code=422, code=code,
            message="StoryPack 与镜头参数未满足现有 Episode 契约。",
            retryable=False,
        ) from error

    # 该预算检查只计算有界计划成本，不创建生产 Episode 或 GPU 任务。
    result["budget_preview"] = request.app.state.services.production.preview_budget(
        Episode.model_validate(result["episode"])
    )
    return result
