from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from picotoopet_core.api.app import create_app
from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths
from picotoopet_core.deep_ai.learning import DeepAiLearningLedger
from picotoopet_core.deep_ai.models import DeepAiHumanAction


def _client(tmp_path: Path) -> tuple[TestClient, dict[str, str]]:
    token = "0123456789abcdef0123456789abcdef"
    settings = AppSettings(paths=RuntimePaths.from_root(tmp_path / "runtime"), api_token=token)
    return TestClient(create_app(settings)), {"Authorization": f"Bearer {token}"}


def _seed_learning(client: TestClient, *, count: int = 5) -> None:
    services = client.app.state.services
    ledger = DeepAiLearningLedger(services.deep_ai_repository)
    for index in range(1, count + 1):
        source_id = f"quality-evaluation-api-{index:03d}"
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
            idempotency_key=f"quality-evaluation-api:validation:{index}:v1",
            project_key="pet-dryer-us",
            job=job,
            local_profile="reviews.voice_of_customer.v1",
            local_model_id="gpt-oss:20b",
            local_template_version="reviews.v1",
            local_attempt_count=2,
            local_quality_outcome="NEEDS_DEEP_AI",
            quality_reasons=["semantic uncertainty"],
            paid_output_digest=uuid4().hex * 2,
            input_tokens=1000,
            output_tokens=500,
            cost_usd="0.35",
            paid_validation_outcome="PASS",
            downstream_ref=f"result-package-{index:03d}",
        )
        ledger.record_feedback(
            idempotency_key=f"quality-evaluation-api:feedback:{index}:v1",
            project_key="pet-dryer-us",
            job=job,
            action=(
                DeepAiHumanAction.REJECTED
                if index <= 2
                else DeepAiHumanAction.ACCEPTED
            ),
            reason_tags=["missing_evidence"] if index <= 3 else [],
            final_content_digest=uuid4().hex * 2,
            downstream_ref=f"result-package-{index:03d}",
        )


def test_quality_evaluation_api_snapshot_run_metrics_candidates_and_review(tmp_path: Path) -> None:
    client, headers = _client(tmp_path)
    with client:
        _seed_learning(client)

        snapshot_response = client.post(
            "/api/v1/deep-ai/evaluation-snapshots",
            headers=headers,
            json={
                "project_key": "pet-dryer-us",
                "evaluation_profile_id": "quality.offline.v1",
            },
        )
        assert snapshot_response.status_code == 201, snapshot_response.text
        snapshot = snapshot_response.json()
        assert snapshot["project_key"] == "pet-dryer-us"
        assert snapshot["member_count"] == 10

        run_response = client.post(
            "/api/v1/deep-ai/evaluations",
            headers=headers,
            json={"snapshot_id": snapshot["snapshot_id"]},
        )
        assert run_response.status_code == 201, run_response.text
        run = run_response.json()
        assert run["status"] == "Completed"

        metrics_response = client.get(
            f"/api/v1/deep-ai/evaluations/{run['evaluation_run_id']}/metrics",
            headers=headers,
        )
        assert metrics_response.status_code == 200, metrics_response.text
        metrics = {item["metric_name"]: item for item in metrics_response.json()}
        # Explicit ratio gate       The API must expose numerator/denominator, not only a rounded rate.
        assert metrics["human_rejected_or_modified_rate"]["numerator"] == 2
        assert metrics["human_rejected_or_modified_rate"]["denominator"] == 5

        candidates_response = client.get(
            f"/api/v1/deep-ai/improvement-candidates?evaluation_run_id={run['evaluation_run_id']}",
            headers=headers,
        )
        assert candidates_response.status_code == 200, candidates_response.text
        candidates = candidates_response.json()
        classes = {item["candidate_class"] for item in candidates}
        assert "PROMPT_REVIEW" in classes
        assert "LOCAL_REASONING_REVIEW" in classes
        assert "EVIDENCE_SELECTION_REVIEW" in classes
        assert "COST_POLICY_REVIEW" in classes

        candidate = candidates[0]
        review_response = client.post(
            f"/api/v1/deep-ai/improvement-candidates/{candidate['candidate_id']}/review",
            headers=headers,
            json={
                "action": "AcceptedForShadow",
                "idempotency_key": f"review:{candidate['candidate_id']}:shadow:v1",
            },
        )
        assert review_response.status_code == 201, review_response.text
        assert review_response.json()["action"] == "AcceptedForShadow"


def test_quality_evaluation_api_rejects_runtime_policy_and_formula_injection(tmp_path: Path) -> None:
    client, headers = _client(tmp_path)
    with client:
        _seed_learning(client, count=1)
        forbidden_fields = {
            "prompt": "rewrite this",
            "prompt_template": "attacker-template",
            "endpoint": "https://evil.invalid/v1",
            "url": "https://evil.invalid/v1",
            "model": "attacker-model",
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
        }
        for field, value in forbidden_fields.items():
            response = client.post(
                "/api/v1/deep-ai/evaluation-snapshots",
                headers=headers,
                json={
                    "project_key": "pet-dryer-us",
                    "evaluation_profile_id": "quality.offline.v1",
                    field: value,
                },
            )
            # Input boundary gate    Every execution/policy/formula override is rejected before evaluation.
            assert response.status_code == 422, (field, response.text)


def test_quality_evaluation_api_requires_authentication(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    with client:
        assert client.get("/api/v1/deep-ai/evaluation-snapshots").status_code == 401
