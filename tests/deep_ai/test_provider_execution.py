from __future__ import annotations

import hashlib
import importlib
import importlib.util
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from picotoopet_core.config.paths import RuntimePaths
from picotoopet_core.db.database import Database
from picotoopet_core.deep_ai.repository import DeepAiRepository


REQUEST_BYTES = b'{"schema_version":"1.0","instruction_template_id":"deep-ai.reasoning.v1"}'
REQUEST_DIGEST = hashlib.sha256(REQUEST_BYTES).hexdigest()


def _module(name: str):  # type: ignore[no-untyped-def]
    if importlib.util.find_spec(name) is None:
        pytest.fail(f"{name} is not implemented")
    return importlib.import_module(name)


def _database(tmp_path: Path) -> Database:
    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    return database


def _job(repository: DeepAiRepository, *, max_cost: str = "3.50", max_calls: int = 2):  # type: ignore[no-untyped-def]
    job = repository.prepare_job(
        escalation_job_id=str(uuid4()),
        source_kind="business.local_intelligence",
        source_id=str(uuid4()),
        source_digest="1" * 64,
        policy_version="deep-ai.escalation.v1",
        sanitized_package_relpath="runtime/deep-ai/requests/request.json",
        sanitized_package_digest=REQUEST_DIGEST,
        sanitizer_version="deep-ai.sanitizer.v1",
        provider_profile_id="paid.reasoning.v1",
        provider_profile_digest="3" * 64,
        model_id="gpt-5.6-terra",
        max_input_tokens=12000,
        max_output_tokens=4000,
        max_calls=max_calls,
        max_cost_usd=max_cost,
    )
    repository.database.execute(
        "UPDATE deep_ai_escalation_jobs SET status='ProviderReady' WHERE escalation_job_id=?",
        (job.escalation_job_id,),
    )
    return repository.get_job(job.escalation_job_id)


class FakeProvider:
    def __init__(self, repository: DeepAiRepository, responses, estimates) -> None:  # type: ignore[no-untyped-def]
        self.repository = repository
        self.responses = list(responses)
        self.estimates = list(estimates)
        self.calls: list[tuple[str, bool]] = []
        self.reserved_before_submit: list[bool] = []
        self.reconciled: list[str] = []

    def estimate(self, *, request_bytes: bytes, repair: bool):  # type: ignore[no-untyped-def]
        provider_module = _module("picotoopet_core.deep_ai.provider")
        value = self.estimates[min(len(self.calls), len(self.estimates) - 1)]
        return provider_module.ProviderEstimate(
            input_tokens=value[0],
            output_tokens=value[1],
            cost_usd=Decimal(value[2]),
        )

    def execute(self, *, request_bytes: bytes, attempt_id: str, repair: bool):  # type: ignore[no-untyped-def]
        self.calls.append((attempt_id, repair))
        self.reserved_before_submit.append(
            self.repository.get_attempt(attempt_id).status.value == "Reserved"
        )
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def reconcile(self, attempt_id: str):  # type: ignore[no-untyped-def]
        self.reconciled.append(attempt_id)
        return None


def _response(*, request_id: str, structural_error: bool = False, semantic_failure: bool = False):  # type: ignore[no-untyped-def]
    provider_module = _module("picotoopet_core.deep_ai.provider")
    return provider_module.ProviderResponse(
        provider_request_id=request_id,
        output={"findings": [{"summary": "bounded result"}]},
        input_tokens=1000,
        output_tokens=500,
        actual_cost_usd=Decimal("0.010000"),
        cost_source="calculated",
        structural_error=structural_error,
        semantic_failure=semantic_failure,
    )


def _coordinator(tmp_path: Path, repository: DeepAiRepository, provider, *, enabled: bool):  # type: ignore[no-untyped-def]
    provider_module = _module("picotoopet_core.deep_ai.provider")
    execution_module = _module("picotoopet_core.deep_ai.execution")
    paths = RuntimePaths.from_root(tmp_path / "runtime")
    paths.ensure()
    request_store = provider_module.DeepAiProviderRequestReader(paths)
    result_store = provider_module.DeepAiProviderResultStore(paths)
    return execution_module.DeepAiExecutionCoordinator(
        repository=repository,
        provider=provider,
        request_reader=request_store,
        result_store=result_store,
        execution_enabled=enabled,
    )


def _write_request(tmp_path: Path) -> None:
    paths = RuntimePaths.from_root(tmp_path / "runtime")
    paths.ensure()
    target = paths.root / "runtime/deep-ai/requests/request.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(REQUEST_BYTES)


def test_disabled_executor_makes_zero_provider_calls(tmp_path: Path) -> None:
    database = _database(tmp_path)
    try:
        repository = DeepAiRepository(database)
        job = _job(repository)
        _write_request(tmp_path)
        provider = FakeProvider(repository, [_response(request_id="req-1")], [(1000, 500, "0.02")])
        coordinator = _coordinator(tmp_path, repository, provider, enabled=False)
        result = coordinator.execute(job.escalation_job_id)
        assert result.status.value == "Approved"
        assert provider.calls == []
    finally:
        database.close()


def test_attempt_is_reserved_before_submit_and_restart_does_not_duplicate_spend(tmp_path: Path) -> None:
    database = _database(tmp_path)
    try:
        repository = DeepAiRepository(database)
        job = _job(repository)
        _write_request(tmp_path)
        provider = FakeProvider(repository, [_response(request_id="req-1")], [(1000, 500, "0.02")])
        coordinator = _coordinator(tmp_path, repository, provider, enabled=True)
        first = coordinator.execute(job.escalation_job_id)
        assert first.status.value == "Validating"
        assert provider.reserved_before_submit == [True]
        assert len(provider.calls) == 1

        restarted_provider = FakeProvider(repository, [], [(1000, 500, "0.02")])
        restarted = _coordinator(tmp_path, repository, restarted_provider, enabled=True)
        second = restarted.execute(job.escalation_job_id)
        assert second.status.value == "Validating"
        assert restarted_provider.calls == []
        attempts = repository.list_attempts(job.escalation_job_id)
        assert [item.attempt_number for item in attempts] == [1]
    finally:
        database.close()


def test_structural_repair_is_capped_at_one_second_call(tmp_path: Path) -> None:
    database = _database(tmp_path)
    try:
        repository = DeepAiRepository(database)
        job = _job(repository)
        _write_request(tmp_path)
        provider = FakeProvider(
            repository,
            [
                _response(request_id="req-1", structural_error=True),
                _response(request_id="req-2"),
            ],
            [(1000, 500, "0.02"), (800, 400, "0.02")],
        )
        coordinator = _coordinator(tmp_path, repository, provider, enabled=True)
        result = coordinator.execute(job.escalation_job_id)
        assert result.status.value == "Validating"
        assert [repair for _, repair in provider.calls] == [False, True]
        assert [item.attempt_number for item in repository.list_attempts(job.escalation_job_id)] == [1, 2]

        assert coordinator.execute(job.escalation_job_id).status.value == "Validating"
        assert len(provider.calls) == 2
    finally:
        database.close()


def test_semantic_failure_does_not_consume_repair_call(tmp_path: Path) -> None:
    database = _database(tmp_path)
    try:
        repository = DeepAiRepository(database)
        job = _job(repository)
        _write_request(tmp_path)
        provider = FakeProvider(
            repository,
            [_response(request_id="req-semantic", semantic_failure=True)],
            [(1000, 500, "0.02")],
        )
        coordinator = _coordinator(tmp_path, repository, provider, enabled=True)
        result = coordinator.execute(job.escalation_job_id)
        assert result.status.value == "NeedsHuman"
        assert len(provider.calls) == 1
        assert len(repository.list_attempts(job.escalation_job_id)) == 1
    finally:
        database.close()


def test_budget_preflight_happens_before_every_call(tmp_path: Path) -> None:
    database = _database(tmp_path)
    try:
        repository = DeepAiRepository(database)
        job = _job(repository, max_cost="0.01")
        _write_request(tmp_path)
        provider = FakeProvider(repository, [_response(request_id="never")], [(1000, 500, "0.02")])
        coordinator = _coordinator(tmp_path, repository, provider, enabled=True)
        result = coordinator.execute(job.escalation_job_id)
        assert result.status.value == "NeedsHuman"
        assert result.failure_code == "DEEP_AI_BUDGET_PREFLIGHT_FAILED"
        assert provider.calls == []
        assert repository.list_attempts(job.escalation_job_id) == []
    finally:
        database.close()


def test_ambiguous_transport_without_reconciliation_never_spends_second_time(tmp_path: Path) -> None:
    database = _database(tmp_path)
    try:
        repository = DeepAiRepository(database)
        job = _job(repository)
        _write_request(tmp_path)
        execution_module = _module("picotoopet_core.deep_ai.execution")
        provider = FakeProvider(
            repository,
            [execution_module.ProviderTransportAmbiguous("connection lost after submit")],
            [(1000, 500, "0.02")],
        )
        coordinator = _coordinator(tmp_path, repository, provider, enabled=True)
        result = coordinator.execute(job.escalation_job_id)
        assert result.status.value == "NeedsHuman"
        assert result.failure_code == "DEEP_AI_PROVIDER_AMBIGUOUS"
        assert len(provider.calls) == 1
        assert len(provider.reconciled) == 1
        attempts = repository.list_attempts(job.escalation_job_id)
        assert len(attempts) == 1
        assert attempts[0].status.value == "Ambiguous"
    finally:
        database.close()
