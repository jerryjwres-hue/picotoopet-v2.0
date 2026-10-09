"""Deterministic quality checks for Windows production evidence."""

from __future__ import annotations

from .models import (
    ProductionExecutionBackend,
    ProductionTaskCommitRequest,
    ProductionTaskPlan,
)
from .profile import MAX_FPS, MAX_FRAME_COUNT, MAX_HEIGHT, MAX_WIDTH, MIN_HEIGHT, MIN_WIDTH


def validate_task_commit(task: ProductionTaskPlan, request: ProductionTaskCommitRequest) -> None:
    """Reject executor evidence that diverges from the frozen plan."""

    # ── Dimensions and cadence must match the plan exactly ──────────────────
    if request.width != task.width or request.height != task.height:
        raise ValueError("PRODUCTION_OUTPUT_DIMENSION_MISMATCH")
    if request.fps != task.fps or request.frame_count != task.frame_count:
        raise ValueError("PRODUCTION_OUTPUT_TIMING_MISMATCH")
    if not (MIN_WIDTH <= request.width <= MAX_WIDTH and MIN_HEIGHT <= request.height <= MAX_HEIGHT):
        raise ValueError("PRODUCTION_OUTPUT_DIMENSION_OUT_OF_RANGE")
    if request.fps > MAX_FPS or request.frame_count > MAX_FRAME_COUNT:
        raise ValueError("PRODUCTION_OUTPUT_TIMING_OUT_OF_RANGE")

    # ── First formal profile produces WebM video only ───────────────────────
    if request.mime_type != "video/webm" or not request.output_relpath.lower().endswith(".webm"):
        raise ValueError("PRODUCTION_OUTPUT_MEDIA_TYPE_INVALID")

    # ── Prompt identity exists only for the Comfy execution plane ──────────
    if task.execution_backend is ProductionExecutionBackend.COMFY and not request.comfy_prompt_id:
        raise ValueError("PRODUCTION_PROMPT_ID_REQUIRED")
    if (
        task.execution_backend is ProductionExecutionBackend.LOCAL_MEDIA
        and request.comfy_prompt_id is not None
    ):
        raise ValueError("PRODUCTION_LOCAL_MEDIA_PROMPT_FORBIDDEN")
