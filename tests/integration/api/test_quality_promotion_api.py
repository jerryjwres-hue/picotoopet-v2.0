from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from picotoopet_core.api.app import create_app
from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths
from picotoopet_core.deep_ai.evaluation import QualityEvaluationScope
from picotoopet_core.deep_ai.learning import DeepAiLearningLedger
from picotoopet_core.deep_ai.models import DeepAiHumanAction


def _client(tmp_path: Path) -> tuple[TestClient, dict[str, str]]:
    token = "0123456789abcdef0123456789abcdef"
    settings = AppSettings(paths=RuntimePaths.from_root(tmp_path / "runtime"), api_token=token)
    return TestClient(create_app(settings)), {"Authorization": f"Bearer {token}"}


def _promotion_ready_shadow(client: TestClient) -> str:
    services = client.app.state.services
    ledger = DeepAiLearningLedger(services.deep_ai_repository)
    for index in range(1, 61):
        source_id = f"quality-promotion-api-{index:03d}"
        job = services.deep_ai_repository.prepare_job(
            escalation_job_id=str(uuid4()),
            source_kind="business.local_intelligence",
            source_id=source_id,
            source_digest=uuid4().hex * 2,
            policy_version="deep-ai.escalation.v1",
            sanitized_package_relpath=f"runtime/deep-ai/requests/{source_id}.json",
            sanitized_package_digest=uuid4().hex * 2,
            sanitizer_version="deep-ai.sanitizer.v1",
            provider_profile_id="paid.reasoning.v1",
            provider_profile_digest=uuid4().hex * 2,
            model_id="gpt-5.6-terra",
            max_input_tokens=12000,
            max_output_tokens=4000,
            max_calls=2,
            max_cost_usd="0.50",
        )
        ledger.record_validation(
            idempotency_key=f"quality-promotion-api:validation:{index}:v1",
            project_key="pet-dryer-us",
            job=job,
            local_profile="reviews.voice_of_customer.v1",
            local_model_id="gpt-oss:20b",
            local_template_version="reviews.v1",
            local_attempt_count=1,
            local_quality_outcome="PASS",
            quality_reasons=[],
            paid_output_digest=uuid4().hex * 2,
            input_tokens=100,
            output_tokens=50,
            cost_usd="0.10",
            paid_validation_outcome="PASS",
            downstream_ref=f"result-package-{index:03d}",
        )
        ledger.record_feedback(
            idempotency_key=f"quality-promotion-api:feedback:{index}:v1",
            project_key="pet-dryer-us",
            job=job,
            action=DeepAiHumanAction.REJECTED,
            reason_tags=[],
            final_content_digest=uuid4().hex * 2,
            downstream_ref=f"result-package-{index:03d}",
        )
    snapshot = services.quality_evaluation.create_snapshot(
        QualityEvaluationScope(project_key="pet-dryer-us")
    )
    evaluation_run = services.quality_evaluation.evaluate(snapshot.snapshot_id)
    candidate = next(
        item
        for item in services.quality_evaluation.list_candidates(
            evaluation_run_id=evaluation_run.evaluation_run_id
        )
        if item.candidate_class == "PROMPT_REVIEW" and item.cohort_dimension is None
    )
    services.quality_evaluation.review_candidate(
        candidate.candidate_id,
        action="AcceptedForShadow",
        idempotency_key=f"quality-promotion-api:{candidate.candidate_id}:shadow:v1",
    )
    shadow_run = services.quality_shadow.create(candidate.candidate_id)
    assert shadow_run.verdict == "Supported"
    services.quality_shadow.review(
        shadow_run.shadow_run_id,
        action="AcceptedForPromotionReview",
        idempotency_key=f"quality-promotion-api:{shadow_run.shadow_run_id}:promotion:v1",
    )
    return shadow_run.shadow_run_id


def test_promotion_api_create_exact_activation_and_read_history(tmp_path: Path) -> None:
    client, headers = _client(tmp_path)
    with client:
        shadow_run_id = _promotion_ready_shadow(client)

        create_response = client.post(
            "/api/v1/deep-ai/promotions",
            headers=headers,
            json={"shadow_run_id": shadow_run_id},
        )
        assert create_response.status_code == 201, create_response.text
        promotion = create_response.json()
        assert promotion["shadow_run_id"] == shadow_run_id
        assert promotion["promotion_profile_id"] == "quality.promotion.v1"
        assert promotion["version_no"] == 1
        assert promotion["status"] == "AwaitingApproval"

        request_response = client.get(
            f"/api/v1/deep-ai/promotions/{promotion['promotion_id']}/activation-request",
            headers=headers,
        )
        assert request_response.status_code == 200, request_response.text
        request = request_response.json()
        assert request["approval_kind"] == "PromotionActivation"
        assert request["status"] == "Pending"

        decision_response = client.post(
            f"/api/v1/deep-ai/promotions/{promotion['promotion_id']}/activation-decision",
            headers=headers,
            json={
                "decision": "Approved",
                "request_digest": request["request_digest"],
                "idempotency_key": f"api:activate:{promotion['promotion_id']}:v1",
            },
        )
        assert decision_response.status_code == 200, decision_response.text
        assert decision_response.json()["status"] == "Active"

        history_response = client.get(
            f"/api/v1/deep-ai/promotions/{promotion['promotion_id']}/history",
            headers=headers,
        )
        assert history_response.status_code == 200, history_response.text
        history = history_response.json()
        assert len(history["decisions"]) == 1
        assert history["rollbacks"] == []
        # Zero-execution gate      Promotion API never creates or submits a paid attempt.
        assert client.app.state.services.database.scalar("SELECT COUNT(*) FROM deep_ai_attempts") == 0


def test_promotion_api_rollback_uses_closed_reason_and_exact_digest(tmp_path: Path) -> None:
    client, headers = _client(tmp_path)
    with client:
        shadow_run_id = _promotion_ready_shadow(client)
        promotion = client.post(
            "/api/v1/deep-ai/promotions",
            headers=headers,
            json={"shadow_run_id": shadow_run_id},
        ).json()
        activation = client.get(
            f"/api/v1/deep-ai/promotions/{promotion['promotion_id']}/activation-request",
            headers=headers,
        ).json()
        activate_response = client.post(
            f"/api/v1/deep-ai/promotions/{promotion['promotion_id']}/activation-decision",
            headers=headers,
            json={
                "decision": "Approved",
                "request_digest": activation["request_digest"],
                "idempotency_key": f"api:activate:{promotion['promotion_id']}:v1",
            },
        )
        assert activate_response.status_code == 200, activate_response.text

        rollback_response = client.post(
            f"/api/v1/deep-ai/promotions/{promotion['promotion_id']}/rollback-request",
            headers=headers,
            json={"rollback_reason_code": "OperatorDecision"},
        )
        assert rollback_response.status_code == 201, rollback_response.text
        rollback_request = rollback_response.json()
        assert rollback_request["approval_kind"] == "PromotionRollback"
        assert rollback_request["rollback_reason_code"] == "OperatorDecision"

        rollback_decision = client.post(
            f"/api/v1/deep-ai/promotions/{promotion['promotion_id']}/rollback-decision",
            headers=headers,
            json={
                "decision": "Approved",
                "request_digest": rollback_request["request_digest"],
                "idempotency_key": f"api:rollback:{promotion['promotion_id']}:v1",
            },
        )
        assert rollback_decision.status_code == 200, rollback_decision.text
        assert rollback_decision.json()["status"] == "RolledBack"


def test_promotion_api_rejects_executable_policy_injection(tmp_path: Path) -> None:
    client, headers = _client(tmp_path)
    with client:
        shadow_run_id = _promotion_ready_shadow(client)
        forbidden_fields = {
            "prompt": "rewrite this",
            "model": "attacker-model",
            "provider": "attacker-provider",
            "endpoint": "https://evil.invalid/v1",
            "api_key": "secret",
            "budget": 999,
            "temperature": 1,
            "tools": [{"type": "shell"}],
            "command": "powershell.exe",
            "shell": "bash",
            "path": "/tmp/raw.json",
            "workflow": {"nodes": []},
            "sql": "SELECT * FROM secrets",
            "formula": "score * 999",
            "threshold": 0.01,
            "version_no": 999,
            "slot_key": "attacker-slot",
            "patch": {"runtime": "mutate"},
        }
        for field, value in forbidden_fields.items():
            response = client.post(
                "/api/v1/deep-ai/promotions",
                headers=headers,
                json={"shadow_run_id": shadow_run_id, field: value},
            )
            assert response.status_code == 422, (field, response.text)


def test_promotion_api_requires_authentication(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    with client:
        assert client.get("/api/v1/deep-ai/promotions").status_code == 401
