from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest

from picotoopet_core.db.database import Database
from picotoopet_core.deep_ai.models import DeepAiHumanAction
from picotoopet_core.deep_ai.repository import DeepAiRepository


def _module(name: str):  # type: ignore[no-untyped-def]
    if importlib.util.find_spec(name) is None:
        pytest.fail(f"{name} is not implemented")
    return importlib.import_module(name)


def _database(tmp_path: Path) -> Database:
    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    return database


def _job(repository: DeepAiRepository):  # type: ignore[no-untyped-def]
    return repository.prepare_job(
        escalation_job_id=str(uuid4()),
        source_kind="business.local_intelligence",
        source_id="source-learning-001",
        source_digest="1" * 64,
        policy_version="deep-ai.escalation.v1",
        sanitized_package_relpath="runtime/deep-ai/requests/request.json",
        sanitized_package_digest="2" * 64,
        sanitizer_version="deep-ai.sanitizer.v1",
        provider_profile_id="paid.reasoning.v1",
        provider_profile_digest="3" * 64,
        model_id="gpt-5.6-terra",
        max_input_tokens=12000,
        max_output_tokens=4000,
        max_calls=2,
        max_cost_usd="0.50",
    )


def test_learning_ledger_records_validation_and_feedback_without_mutating_policy(tmp_path: Path) -> None:
    database = _database(tmp_path)
    try:
        repository = DeepAiRepository(database)
        job = _job(repository)
        before = repository.get_job(job.escalation_job_id)
        ledger_module = _module("picotoopet_core.deep_ai.learning")
        ledger = ledger_module.DeepAiLearningLedger(repository)

        validation = ledger.record_validation(
            idempotency_key="validation:source-learning-001:v1",
            project_key="pet-dryer-us",
            job=job,
            local_profile="reviews.voice_of_customer.v1",
            local_model_id="gpt-oss:20b",
            local_template_version="reviews.v1",
            local_attempt_count=2,
            local_quality_outcome="NEEDS_DEEP_AI",
            quality_reasons=["semantic uncertainty"],
            paid_output_digest="4" * 64,
            input_tokens=1000,
            output_tokens=500,
            cost_usd="0.01",
            paid_validation_outcome="PASS",
            downstream_ref="result-package-001",
        )
        feedback = ledger.record_feedback(
            idempotency_key="feedback:source-learning-001:accepted:v1",
            project_key="pet-dryer-us",
            job=job,
            action=DeepAiHumanAction.ACCEPTED,
            reason_tags=["useful", "grounded"],
            final_content_digest="5" * 64,
            downstream_ref="result-package-001",
        )

        assert validation.provider_profile_id == "paid.reasoning.v1"
        assert validation.provider_model_id == "gpt-5.6-terra"
        assert validation.sanitized_input_digest == "2" * 64
        assert validation.paid_output_digest == "4" * 64
        assert validation.input_tokens == 1000
        assert validation.output_tokens == 500
        assert str(validation.cost_usd) == "0.01"
        assert validation.human_action is DeepAiHumanAction.NO_DECISION
        assert feedback.human_action is DeepAiHumanAction.ACCEPTED

        after = repository.get_job(job.escalation_job_id)
        assert after.provider_profile_id == before.provider_profile_id
        assert after.provider_profile_digest == before.provider_profile_digest
        assert after.model_id == before.model_id
        assert after.max_calls == before.max_calls
        assert after.max_cost_usd == before.max_cost_usd
        assert repository.list_attempts(job.escalation_job_id) == []
        assert len(repository.list_learning_events(project_key="pet-dryer-us")) == 2
    finally:
        database.close()


def test_learning_event_idempotency_rejects_content_rewrite(tmp_path: Path) -> None:
    database = _database(tmp_path)
    try:
        repository = DeepAiRepository(database)
        job = _job(repository)
        ledger_module = _module("picotoopet_core.deep_ai.learning")
        ledger = ledger_module.DeepAiLearningLedger(repository)
        ledger.record_feedback(
            idempotency_key="feedback:immutable:v1",
            project_key="pet-dryer-us",
            job=job,
            action=DeepAiHumanAction.MODIFIED,
            reason_tags=["tone"],
            final_content_digest="6" * 64,
            downstream_ref=None,
        )
        with pytest.raises(ValueError, match="DEEP_AI_LEARNING_EVENT_IMMUTABLE"):
            ledger.record_feedback(
                idempotency_key="feedback:immutable:v1",
                project_key="pet-dryer-us",
                job=job,
                action=DeepAiHumanAction.REJECTED,
                reason_tags=["wrong"],
                final_content_digest="7" * 64,
                downstream_ref=None,
            )
    finally:
        database.close()
