from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from pydantic import SecretStr

from picotoopet_core.config.paths import RuntimePaths
from picotoopet_core.db.database import Database
from picotoopet_core.deep_ai.policy import DeepAiEscalationPolicy
from picotoopet_core.deep_ai.provider import (
    DeepAiProviderRequestReader,
    DeepAiProviderResultStore,
    DeepAiWorkerProviderConfig,
    ProviderEstimate,
    ProviderResponse,
)
from picotoopet_core.deep_ai.repository import DeepAiRepository
from picotoopet_core.deep_ai.sanitizer import DeepAiSourceContext
from picotoopet_core.deep_ai.service import DeepAiEscalationService
from picotoopet_core.deep_ai.store import DeepAiSanitizedPackageStore
from picotoopet_core.handoffs.approvals import HandoffApprovalService
from picotoopet_core.queue.diagnostic_repository import DiagnosticQueueRepository


class FakeSourceResolver:
    def resolve(self, source_kind: str, source_id: str) -> DeepAiSourceContext:
        return DeepAiSourceContext(
            source_kind=source_kind,
            source_id=source_id,
            source_digest="1" * 64,
            project_key="pet-dryer-us",
            source_profile="reviews.voice_of_customer.v1",
            quality_outcome="NEEDS_DEEP_AI",
            quality_reasons=["needs deeper reasoning"],
            evidence_snippets=["bounded evidence"],
            local_result_digest="2" * 64,
            return_schema={"type": "object", "required": ["findings"]},
            manual_handoff_id="handoff-001",
            manual_handoff_digest="3" * 64,
        )


class FakeProvider:
    def __init__(self) -> None:
        self.calls = 0

    def estimate(self, *, request_bytes: bytes, repair: bool) -> ProviderEstimate:
        return ProviderEstimate(input_tokens=1000, output_tokens=500, cost_usd=Decimal("0.02"))

    def execute(self, *, request_bytes: bytes, attempt_id: str, repair: bool) -> ProviderResponse:
        self.calls += 1
        return ProviderResponse(
            provider_request_id="provider-request-1",
            output={"findings": [{"summary": "supported"}]},
            input_tokens=1000,
            output_tokens=500,
            actual_cost_usd=Decimal("0.01"),
            cost_source="calculated",
        )

    def reconcile(self, attempt_id: str) -> ProviderResponse | None:
        return None


def _build(tmp_path: Path):  # type: ignore[no-untyped-def]
    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    paths = RuntimePaths.from_root(tmp_path / "runtime")
    paths.ensure()
    repository = DeepAiRepository(database)
    approvals = HandoffApprovalService(database, DiagnosticQueueRepository(database))
    service = DeepAiEscalationService(
        repository=repository,
        store=DeepAiSanitizedPackageStore(paths),
        approvals=approvals,
        source_resolver=FakeSourceResolver(),
        policy=DeepAiEscalationPolicy.default(),
    )
    return database, paths, repository, approvals, service


def _approve(approvals: HandoffApprovalService, job) -> None:  # type: ignore[no-untyped-def]
    approval = approvals.get(job.approval_id)
    approvals.decide_for_control_center(
        approval_id=approval.approval_id,
        decision="approve",
        request_digest=approval.request_digest,
        idempotency_key=f"approve:{job.escalation_job_id}",
        resolved_by="human-user",
        reason="Approve exact bounded paid-AI envelope.",
    )


def test_worker_loop_promotes_exact_approved_job_and_executes_once(tmp_path: Path) -> None:
    from picotoopet_core.deep_ai.execution import DeepAiWorkerExecutionLoop

    database, paths, repository, approvals, service = _build(tmp_path)
    try:
        job = service.prepare_from_source(
            source_kind="business.local_intelligence",
            source_id="source-001",
            requested_by="windows-control-center",
        )
        _approve(approvals, job)
        assert service.reconcile(job.escalation_job_id).status.value == "Approved"
        provider = FakeProvider()
        config = DeepAiWorkerProviderConfig(
            api_key=SecretStr("fake-test-key"),
            execution_enabled=True,
        )
        loop = DeepAiWorkerExecutionLoop(
            repository=repository,
            approvals=approvals,
            policy=DeepAiEscalationPolicy.default(),
            config=config,
            provider=provider,
            request_reader=DeepAiProviderRequestReader(paths),
            result_store=DeepAiProviderResultStore(paths),
        )
        processed = loop.run_once()
        assert processed == 1
        assert provider.calls == 1
        assert repository.get_job(job.escalation_job_id).status.value == "Validating"
        assert loop.run_once() == 0
        assert provider.calls == 1
    finally:
        database.close()


def test_worker_loop_profile_mismatch_never_calls_provider(tmp_path: Path) -> None:
    from picotoopet_core.deep_ai.execution import DeepAiWorkerExecutionLoop

    database, paths, repository, approvals, service = _build(tmp_path)
    try:
        job = service.prepare_from_source(
            source_kind="business.local_intelligence",
            source_id="source-002",
            requested_by="windows-control-center",
        )
        _approve(approvals, job)
        service.reconcile(job.escalation_job_id)
        provider = FakeProvider()
        config = DeepAiWorkerProviderConfig(
            model_id="attacker-model",
            api_key=SecretStr("fake-test-key"),
            execution_enabled=True,
        )
        loop = DeepAiWorkerExecutionLoop(
            repository=repository,
            approvals=approvals,
            policy=DeepAiEscalationPolicy.default(),
            config=config,
            provider=provider,
            request_reader=DeepAiProviderRequestReader(paths),
            result_store=DeepAiProviderResultStore(paths),
        )
        assert loop.run_once() == 0
        assert provider.calls == 0
        updated = repository.get_job(job.escalation_job_id)
        assert updated.status.value == "NeedsHuman"
        assert updated.failure_code == "DEEP_AI_WORKER_PROFILE_MISMATCH"
    finally:
        database.close()
