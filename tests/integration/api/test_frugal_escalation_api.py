from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from picotoopet_core.api.app import create_app
from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths
from picotoopet_core.deep_ai.frugal import FrugalAssessmentSignals
from picotoopet_core.providers.models import ProviderReadinessStatus, ProviderUsageStatus
from picotoopet_core.providers.readiness import ProviderReadinessProjection


def _client(tmp_path: Path) -> tuple[TestClient, dict[str, str]]:
    token = "0123456789abcdef0123456789abcdef"
    settings = AppSettings(
        paths=RuntimePaths.from_root(tmp_path / "runtime"),
        api_token=token,
    )
    return TestClient(create_app(settings)), {"Authorization": f"Bearer {token}"}


def _signals() -> FrugalAssessmentSignals:
    return FrugalAssessmentSignals(
        contract_valid=True,
        validation_passed=False,
        coverage=0.70,
        contradiction_rate=0.10,
        model_confidence=0.65,
        risk_score=0.30,
        retry_count=0,
    )


def _publish_ready_providers(client: TestClient) -> None:
    projection = ProviderReadinessProjection(client.app.state.services.capability_router)
    projection.publish(
        worker_id="frugal-api-worker",
        provider="codex",
        status=ProviderReadinessStatus.READY,
        task_type="provider.codex.handoff-v1",
    )
    projection.publish(
        worker_id="frugal-api-worker",
        provider="claude_code",
        status=ProviderReadinessStatus.READY,
        task_type="provider.claude-code.handoff-v1",
    )


def _approve_handoff(client: TestClient, handoff_id: str) -> None:
    database = client.app.state.services.database
    row = database.fetchone(
        "SELECT preview_json FROM handoffs WHERE handoff_id = ?",
        (handoff_id,),
    )
    assert row is not None
    preview = json.loads(row["preview_json"])
    preview["status"] = "approved"
    database.execute(
        "UPDATE handoffs SET status = ?, preview_json = ? WHERE handoff_id = ?",
        (
            "approved",
            json.dumps(preview, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            handoff_id,
        ),
    )


def test_create_coding_escalation_accepts_only_high_level_goal_and_is_replay_safe(
    tmp_path: Path,
) -> None:
    client, headers = _client(tmp_path)
    request_headers = {**headers, "Idempotency-Key": "coding-goal-create-001"}
    payload = {
        "title": "修复受控仓库回归",
        "objective": "先使用本地事实判断是否需要外部 Coding AI；禁止发布改动。",
    }

    with client:
        _publish_ready_providers(client)
        created = client.post(
            "/api/v1/coding-escalations",
            headers=request_headers,
            json=payload,
        )
        handoff_count = client.app.state.services.database.scalar(
            "SELECT COUNT(*) FROM handoffs"
        )
        session_count = client.app.state.services.database.scalar(
            "SELECT COUNT(*) FROM provider_sessions"
        )
        replay = client.post(
            "/api/v1/coding-escalations",
            headers=request_headers,
            json=payload,
        )
        replay_handoff_count = client.app.state.services.database.scalar(
            "SELECT COUNT(*) FROM handoffs"
        )
        replay_session_count = client.app.state.services.database.scalar(
            "SELECT COUNT(*) FROM provider_sessions"
        )

    assert created.status_code == 201
    body = created.json()
    assert body["decision"]["task_class"] == "repository_maintenance"
    assert body["decision"]["chosen_provider"] == "codex"
    assert body["decision"]["confidence_lower"] < 0.62
    assert body["stage"] == "awaiting_handoff_approval"
    assert body["handoff_id"] is not None
    source_id = body["decision"]["goal_id"]
    assert source_id != body["handoff_id"]
    assert handoff_count == 2  # one manual source fact + one Core-selected provider handoff
    assert session_count == 0
    assert replay.status_code == 201
    assert replay.json() == body
    assert replay_handoff_count == handoff_count
    assert replay_session_count == 0


def test_create_coding_escalation_rejects_client_authority_fields(tmp_path: Path) -> None:
    client, headers = _client(tmp_path)
    with client:
        response = client.post(
            "/api/v1/coding-escalations",
            headers={**headers, "Idempotency-Key": "coding-goal-create-authority"},
            json={
                "title": "客户端不得选 Provider",
                "objective": "验证权限边界。",
                "provider": "claude_code",
                "budget": {"max_turns": 99},
                "signals": {"validation_passed": True},
                "task_class": "repository_maintenance",
            },
        )
        operation = client.get("/openapi.json").json()["paths"][
            "/api/v1/coding-escalations"
        ]["post"]

    assert response.status_code == 422
    schema_ref = operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    assert schema_ref.endswith("/CodingEscalationCreateRequest")
    assert "provider" not in json.dumps(operation).lower()
    assert "budget" not in json.dumps(operation).lower()
    assert "signals" not in json.dumps(operation).lower()


def test_frugal_decision_get_is_authenticated_read_only_and_does_not_spend(tmp_path: Path) -> None:
    client, headers = _client(tmp_path)
    with client:
        services = client.app.state.services
        _publish_ready_providers(client)
        plan = services.coding_escalation.evaluate(
            goal_id="goal-frugal-api",
            task_class="repository_maintenance",
            title="Bounded repository repair",
            objective="Repair one bounded issue without publishing changes.",
            signals=_signals(),
        )
        assert plan.handoff_id is not None
        _approve_handoff(client, plan.handoff_id)
        services.provider_sessions.confirm_usage(
            plan.handoff_id,
            ProviderUsageStatus.CONFIRMED_AVAILABLE,
            idempotency_key="frugal-api-usage",
        )

        unauthenticated = client.get(
            "/api/v1/coding-escalations/goal-frugal-api/decision"
        )
        before = services.database.scalar("SELECT COUNT(*) FROM provider_sessions")
        response = client.get(
            "/api/v1/coding-escalations/goal-frugal-api/decision",
            headers=headers,
        )
        after = services.database.scalar("SELECT COUNT(*) FROM provider_sessions")

    assert unauthenticated.status_code == 401
    assert response.status_code == 200
    body = response.json()
    assert body["goal_id"] == "goal-frugal-api"
    assert body["decision"]["task_class"] == "repository_maintenance"
    assert body["decision"]["chosen_provider"] == "codex"
    assert body["decision"]["policy_version"]
    assert len(body["decision_digest"]) == 64
    assert before == 0
    assert after == 0


def test_frugal_decision_get_has_no_provider_budget_or_model_override_surface(tmp_path: Path) -> None:
    client, headers = _client(tmp_path)
    with client:
        missing = client.get(
            "/api/v1/coding-escalations/missing-goal/decision",
            headers=headers,
        )
        operation = client.get("/openapi.json").json()["paths"][
            "/api/v1/coding-escalations/{goal_id}/decision"
        ]

    assert missing.status_code == 404
    assert set(operation) == {"get"}
    get_operation = operation["get"]
    assert "requestBody" not in get_operation
    parameter_names = {item["name"] for item in get_operation.get("parameters", [])}
    assert parameter_names == {"goal_id"}
    for forbidden in ("provider", "model", "budget", "argv", "command", "worktree"):
        assert forbidden not in parameter_names
