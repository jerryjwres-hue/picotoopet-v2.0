from __future__ import annotations

from uuid import uuid4

import pytest

from picotoopet_core.production.models import ProductionTaskCommitRequest, ProductionTaskPlan
from picotoopet_core.production.quality import validate_task_commit


def _task() -> ProductionTaskPlan:
    # ── Frozen executable task fixture ──────────────────────────────────────
    return ProductionTaskPlan(
        production_task_id=str(uuid4()),
        shot_id="shot-001",
        order=1,
        render_intent="GENERATIVE_VIDEO",
        execution_disposition="Executable",
        workflow_id="comfy.wan22.ti2v5b.t2v.v1",
        positive_prompt="subject; environment; action; framing; light; continuity; facts",
        negative_prompt_policy_id="wan22.safe-negative.v1",
        seed=123,
        width=832,
        height=480,
        fps=24,
        frame_count=81,
    )


def _result(**updates: object) -> ProductionTaskCommitRequest:
    # ── Bounded executor evidence fixture ───────────────────────────────────
    payload = {
        "executor_id": "pc-gpu-1",
        "lease_token": "a" * 32,
        "comfy_prompt_id": "prompt-1",
        "output_relpath": "output/picotoopet/job/shot-001.webm",
        "output_sha256": "c" * 64,
        "output_bytes": 4096,
        "mime_type": "video/webm",
        "width": 832,
        "height": 480,
        "frame_count": 81,
        "fps": 24,
    }
    payload.update(updates)
    return ProductionTaskCommitRequest(**payload)


def test_valid_task_commit_matches_frozen_plan() -> None:
    validate_task_commit(_task(), _result())


def test_output_path_must_be_relative_and_bounded() -> None:
    with pytest.raises(ValueError):
        _result(output_relpath="C:/Users/test/output.webm")
    with pytest.raises(ValueError):
        _result(output_relpath="../outside.webm")


def test_output_dimensions_and_media_type_must_match_plan() -> None:
    with pytest.raises(ValueError, match="PRODUCTION_OUTPUT_DIMENSION_MISMATCH"):
        validate_task_commit(_task(), _result(width=1024))
    with pytest.raises(ValueError, match="PRODUCTION_OUTPUT_MEDIA_TYPE_INVALID"):
        validate_task_commit(_task(), _result(mime_type="application/octet-stream"))
