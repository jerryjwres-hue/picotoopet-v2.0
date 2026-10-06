from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from picotoopet_core.production.models import (
    ProductionTaskCommitRequest,
    ProductionTaskPlan,
)
from picotoopet_core.production.quality import validate_task_commit


def _plan(**updates: object) -> ProductionTaskPlan:
    payload: dict[str, object] = {
        "production_task_id": str(uuid4()),
        "shot_id": "shot-001",
        "order": 1,
        "render_intent": "TEXT_CARD",
        "execution_disposition": "Executable",
        "execution_backend": "local_media",
        "execution_profile_id": "production.local.text-card.v1",
        "workflow_id": None,
        "local_media": {
            "text_digest": "f65fb5a5c36901382688e08b4211c85d7bec28acd61049fef5e2e2e24c1eec1f",
            "text_content": "Save time with gentle airflow.",
            "text_profile_id": "production.local.text-card.v1",
        },
        "positive_prompt": "text card",
        "negative_prompt_policy_id": "wan22.safe-negative.v1",
        "seed": 123,
        "width": 832,
        "height": 480,
        "fps": 24,
        "frame_count": 73,
        "target_duration_ms": 3000,
        "trusted_input_asset_ref": None,
    }
    payload.update(updates)
    return ProductionTaskPlan.model_validate(payload)


def _commit(**updates: object) -> ProductionTaskCommitRequest:
    payload: dict[str, object] = {
        "executor_id": "pc-gpu-1",
        "lease_token": "a" * 32,
        "comfy_prompt_id": None,
        "output_relpath": "PicotooPet/production/job/001-shot.webm",
        "output_sha256": "c" * 64,
        "output_bytes": 4096,
        "mime_type": "video/webm",
        "width": 832,
        "height": 480,
        "frame_count": 73,
        "fps": 24,
    }
    payload.update(updates)
    return ProductionTaskCommitRequest.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("execution_backend", "shell"),
        ("execution_profile_id", "production.local.custom.v1"),
    ],
)
def test_unknown_execution_backend_or_profile_is_rejected(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        _plan(**{field: value})


def test_local_media_payload_rejects_text_digest_mismatch_and_extra_authority() -> None:
    with pytest.raises(ValidationError):
        _plan(
            local_media={
                "text_digest": "0" * 64,
                "text_content": "Save time with gentle airflow.",
                "text_profile_id": "production.local.text-card.v1",
            }
        )
    with pytest.raises(ValidationError):
        _plan(
            local_media={
                "text_digest": "f65fb5a5c36901382688e08b4211c85d7bec28acd61049fef5e2e2e24c1eec1f",
                "text_content": "Save time with gentle airflow.",
                "text_profile_id": "production.local.text-card.v1",
                "font_path": "C:/Windows/Fonts/custom.ttf",
            }
        )


def test_local_media_commit_accepts_null_prompt_and_rejects_fake_prompt() -> None:
    validate_task_commit(_plan(), _commit())

    with pytest.raises(ValueError, match="PRODUCTION_LOCAL_MEDIA_PROMPT_FORBIDDEN"):
        validate_task_commit(_plan(), _commit(comfy_prompt_id="fake-local-prompt"))


def test_comfy_commit_still_requires_prompt_identity() -> None:
    comfy = _plan(
        render_intent="GENERATIVE_VIDEO",
        execution_backend="comfy",
        execution_profile_id="comfy.wan22.ti2v5b.t2v.v1",
        workflow_id="comfy.wan22.ti2v5b.t2v.v1",
        local_media=None,
    )

    with pytest.raises(ValueError, match="PRODUCTION_PROMPT_ID_REQUIRED"):
        validate_task_commit(comfy, _commit())
