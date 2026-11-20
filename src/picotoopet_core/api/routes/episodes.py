"""剧集导入、审片视图和合成接口。"""

from fastapi import APIRouter, Depends, Request, Response
from starlette.concurrency import run_in_threadpool

from picotoopet_core.api.errors import ApiError
from picotoopet_core.api.production_admission_hold import block_legacy_episode_creation
from picotoopet_core.domain.episode import (
    Episode,
    EpisodeCreated,
    EpisodeReview,
    EpisodeSummary,
    EpisodeValidationError,
    load_episode,
)
from picotoopet_core.domain.models import TaskRecord
from picotoopet_core.security.auth import require_auth

router = APIRouter(dependencies=[Depends(require_auth)])
EPISODE_LIMIT = 2 * 1024 * 1024


async def _parse_episode_request(request: Request) -> Episode:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type not in {
        "application/json",
        "application/yaml",
        "application/x-yaml",
        "text/yaml",
        "text/x-yaml",
    }:
        raise ApiError(
            status_code=415,
            code="VALIDATION_ERROR",
            message="剧集须使用 JSON 或 YAML 请求格式。",
            retryable=False,
        )
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > EPISODE_LIMIT:
            raise ApiError(
                status_code=413,
                code="VALIDATION_ERROR",
                message="剧集文件不能超过 2 MB。",
                retryable=False,
            )
        content.extend(chunk)
    try:
        episode = await run_in_threadpool(
            load_episode,
            bytes(content),
            as_yaml=content_type != "application/json",
        )
    except EpisodeValidationError as exc:
        raise ApiError(
            status_code=422, code="VALIDATION_ERROR", message=str(exc), retryable=False
        ) from exc
    return episode


@router.post(
    "/episodes",
    status_code=201,
    responses={
        200: {"model": EpisodeCreated, "description": "剧集已存在"},
        422: {
            "description": "剧集字段校验失败",
        },
    },
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {"schema": {"$ref": "#/components/schemas/Episode"}},
                "application/yaml": {
                    "schema": {"type": "string", "description": "UTF-8 episode.yaml"}
                },
            },
        }
    },
)
async def create_episode(request: Request, response: Response) -> EpisodeCreated:
    # Owner 模式禁止旧设备接口直接入 GPU 队列；只读预算接口不受影响。
    block_legacy_episode_creation(request)
    episode = await _parse_episode_request(request)
    service = request.app.state.services.production
    try:
        created, inserted = await run_in_threadpool(
            service.create, episode, request.state.trace_id
        )
    except EpisodeValidationError as exc:
        raise ApiError(
            status_code=422, code="VALIDATION_ERROR",
            message=str(exc), retryable=False,
        ) from exc
    if not inserted:
        response.status_code = 200
    return created


@router.post("/episodes/budget/preview")
async def preview_episode_budget(request: Request) -> dict:
    """Estimate bounded takes before the client submits an executable Episode."""
    episode = await _parse_episode_request(request)
    # 只读预算诊断：既不建立 episode，也不签发 GPU 或 Owner 权限。
    return request.app.state.services.production.preview_budget(episode)


@router.get("/episodes")
def list_episodes(request: Request) -> list[EpisodeSummary]:
    return request.app.state.services.production.list()


@router.get("/episodes/{episode_id}/review")
def read_review(episode_id: str, request: Request) -> EpisodeReview:
    return request.app.state.services.production.review(episode_id)


@router.post(
    "/episodes/{episode_id}/assemble",
    status_code=201,
    responses={409: {"description": "仍有分镜没有选用的视频"}},
)
def assemble_episode(episode_id: str, request: Request) -> TaskRecord:
    # 合成同样创建新执行任务，不能成为绕过生产门禁的旁路。
    block_legacy_episode_creation(request)
    return request.app.state.services.production.assemble(episode_id, request.state.trace_id)
