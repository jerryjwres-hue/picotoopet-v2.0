from __future__ import annotations

import importlib
import importlib.util
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from picotoopet_core.config.paths import RuntimePaths
from picotoopet_core.db.database import Database
from picotoopet_core.deep_ai.models import DeepAiEscalationStatus
from picotoopet_core.deep_ai.provider import DeepAiProviderResultStore, ProviderResponse
from picotoopet_core.deep_ai.repository import DeepAiRepository
from picotoopet_core.deep_ai.sanitizer import DeepAiSourceContext


def _module(name: str):  # type: ignore[no-untyped-def]
    if importlib.util.find_spec(name) is None:
        pytest.fail(f"{name} is not implemented")
    return importlib.import_module(name)


class FakeResolver:
    def __init__(self, *, required: str = "findings") -> None:
        self.required = required

    def resolve(self, source_kind: str, source_id: str) -> DeepAiSourceContext:
        return DeepAiSourceContext(
            source_kind=source_kind,
            source_id=source_id,
            source_digest="1" * 64,
            project_key="pet-dryer-us",
            source_profile="reviews.voice_of_customer.v1",
            quality_outcome="NEEDS_DEEP_AI",
            quality_reasons=["semantic uncertainty"],
            evidence_snippets=["bounded evidence"],
            local_result_digest="2" * 64,
            return_schema={"type": "object", "required": [self.required]},
            manual_handoff_id="handoff-001",
            manual_handoff_digest="3" * 64,
        )


class FakeContinuation:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def apply_pass(self, *, job, output, output_digest):  # type: ignore[no-untyped-def]
        self.calls.append(output_digest)
        return "downstream-result-001"


def _database(tmp_path: Path) -> Database:
    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    return database


def _job(repository: DeepAiRepository):  # type: ignore[no-untyped-def]
    job = repository.prepare_job(
        escalation_job_id=str(uuid4()),
        source_kind="business.local_intelligence",
        source_id="source-processor-001",
        source_digest="1" * 64,
        policy_version="deep-ai.escalation.v1",
        sanitized_package_relpath="runtime/deep-ai/requests/request.json",
        sanitized_package_digest="4" * 64,
        sanitizer_version="deep-ai.sanitizer.v1",
        provider_profile_id="paid.reasoning.v1",
        provider_profile_digest="5" * 64,
        model_id="gpt-5.6-terra",
        max_input_tokens=12000,
        max_output_tokens=4000,
        max_calls=2,
        max_cost_usd="0.50",
    )
    return repository.set_job_status(job.escalation_job_id, DeepAiEscalationStatus.VALIDATING)


def _bind_response(tmp_path: Path, repository: DeepAiRepository, job, output):  # type: ignore[no-untyped-def]
    paths = RuntimePaths.from_root(tmp_path / "runtime")
    paths.ensure()
    store = DeepAiProviderResultStore(paths)
    attempt_id = str(uuid4())
    repository.reserve_attempt(
        escalation_job_id=job.escalation_job_id,
        attempt_id=attempt_id,
        attempt_number=1,
        estimated_cost_usd="0.02",
    )
    response = ProviderResponse(
        provider_request_id="provider-request-processor-1",
        output=output,
        input_tokens=1000,
        output_tokens=500,
        actual_cost_usd=Decimal("0.01"),
        cost_source="calculated",
    )
    stored = store.save(attempt_id=attempt_id, response=response)
    repository.bind_attempt_result(
        attempt_id,
        provider_request_id=response.provider_request_id,
        response_digest=stored.digest,
        response_relpath=stored.relpath,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        actual_cost_usd=response.actual_cost_usd,
        cost_source=response.cost_source,
    )
    return store, stored


def test_pass_result_continues_once_records_learning_and_completes(tmp_path: Path) -> None:
    processor_module = _module("picotoopet_core.deep_ai.result_processing")
    learning_module = _module("picotoopet_core.deep_ai.learning")
    validation_module = _module("picotoopet_core.deep_ai.validation")
    database = _database(tmp_path)
    try:
        repository = DeepAiRepository(database)
        job = _job(repository)
        result_store, stored = _bind_response(
            tmp_path,
            repository,
            job,
            {"findings": [{"summary": "supported"}]},
        )
        continuation = FakeContinuation()
        processor = processor_module.DeepAiResultProcessor(
            repository=repository,
            result_store=result_store,
            source_resolver=FakeResolver(),
            validator=validation_module.DeepAiResultValidator(),
            continuation=continuation,
            learning=learning_module.DeepAiLearningLedger(repository),
        )
        completed = processor.process(job.escalation_job_id)
        assert completed.status.value == "Completed"
        assert completed.validation_outcome.value == "PASS"
        assert completed.accepted_result_digest == stored.digest
        assert completed.accepted_result_relpath == repository.list_attempts(job.escalation_job_id)[0].response_relpath
        assert len(continuation.calls) == 1
        learning = repository.list_learning_events(project_key="pet-dryer-us")
        assert len(learning) == 1

        repeated = processor.process(job.escalation_job_id)
        assert repeated.status.value == "Completed"
        assert len(continuation.calls) == 1
        assert len(repository.list_learning_events(project_key="pet-dryer-us")) == 1
        assert len(repository.list_attempts(job.escalation_job_id)) == 1
    finally:
        database.close()


def test_invalid_structure_needs_human_and_never_continues(tmp_path: Path) -> None:
    processor_module = _module("picotoopet_core.deep_ai.result_processing")
    learning_module = _module("picotoopet_core.deep_ai.learning")
    validation_module = _module("picotoopet_core.deep_ai.validation")
    database = _database(tmp_path)
    try:
        repository = DeepAiRepository(database)
        job = _job(repository)
        result_store, _ = _bind_response(tmp_path, repository, job, {"notes": "wrong shape"})
        continuation = FakeContinuation()
        processor = processor_module.DeepAiResultProcessor(
            repository=repository,
            result_store=result_store,
            source_resolver=FakeResolver(),
            validator=validation_module.DeepAiResultValidator(),
            continuation=continuation,
            learning=learning_module.DeepAiLearningLedger(repository),
        )
        result = processor.process(job.escalation_job_id)
        assert result.status.value == "NeedsHuman"
        assert result.validation_outcome.value == "NEEDS_HUMAN"
        assert continuation.calls == []
        assert len(repository.list_learning_events(project_key="pet-dryer-us")) == 1
    finally:
        database.close()


def test_forbidden_authority_rejects_and_never_continues(tmp_path: Path) -> None:
    processor_module = _module("picotoopet_core.deep_ai.result_processing")
    learning_module = _module("picotoopet_core.deep_ai.learning")
    validation_module = _module("picotoopet_core.deep_ai.validation")
    database = _database(tmp_path)
    try:
        repository = DeepAiRepository(database)
        job = _job(repository)
        result_store, _ = _bind_response(
            tmp_path,
            repository,
            job,
            {"findings": [], "tools": [{"type": "shell"}]},
        )
        continuation = FakeContinuation()
        processor = processor_module.DeepAiResultProcessor(
            repository=repository,
            result_store=result_store,
            source_resolver=FakeResolver(),
            validator=validation_module.DeepAiResultValidator(),
            continuation=continuation,
            learning=learning_module.DeepAiLearningLedger(repository),
        )
        result = processor.process(job.escalation_job_id)
        assert result.status.value == "Rejected"
        assert result.validation_outcome.value == "REJECT"
        assert continuation.calls == []
    finally:
        database.close()
