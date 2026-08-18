from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from picotoopet_core.api.app import create_app
from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths


def make_client(tmp_path: Path) -> tuple[TestClient, dict[str, str]]:
    token = "0123456789abcdef0123456789abcdef"
    settings = AppSettings(
        paths=RuntimePaths.from_root(tmp_path / "runtime"),
        api_token=token,
    )
    return TestClient(create_app(settings)), {"Authorization": f"Bearer {token}"}


def test_goal_center_exposes_bounded_templates_and_authenticated_human_goals(
    tmp_path: Path,
) -> None:
    client, headers = make_client(tmp_path)
    with client:
        assert client.get("/api/v1/autonomous/goals/templates").status_code == 401

        templates = client.get("/api/v1/autonomous/goals/templates", headers=headers)
        assert templates.status_code == 200
        body = templates.json()
        assert [item["goal_type"] for item in body] == [
            "product.research",
            "consumer.pain_points",
            "business.opportunity",
            "video.creative",
            "product.research_to_video",
        ]
        assert all(item["title"] and item["example"] for item in body)

        created = client.post(
            "/api/v1/autonomous/goals",
            headers={**headers, "Idempotency-Key": "goal-center-e2e-1"},
            json={
                "goal_type": "product.research_to_video",
                "objective": "研究大型犬耐咬玩具，找消费者痛点，并生成 TikTok AI 视频方案",
                "depth": "standard",
            },
        )
        assert created.status_code == 201
        goal = created.json()
        assert goal["origin"] == "human"
        assert goal["intent_type"] == "product.research_to_video"
        assert goal["priority_class"] == "P1"
        assert goal["status"] == "Ready"
        assert goal["constraints"] == {
            "depth": "standard",
            "external_ai_upload_requires_user_action": True,
            "read_only_research": True,
        }
        assert goal["budget_class"] == "local-first"
        assert goal["idempotency_key"] == "human:goal-center-e2e-1"

        replay = client.post(
            "/api/v1/autonomous/goals",
            headers={**headers, "Idempotency-Key": "goal-center-e2e-1"},
            json={
                "goal_type": "product.research_to_video",
                "objective": "研究大型犬耐咬玩具，找消费者痛点，并生成 TikTok AI 视频方案",
                "depth": "standard",
            },
        )
        assert replay.status_code == 201
        assert replay.json()["goal_id"] == goal["goal_id"]

        listed = client.get("/api/v1/autonomous/goals", headers=headers)
        assert listed.status_code == 200
        assert [item["goal_id"] for item in listed.json()] == [goal["goal_id"]]

        fetched = client.get(
            f"/api/v1/autonomous/goals/{goal['goal_id']}",
            headers=headers,
        )
        assert fetched.status_code == 200
        assert fetched.json()["objective"] == goal["objective"]


def test_goal_center_rejects_unknown_goal_types_and_cannot_set_system_priority(
    tmp_path: Path,
) -> None:
    client, headers = make_client(tmp_path)
    with client:
        unknown = client.post(
            "/api/v1/autonomous/goals",
            headers={**headers, "Idempotency-Key": "bad-goal"},
            json={
                "goal_type": "arbitrary.shell",
                "objective": "run anything",
                "depth": "standard",
            },
        )
        assert unknown.status_code == 422

        injected = client.post(
            "/api/v1/autonomous/goals",
            headers={**headers, "Idempotency-Key": "priority-injection"},
            json={
                "goal_type": "product.research",
                "objective": "研究一个产品",
                "depth": "quick",
                "priority_class": "P0",
                "origin": "system",
            },
        )
        assert injected.status_code == 422
