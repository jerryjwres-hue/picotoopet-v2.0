"""Authenticated read-only post-production routes (C007A narration plan)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from picotoopet_core.api.errors import ApiError
from picotoopet_core.postproduction.captions_overlay import (
    NOT_READY as TEXT_PRESENTATION_NOT_READY,
    CaptionOverlayPlanError,
    CaptionOverlayPlanResponse,
    CaptionOverlayPlanService,
)
from picotoopet_core.postproduction.narration import (
    NOT_READY,
    NarrationPlanError,
    NarrationPlanResponse,
    NarrationPlanService,
)
from picotoopet_core.security.auth import require_auth

router = APIRouter(dependencies=[Depends(require_auth)])

_STATUS = {NOT_READY: 409}
_MESSAGE = "Narration plan cannot be derived from the current Production facts."
_TEXT_STATUS = {TEXT_PRESENTATION_NOT_READY: 409}
_TEXT_MESSAGE = "Text presentation plan cannot be derived from the current Production facts."


@router.get(
    "/postproduction/production/{production_job_id}/narration-plan",
    response_model=NarrationPlanResponse,
)
def get_narration_plan(production_job_id: str, request: Request) -> NarrationPlanResponse:
    service = NarrationPlanService(request.app.state.services.production)
    try:
        return service.get_plan(production_job_id)
    except KeyError:
        raise ApiError(
            status_code=404,
            code="PRODUCTION_RESOURCE_NOT_FOUND",
            message="Production resource not found.",
            retryable=False,
        ) from None
    except NarrationPlanError as error:
        raise ApiError(
            status_code=_STATUS.get(error.code, 422),
            code=error.code,
            message=_MESSAGE,
            retryable=error.code == NOT_READY,
        ) from None


@router.get(
    "/postproduction/production/{production_job_id}/caption-overlay-plan",
    response_model=CaptionOverlayPlanResponse,
)
def get_caption_overlay_plan(
    production_job_id: str,
    request: Request,
) -> CaptionOverlayPlanResponse:
    # ── C008A2 is a read-only projection over existing durable Production facts. ──
    service = CaptionOverlayPlanService(request.app.state.services.production)
    try:
        return service.get_plan(production_job_id)
    except KeyError:
        raise ApiError(
            status_code=404,
            code="PRODUCTION_RESOURCE_NOT_FOUND",
            message="Production resource not found.",
            retryable=False,
        ) from None
    except CaptionOverlayPlanError as error:
        raise ApiError(
            status_code=_TEXT_STATUS.get(error.code, 422),
            code=error.code,
            message=_TEXT_MESSAGE,
            retryable=error.code == TEXT_PRESENTATION_NOT_READY,
        ) from None
