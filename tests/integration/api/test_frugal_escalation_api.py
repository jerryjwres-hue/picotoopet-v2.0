from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from picotoopet_core.api.app import create_app
from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths
from picotoopet_core.deep_ai.frugal import FrugalAssessmentSignals
from picotoopet_core.providers.models import ProviderUsageStatus


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


def test_frugal_decision_get_is_authenticated_read_only_and_does_not_spend(tmp_path: Path) -> None:
    client, headers = _client(tmp_path)
    with client:
        services = client.app.state.services
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
