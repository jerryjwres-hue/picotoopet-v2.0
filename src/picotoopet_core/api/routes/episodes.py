"""剧集导入、审片视图和合成接口。"""

from fastapi import APIRouter, Depends, Request, Response
from starlette.concurrency import run_in_threadpool

from picotoopet_core.api.errors import ApiError
from picotoopet_core.domain.episode import (
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
    service = request.app.state.services.production
    created, inserted = await run_in_threadpool(service.create, episode, request.state.trace_id)
    if not inserted:
        response.status_code = 200
    return created


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
    return request.app.state.services.production.assemble(episode_id, request.state.trace_id)
