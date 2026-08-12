from __future__ import annotations

import importlib
import importlib.util
import inspect
from datetime import timedelta
from pathlib import Path

import pytest

from picotoopet_core.config.paths import RuntimePaths
from picotoopet_core.db.database import Database
from picotoopet_core.handoffs.approvals import HandoffApprovalService
from picotoopet_core.queue.diagnostic_repository import DiagnosticQueueRepository


def _module(name: str):  # type: ignore[no-untyped-def]
    if importlib.util.find_spec(name) is None:
        pytest.fail(f"{name} is not implemented")
    return importlib.import_module(name)


class FakeSourceResolver:
    def __init__(self, context) -> None:  # type: ignore[no-untyped-def]
        self.context = context
        self.calls: list[tuple[str, str]] = []

    def resolve(self, source_kind: str, source_id: str):  # type: ignore[no-untyped-def]
        self.calls.append((source_kind, source_id))
        if source_kind != self.context.source_kind or source_id != self.context.source_id:
            raise KeyError(source_id)
        return self.context


def _database(tmp_path: Path) -> Database:
    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    return database


def _context(*, outcome: str = "NEEDS_DEEP_AI"):  # type: ignore[no-untyped-def]
    sanitizer = _module("picotoopet_core.deep_ai.sanitizer")
    return sanitizer.DeepAiSourceContext(
        source_kind="business.local_intelligence",
        source_id="work-eligible-001",
        source_digest="1" * 64,
        project_key="pet-dryer-us",
        source_profile="reviews.voice_of_customer.v1",
        quality_outcome=outcome,
        quality_reasons=["semantic uncertainty remains after bounded local attempts"],
        evidence_snippets=["Airflow complaints are concentrated in long-hair pet reviews."],
        local_result_digest="2" * 64,
        return_schema={"type": "object", "required": ["findings"]},
        manual_handoff_id="handoff-existing-001",
        manual_handoff_digest="3" * 64,
    )


def _service(tmp_path: Path, context, *, approval_ttl: timedelta = timedelta(hours=1)):  # type: ignore[no-untyped-def]
    repository_module = _module("picotoopet_core.deep_ai.repository")
    store_module = _module("picotoopet_core.deep_ai.store")
    service_module = _module("picotoopet_core.deep_ai.service")
    policy_module = _module("picotoopet_core.deep_ai.policy")
    database = _database(tmp_path)
    paths = RuntimePaths.from_root(tmp_path / "runtime")
    paths.ensure()
    queue = DiagnosticQueueRepository(database)
    approvals = HandoffApprovalService(database, queue)
    service = service_module.DeepAiEscalationService(
        repository=repository_module.DeepAiRepository(database),
        store=store_module.DeepAiSanitizedPackageStore(paths),
        approvals=approvals,
        source_resolver=FakeSourceResolver(context),
        policy=policy_module.DeepAiEscalationPolicy.default(),
        approval_ttl=approval_ttl,
    )
    return database, approvals, service


def test_prepare_requires_existing_needs_deep_ai_fact_and_is_idempotent(tmp_path: Path) -> None:
    database, approvals, service = _service(tmp_path, _context())
    try:
        first = service.prepare_from_source(
            source_kind="business.local_intelligence",
            source_id="work-eligible-001",
            requested_by="windows-control-center",
        )
        repeated = service.prepare_from_source(
            source_kind="business.local_intelligence",
            source_id="work-eligible-001",
            requested_by="windows-control-center",
        )
        assert repeated.escalation_job_id == first.escalation_job_id
        assert repeated.approval_id == first.approval_id
        assert first.status.value == "WaitingApproval"
        assert first.provider_profile_id == "paid.reasoning.v1"
        assert first.model_id == "gpt-5.6-terra"
        assert first.max_calls == 2
        assert str(first.max_cost_usd) == "0.50"

        approval = approvals.get(first.approval_id)
        assert approval.approval_type == "deep-ai.execute-v1"
        assert approval.scope["escalation_job_id"] == first.escalation_job_id
        assert approval.scope["sanitized_package_digest"] == first.sanitized_package_digest
        assert approval.scope["provider_profile_id"] == "paid.reasoning.v1"
        assert approval.scope["provider_profile_digest"] == first.provider_profile_digest
        assert approval.scope["model_id"] == "gpt-5.6-terra"
        assert approval.scope["max_input_tokens"] == 12000
        assert approval.scope["max_output_tokens"] == 4000
        assert approval.scope["max_calls"] == 2
        assert approval.scope["max_cost_usd"] == "0.50"
        assert approval.scope["policy_version"] == "deep-ai.escalation.v1"
    finally:
        database.close()


def test_prepare_rejects_non_needs_deep_ai_and_ineligible_source_class(tmp_path: Path) -> None:
    database, _, service = _service(tmp_path, _context(outcome="PASS"))
    try:
        with pytest.raises(ValueError, match="DEEP_AI_SOURCE_NOT_NEEDS_DEEP_AI"):
            service.prepare_from_source(
                source_kind="business.local_intelligence",
                source_id="work-eligible-001",
                requested_by="windows-control-center",
            )
        with pytest.raises(ValueError, match="DEEP_AI_SOURCE_NOT_ELIGIBLE"):
            service.prepare_from_source(
                source_kind="production.comfyui",
                source_id="work-eligible-001",
                requested_by="windows-control-center",
            )
    finally:
        database.close()


def test_accepted_approval_remains_non_spending_when_execution_disabled(tmp_path: Path) -> None:
    database, approvals, service = _service(tmp_path, _context())
    try:
        prepared = service.prepare_from_source(
            source_kind="business.local_intelligence",
            source_id="work-eligible-001",
            requested_by="windows-control-center",
        )
        approval = approvals.get(prepared.approval_id)
        approvals.decide_for_control_center(
            approval_id=approval.approval_id,
            decision="approve",
            request_digest=approval.request_digest,
            idempotency_key="approve-paid-ai-work-eligible-001",
            resolved_by="human-user",
            reason="Approve exact bounded envelope for later provider execution.",
        )
        reconciled = service.reconcile(prepared.escalation_job_id)
        assert reconciled.status.value == "Approved"
        readiness = service.readiness(prepared.escalation_job_id)
        assert readiness.execution_enabled is False
        assert readiness.provider_ready is False
        assert readiness.reason_code == "DEEP_AI_EXECUTION_DISABLED"
        assert service.claim_provider_ready(limit=10) == []
    finally:
        database.close()


def test_rejected_or_expired_approval_converges_without_provider_readiness(tmp_path: Path) -> None:
    database, approvals, service = _service(tmp_path, _context())
    try:
        prepared = service.prepare_from_source(
            source_kind="business.local_intelligence",
            source_id="work-eligible-001",
            requested_by="windows-control-center",
        )
        approval = approvals.get(prepared.approval_id)
        approvals.decide_for_control_center(
            approval_id=approval.approval_id,
            decision="reject",
            request_digest=approval.request_digest,
            idempotency_key="reject-paid-ai-work-eligible-001",
            resolved_by="human-user",
            reason="Keep manual handoff only.",
        )
        assert service.reconcile(prepared.escalation_job_id).status.value == "Rejected"
        assert service.claim_provider_ready(limit=10) == []
    finally:
        database.close()

    expired_db, _, expired_service = _service(
        tmp_path / "expired",
        _context(),
        approval_ttl=timedelta(seconds=-1),
    )
    try:
        expired = expired_service.prepare_from_source(
            source_kind="business.local_intelligence",
            source_id="work-eligible-001",
            requested_by="windows-control-center",
        )
        assert expired_service.reconcile(expired.escalation_job_id).status.value == "Cancelled"
        assert expired_service.claim_provider_ready(limit=10) == []
    finally:
        expired_db.close()


def test_prepare_api_has_no_provider_model_endpoint_or_prompt_override() -> None:
    service_module = _module("picotoopet_core.deep_ai.service")
    parameters = set(inspect.signature(service_module.DeepAiEscalationService.prepare_from_source).parameters)
    for forbidden in (
        "provider",
        "provider_profile_id",
        "model",
        "model_id",
        "endpoint",
        "url",
        "api_key",
        "prompt",
        "temperature",
        "tools",
        "command",
    ):
        assert forbidden not in parameters
