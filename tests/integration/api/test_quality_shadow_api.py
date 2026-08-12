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


def _accepted_candidate(client: TestClient, *, count: int = 60) -> str:
    services = client.app.state.services
    ledger = DeepAiLearningLedger(services.deep_ai_repository)
    for index in range(1, count + 1):
        source_id = f"quality-shadow-api-{index:03d}"
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
            idempotency_key=f"quality-shadow-api:validation:{index}:v1",
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
            idempotency_key=f"quality-shadow-api:feedback:{index}:v1",
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
    run = services.quality_evaluation.evaluate(snapshot.snapshot_id)
    candidate = next(
        item
        for item in services.quality_evaluation.list_candidates(
            evaluation_run_id=run.evaluation_run_id
        )
        if item.candidate_class == "PROMPT_REVIEW" and item.cohort_dimension is None
    )
    services.quality_evaluation.review_candidate(
        candidate.candidate_id,
        action="AcceptedForShadow",
        idempotency_key=f"quality-shadow-api:{candidate.candidate_id}:accepted:v1",
    )
    return candidate.candidate_id


def test_shadow_api_create_list_metrics_reconcile_and_review(tmp_path: Path) -> None:
    client, headers = _client(tmp_path)
    with client:
        candidate_id = _accepted_candidate(client)

        create_response = client.post(
            "/api/v1/deep-ai/shadow-runs",
            headers=headers,
            json={"candidate_id": candidate_id},
        )
        assert create_response.status_code == 201, create_response.text
        run = create_response.json()
        assert run["candidate_id"] == candidate_id
        assert run["shadow_profile_id"] == "quality.shadow.v1"
        assert run["split_version"] == "quality.shadow.split.v1"
        assert run["verdict"] == "Supported"

        list_response = client.get(
            f"/api/v1/deep-ai/shadow-runs?candidate_id={candidate_id}",
            headers=headers,
        )
        assert list_response.status_code == 200, list_response.text
        assert [item["shadow_run_id"] for item in list_response.json()] == [run["shadow_run_id"]]

        metrics_response = client.get(
            f"/api/v1/deep-ai/shadow-runs/{run['shadow_run_id']}/metrics",
            headers=headers,
        )
        assert metrics_response.status_code == 200, metrics_response.text
        metrics = metrics_response.json()
        assert {item["arm"] for item in metrics} == {"baseline", "shadow"}
        assert all("numerator" in item and "denominator" in item for item in metrics)

        reconcile_response = client.post(
            f"/api/v1/deep-ai/shadow-runs/{run['shadow_run_id']}/reconcile",
            headers=headers,
            json={},
        )
        assert reconcile_response.status_code == 200, reconcile_response.text
        assert reconcile_response.json()["shadow_run_id"] == run["shadow_run_id"]
        assert reconcile_response.json()["report_digest"] == run["report_digest"]

        review_response = client.post(
            f"/api/v1/deep-ai/shadow-runs/{run['shadow_run_id']}/review",
            headers=headers,
            json={
                "action": "AcceptedForPromotionReview",
                "idempotency_key": f"quality-shadow-api:{run['shadow_run_id']}:promotion:v1",
            },
        )
        assert review_response.status_code == 201, review_response.text
        assert review_response.json()["action"] == "AcceptedForPromotionReview"
        # Zero-execution gate      API shadow work cannot reserve or submit paid attempts.
        assert client.app.state.services.database.scalar("SELECT COUNT(*) FROM deep_ai_attempts") == 0


def test_shadow_api_rejects_policy_split_and_execution_injection(tmp_path: Path) -> None:
    client, headers = _client(tmp_path)
    with client:
        candidate_id = _accepted_candidate(client, count=5)
        forbidden_fields = {
            "prompt": "rewrite this",
            "model": "attacker-model",
            "endpoint": "https://evil.invalid/v1",
            "api_key": "secret",
            "provider_key": "secret",
            "budget": 999,
            "temperature": 1,
            "tools": [{"type": "shell"}],
            "command": "powershell.exe",
            "shell": "bash",
            "path": "/tmp/raw.json",
            "workflow": {"nodes": []},
            "sql": "SELECT * FROM secrets",
            "formula": "acceptance_rate * 999",
            "threshold": 0.01,
            "split": "attacker-controlled",
            "seed": 1234,
        }
        for field, value in forbidden_fields.items():
            response = client.post(
                "/api/v1/deep-ai/shadow-runs",
                headers=headers,
                json={"candidate_id": candidate_id, field: value},
            )
            # Input boundary gate    Caller cannot change the closed shadow experiment contract.
            assert response.status_code == 422, (field, response.text)


def test_shadow_api_requires_authentication(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    with client:
        assert client.get("/api/v1/deep-ai/shadow-runs").status_code == 401
