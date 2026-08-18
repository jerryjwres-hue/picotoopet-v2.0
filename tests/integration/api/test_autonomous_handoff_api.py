from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi.testclient import TestClient

from picotoopet_core.api.app import create_app
from picotoopet_core.autonomous.goal_handoff_access import GoalHandoffMetadata
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
