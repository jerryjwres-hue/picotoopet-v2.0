from __future__ import annotations

import importlib
import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from picotoopet_core.db.database import Database


def _database(tmp_path: Path) -> Database:
    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    return database


def _repository_module():  # type: ignore[no-untyped-def]
    if importlib.util.find_spec("picotoopet_core.deep_ai.repository") is None:
        pytest.fail("2.3.22.1 deep_ai repository is not implemented")
    return importlib.import_module("picotoopet_core.deep_ai.repository")


def _models_module():  # type: ignore[no-untyped-def]
    if importlib.util.find_spec("picotoopet_core.deep_ai.models") is None:
        pytest.fail("2.3.22.1 deep_ai models are not implemented")
    return importlib.import_module("picotoopet_core.deep_ai.models")


def _prepare(repository, *, source_id: str, source_digest: str, job_id: str):  # type: ignore[no-untyped-def]
    return repository.prepare_job(
        escalation_job_id=job_id,
        source_kind="business.local_intelligence",
        source_id=source_id,
        source_digest=source_digest,
        policy_version="deep-ai.escalation.v1",
        sanitized_package_relpath=f"deep-ai/requests/{source_id}.json",
        sanitized_package_digest="a" * 64,
        sanitizer_version="deep-ai.sanitizer.v1",
        provider_profile_id="paid.reasoning.v1",
        provider_profile_digest="b" * 64,
        model_id="trusted-reasoning-model",
        max_input_tokens=12000,
        max_output_tokens=4000,
        max_calls=2,
        max_cost_usd="3.50",
    )


def test_migration_15_creates_deep_ai_tables(tmp_path: Path) -> None:
    database = _database(tmp_path)
    try:
        # Schema retention gate      Existing Deep-AI facts remain present through current schema 23.
        assert database.scalar("SELECT MAX(version) FROM schema_migrations") == 23
        tables = {
            row[0]
            for row in database.fetchall(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'deep_ai_%'"
            )
        }
        assert {
            "deep_ai_escalation_jobs",
            "deep_ai_attempts",
            "deep_ai_learning_events",
        } <= tables
    finally:
        database.close()


def test_prepare_is_idempotent_on_immutable_source_and_policy(tmp_path: Path) -> None:
    database = _database(tmp_path)
    try:
        repository = _repository_module().DeepAiRepository(database)
        source_id = str(uuid4())
        source_digest = "1" * 64
        first = _prepare(repository, source_id=source_id, source_digest=source_digest, job_id=str(uuid4()))
        repeated = _prepare(repository, source_id=source_id, source_digest=source_digest, job_id=str(uuid4()))
        assert repeated.escalation_job_id == first.escalation_job_id
        assert repeated.provider_profile_id == "paid.reasoning.v1"
        assert repeated.max_calls == 2
        assert str(repeated.max_cost_usd) == "3.50"
    finally:
        database.close()


def test_prepare_rejects_same_source_with_changed_frozen_envelope(tmp_path: Path) -> None:
    database = _database(tmp_path)
    try:
        repository = _repository_module().DeepAiRepository(database)
        source_id = str(uuid4())
        _prepare(repository, source_id=source_id, source_digest="2" * 64, job_id=str(uuid4()))
        with pytest.raises(ValueError, match="DEEP_AI_EXECUTION_ENVELOPE_IMMUTABLE"):
            repository.prepare_job(
                escalation_job_id=str(uuid4()),
                source_kind="business.local_intelligence",
                source_id=source_id,
                source_digest="2" * 64,
                policy_version="deep-ai.escalation.v1",
                sanitized_package_relpath=f"deep-ai/requests/{source_id}.json",
                sanitized_package_digest="a" * 64,
                sanitizer_version="deep-ai.sanitizer.v1",
                provider_profile_id="paid.reasoning.v1",
                provider_profile_digest="b" * 64,
                model_id="trusted-reasoning-model",
                max_input_tokens=12000,
                max_output_tokens=4000,
                max_calls=1,
                max_cost_usd="3.50",
            )
    finally:
        database.close()


def test_approval_identity_is_write_once(tmp_path: Path) -> None:
    database = _database(tmp_path)
    try:
        repository = _repository_module().DeepAiRepository(database)
        job = _prepare(
            repository,
            source_id=str(uuid4()),
            source_digest="3" * 64,
            job_id=str(uuid4()),
        )
        approval_id = str(uuid4())
        expires_at = datetime.now(UTC) + timedelta(hours=1)
        first = repository.bind_approval_once(
            job.escalation_job_id,
            approval_id=approval_id,
            approval_digest="c" * 64,
            approval_expires_at=expires_at,
        )
        assert first.approval_id == approval_id
        assert repository.bind_approval_once(
            job.escalation_job_id,
            approval_id=approval_id,
            approval_digest="c" * 64,
            approval_expires_at=expires_at,
        ).approval_id == approval_id
        with pytest.raises(ValueError, match="DEEP_AI_APPROVAL_IMMUTABLE"):
            repository.bind_approval_once(
                job.escalation_job_id,
                approval_id=str(uuid4()),
                approval_digest="d" * 64,
                approval_expires_at=expires_at,
            )
    finally:
        database.close()


def test_attempt_reservation_is_unique_and_usage_cannot_decrease(tmp_path: Path) -> None:
    database = _database(tmp_path)
    try:
        repository = _repository_module().DeepAiRepository(database)
        job = _prepare(
            repository,
            source_id=str(uuid4()),
            source_digest="4" * 64,
            job_id=str(uuid4()),
        )
        attempt = repository.reserve_attempt(
            escalation_job_id=job.escalation_job_id,
            attempt_id=str(uuid4()),
            attempt_number=1,
            estimated_cost_usd="1.20",
        )
        assert attempt.attempt_number == 1
        same = repository.reserve_attempt(
            escalation_job_id=job.escalation_job_id,
            attempt_id=attempt.attempt_id,
            attempt_number=1,
            estimated_cost_usd="1.20",
        )
        assert same.attempt_id == attempt.attempt_id
        with pytest.raises(ValueError, match="DEEP_AI_ATTEMPT_ALREADY_RESERVED"):
            repository.reserve_attempt(
                escalation_job_id=job.escalation_job_id,
                attempt_id=str(uuid4()),
                attempt_number=1,
                estimated_cost_usd="1.20",
            )

        repository.bind_attempt_result(
            attempt.attempt_id,
            provider_request_id="provider-request-001",
            response_digest="e" * 64,
            response_relpath="deep-ai/results/result-001.json",
            input_tokens=1000,
            output_tokens=500,
            actual_cost_usd="0.80",
            cost_source="calculated",
        )
        with pytest.raises(ValueError, match="DEEP_AI_USAGE_IMMUTABLE"):
            repository.bind_attempt_result(
                attempt.attempt_id,
                provider_request_id="provider-request-001",
                response_digest="e" * 64,
                response_relpath="deep-ai/results/result-001.json",
                input_tokens=999,
                output_tokens=500,
                actual_cost_usd="0.80",
                cost_source="calculated",
            )
    finally:
        database.close()


def test_learning_event_is_append_only_and_idempotent(tmp_path: Path) -> None:
    database = _database(tmp_path)
    try:
        repository = _repository_module().DeepAiRepository(database)
        model = _models_module()
        event_id = str(uuid4())
        first = repository.append_learning_event(
            event_id=event_id,
            idempotency_key="feedback:source-1:accepted:v1",
            project_key="pet-dryer-us",
            source_kind="business.local_intelligence",
            source_id="source-1",
            local_quality_outcome="NEEDS_DEEP_AI",
            escalation_job_id=None,
            human_action=model.DeepAiHumanAction.ACCEPTED,
            reason_tags=["useful", "grounded"],
            final_content_digest="f" * 64,
        )
        repeated = repository.append_learning_event(
            event_id=str(uuid4()),
            idempotency_key="feedback:source-1:accepted:v1",
            project_key="pet-dryer-us",
            source_kind="business.local_intelligence",
            source_id="source-1",
            local_quality_outcome="NEEDS_DEEP_AI",
            escalation_job_id=None,
            human_action=model.DeepAiHumanAction.ACCEPTED,
            reason_tags=["useful", "grounded"],
            final_content_digest="f" * 64,
        )
        assert repeated.event_id == first.event_id
        assert repository.list_learning_events(project_key="pet-dryer-us")[0].event_id == first.event_id
    finally:
        database.close()
