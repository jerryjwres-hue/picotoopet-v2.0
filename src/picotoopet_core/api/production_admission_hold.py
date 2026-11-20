"""Fail-closed legacy GPU ingress when independent StoryPack Owner review is configured.

This guard is intentionally *not* an admission grant. Existing CPU-only and
legacy unconfigured installations keep their previous behavior, while any
installed Owner credential registry places legacy device-GPU routes on HOLD
until a separate trusted production Plan admission path is implemented.
"""

from __future__ import annotations

from fastapi import Request

from picotoopet_core.api.errors import ApiError
from picotoopet_core.domain.executor import GPU_TAG, TASK_RUNNERS
from picotoopet_core.domain.models import TaskCreate


def storypack_owner_hold(request: Request) -> bool:
    """只要配置过独立 Owner 主体，即使当前凭据过期/被禁用也不能自动降级为旧模式。"""
    # 读取启动时事务持久化的保护状态，而非可被清空的当前 Token 列表。
    # 从未配置过 Owner 的旧部署仍保持原有兼容行为。
    return request.app.state.services.owner_mode_gpu_hold


def block_legacy_episode_creation(request: Request) -> None:
    """阻止旧设备令牌直接把 Episode 转换为新的 GPU 任务。"""
    if storypack_owner_hold(request):
        raise ApiError(
            status_code=409,
            code="STORYPACK_PRODUCTION_ADMISSION_REQUIRED",
            message="当前项目已启用 Owner 审核；旧剧集入口不能绕过冻结 Plan 直接生成。",
            retryable=False,
        )


def block_legacy_gpu_task(request: Request, payload: TaskCreate) -> None:
    """拒绝执行器类型与任何显式 GPU 资源标签的设备端直接创建/重抽。"""
    if storypack_owner_hold(request) and (
        payload.task_type in TASK_RUNNERS or payload.resource_tag == GPU_TAG
    ):
        raise ApiError(
            status_code=409,
            code="STORYPACK_PRODUCTION_ADMISSION_REQUIRED",
            message="当前项目需要独立的 Owner、MASTER 和冻结 Plan 生产准入。",
            retryable=False,
        )
