from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from picotoopet_core.api.app import create_app
from picotoopet_core.api.errors import ApiError
from picotoopet_core.api.routes.autonomous_goals import (
    get_goal_video_return_status,
    submit_goal_video_return,
)
from picotoopet_core.autonomous.goal_handoff_access import GoalHandoffMetadata
from picotoopet_core.autonomous.video_continuation import (
    GoalVideoContinuationRecord,
    GoalVideoContinuationStateError,
)
from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths


def make_client(tmp_path: Path) -> tuple[TestClient, dict[str, str]]:
    token = "0123456789abcdef0123456789abcdef"
    settings = AppSettings(
        paths=RuntimePaths.from_root(tmp_path / "runtime"),
        api_token=token,
    )
    return TestClient(create_app(settings)), {"Authorization": f"Bearer {token}"}


def _create_video_goal(client: TestClient, headers: dict[str, str]) -> str:
    response = client.post(
        "/api/v1/autonomous/goals",
        headers={**headers, "Idempotency-Key": "handoff-api-goal"},
        json={
            "goal_type": "product.research_to_video",
            "objective": "研究产品并生成 AI 视频方案",
            "depth": "quick",
        },
    )
    assert response.status_code == 201
    return response.json()["goal_id"]


def test_handoff_routes_are_authenticated_and_report_not_ready(tmp_path: Path) -> None:
    client, headers = make_client(tmp_path)
    with client:
        goal_id = _create_video_goal(client, headers)
        path = f"/api/v1/autonomous/goals/{goal_id}/handoff"
        assert client.get(path).status_code == 401

        pending = client.get(path, headers=headers)
        assert pending.status_code == 409
        assert pending.json()["error"]["code"] == "AUTONOMOUS_HANDOFF_NOT_READY"


def test_handoff_routes_return_verified_metadata_download_and_fixed_prompt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client, headers = make_client(tmp_path)
    package = tmp_path / "verified.zip"
    package.write_bytes(b"zip-payload")
    digest = hashlib.sha256(package.read_bytes()).hexdigest()
    metadata = GoalHandoffMetadata(
        goal_id="goal-video-1",
        handoff_ready=True,
        package_name="goal-video-1.zip",
        package_sha256=digest,
        package_size_bytes=package.stat().st_size,
        prompt_version="web-gpt-master-v1.0",
        manual_web_gpt_upload_required=True,
    )

    class FakeAccess:
        def metadata(self, goal_id: str) -> GoalHandoffMetadata:
            assert goal_id == "goal-video-1"
            return metadata

        def verified_package(self, goal_id: str) -> Path:
            assert goal_id == "goal-video-1"
            return package

        def fixed_prompt(self, goal_id: str) -> str:
            assert goal_id == "goal-video-1"
            return "Prompt-Version: web-gpt-master-v1.0\nDO THE VIDEO WORK\n"

        def return_prompt(self, goal_id: str) -> str:
            assert goal_id == "goal-video-1"
            return (
                self.fixed_prompt(goal_id)
                + "PICOTOO_RETURN_JSON\n"
                + digest
            )

    monkeypatch.setattr(
        "picotoopet_core.api.routes.autonomous_goals._handoff_access",
        lambda request: FakeAccess(),
    )

    with client:
        base = "/api/v1/autonomous/goals/goal-video-1/handoff"
        response = client.get(base, headers=headers)
        assert response.status_code == 200
        assert response.json()["package_sha256"] == digest
        assert "path" not in response.json()

        downloaded = client.get(f"{base}/download", headers=headers)
        assert downloaded.status_code == 200
        assert downloaded.content == b"zip-payload"
        assert downloaded.headers["content-type"].startswith("application/zip")

        prompt = client.get(f"{base}/prompt", headers=headers)
        assert prompt.status_code == 200
        assert "Prompt-Version: web-gpt-master-v1.0" in prompt.text


def test_video_return_route_is_authenticated_and_uses_bounded_service(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client, headers = make_client(tmp_path)
    expected = GoalVideoContinuationRecord(
        goal_id="goal-video-1",
        handoff_sha256="a" * 64,
        return_sha256="b" * 64,
        creative_job_id="creative-job",
        creative_package_id="11111111-1111-4111-8111-111111111111",
        creative_package_digest="c" * 64,
        creative_status="creative_ready",
        production_job_id="production-job",
        production_status="Ready",
    )

    class FakeContinuation:
        def submit(self, goal_id, payload):  # type: ignore[no-untyped-def]
            assert goal_id == payload.goal_id == "goal-video-1"
            return expected

        def status(self, goal_id):  # type: ignore[no-untyped-def]
            assert goal_id == "goal-video-1"
            return expected

    monkeypatch.setattr(
        "picotoopet_core.api.routes.autonomous_goals._video_return_service",
        lambda request: FakeContinuation(),
    )
    payload = {
        "schema_version": "1.0",
        "goal_id": "goal-video-1",
        "handoff_sha256": "a" * 64,
        "prompt_version": "web-gpt-master-v1.0",
        "generated_at": "2026-10-05T12:00:00Z",
        "selected_direction": "idea-1",
        "reasoning_summary": "reason",
        "verified_fact_ids": [],
        "inference_summary": "inference",
        "creative_summary": "creative",
        "image_prompt_summary": "image",
        "video_prompt_summary": "video",
        "continuity_constraints": [],
        "unresolved_questions": [],
        "recommended_next_actions": [],
        "idea_ranking": {
            "schema_version": "1.0",
            "creative_profile": "creative.content_plan.v1",
            "ideas": [],
        },
        "creative_brief": {},
        "script": {},
        "shot_plan": {},
    }
    path = "/api/v1/autonomous/goals/goal-video-1/handoff/video-return"
    with client:
        assert client.post(path, json=payload).status_code == 401
        # Nested Creative schemas are strict and reject this deliberately incomplete fixture.
        assert client.post(path, headers=headers, json=payload).status_code == 422
        status_response = client.get(path, headers=headers)
        assert status_response.status_code == 200
        assert status_response.json()["production_job_id"] == "production-job"


def test_video_return_routes_bound_state_errors_and_hide_internal_conflicts(monkeypatch) -> None:
    class InvalidStateContinuation:
        def status(self, goal_id):  # type: ignore[no-untyped-def]
            raise GoalVideoContinuationStateError("GOAL_CREATIVE_PROVENANCE_INVALID")

        def submit(self, goal_id, payload):  # type: ignore[no-untyped-def]
            raise ValueError("CREATIVE_EXTERNAL_STAGE_CONFLICT secret-internal-detail")

    monkeypatch.setattr(
        "picotoopet_core.api.routes.autonomous_goals._video_return_service",
        lambda request: InvalidStateContinuation(),
    )

    with pytest.raises(ApiError) as status_error:
        get_goal_video_return_status("goal-video-1", object())  # type: ignore[arg-type]
    assert status_error.value.status_code == 409
    assert status_error.value.code == "AUTONOMOUS_VIDEO_RETURN_STATE_INVALID"
    assert "GOAL_CREATIVE_PROVENANCE_INVALID" not in status_error.value.message

    with pytest.raises(ApiError) as submit_error:
        submit_goal_video_return("goal-video-1", object(), object())  # type: ignore[arg-type]
    assert submit_error.value.status_code == 409
    assert submit_error.value.code == "AUTONOMOUS_VIDEO_RETURN_CONFLICT"
    assert submit_error.value.retryable is False
    assert "CREATIVE_EXTERNAL_STAGE_CONFLICT" not in submit_error.value.message


def test_video_return_submit_missing_projection_is_retryable_bounded_state(monkeypatch) -> None:
    class PendingContinuation:
        def submit(self, goal_id, payload):  # type: ignore[no-untyped-def]
            raise KeyError(goal_id)

    monkeypatch.setattr(
        "picotoopet_core.api.routes.autonomous_goals._video_return_service",
        lambda request: PendingContinuation(),
    )

    with pytest.raises(ApiError) as error:
        submit_goal_video_return("goal-video-1", object(), object())  # type: ignore[arg-type]
    assert error.value.status_code == 409
    assert error.value.code == "AUTONOMOUS_VIDEO_RETURN_STATE_PENDING"
    assert error.value.retryable is True
