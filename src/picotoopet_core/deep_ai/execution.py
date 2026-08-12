"""Bounded paid-AI execution with reserve-before-submit and duplicate-spend protection."""

from __future__ import annotations

import hashlib
from decimal import Decimal
from uuid import uuid4

from picotoopet_core.domain.enums import ApprovalStatus
from picotoopet_core.handoffs.approvals import HandoffApprovalService

from .models import DeepAiAttemptStatus, DeepAiEscalationRecord, DeepAiEscalationStatus
from .policy import DeepAiEscalationPolicy
from .provider import (
    DeepAiProviderRequestReader,
    DeepAiProviderResultStore,
    DeepAiWorkerProviderConfig,
    PaidAiProviderAdapter,
    ProviderExecutionError,
    ProviderResponse,
    ProviderTransportAmbiguous,
)
from .repository import DeepAiRepository


_TERMINAL = frozenset(
    {
        DeepAiEscalationStatus.COMPLETED,
        DeepAiEscalationStatus.NEEDS_HUMAN,
        DeepAiEscalationStatus.REJECTED,
        DeepAiEscalationStatus.FAILED,
        DeepAiEscalationStatus.CANCELLED,
    }
)


class DeepAiExecutionCoordinator:
    def __init__(
        self,
        *,
        repository: DeepAiRepository,
        provider: PaidAiProviderAdapter,
        request_reader: DeepAiProviderRequestReader,
        result_store: DeepAiProviderResultStore,
        execution_enabled: bool,
    ) -> None:
        self.repository = repository
        self.provider = provider
        self.request_reader = request_reader
        self.result_store = result_store
        self.execution_enabled = execution_enabled

    def execute(self, escalation_job_id: str) -> DeepAiEscalationRecord:
        job = self.repository.get_job(escalation_job_id)
        if job.status in _TERMINAL:
            return job
        if not self.execution_enabled:
            if job.status in {
                DeepAiEscalationStatus.PROVIDER_READY,
                DeepAiEscalationStatus.CLAIMED,
                DeepAiEscalationStatus.EXECUTING,
            }:
                return self.repository.set_job_status(
                    escalation_job_id,
                    DeepAiEscalationStatus.APPROVED,
                    failure_code="DEEP_AI_EXECUTION_DISABLED",
                )
            return job
        if job.status is DeepAiEscalationStatus.VALIDATING:
            return job
        if job.status not in {
            DeepAiEscalationStatus.PROVIDER_READY,
            DeepAiEscalationStatus.CLAIMED,
            DeepAiEscalationStatus.EXECUTING,
        }:
            return job

        request_bytes = self.request_reader.read(job.sanitized_package_relpath)
        request_digest = hashlib.sha256(request_bytes).hexdigest()
        if request_digest != job.sanitized_package_digest:
            return self.repository.set_job_status(
                escalation_job_id,
                DeepAiEscalationStatus.NEEDS_HUMAN,
                failure_code="DEEP_AI_REQUEST_DIGEST_MISMATCH",
                finished=True,
            )

        while True:
            job = self.repository.get_job(escalation_job_id)
            attempts = self.repository.list_attempts(escalation_job_id)
            recovered = self._recover_incomplete_attempt(job, attempts)
            if recovered is not None:
                return recovered
            attempts = self.repository.list_attempts(escalation_job_id)

            if attempts and attempts[-1].status is DeepAiAttemptStatus.COMPLETED:
                latest = attempts[-1]
                assert latest.response_relpath is not None
                response = self.result_store.read(latest.response_relpath)
                decision = self._after_response(job, response, latest.attempt_number)
                if decision is not None:
                    return decision
                repair = True
            else:
                repair = False

            attempt_number = len(attempts) + 1
            if attempt_number > job.max_calls:
                return self.repository.set_job_status(
                    escalation_job_id,
                    DeepAiEscalationStatus.NEEDS_HUMAN,
                    failure_code="DEEP_AI_CALL_BUDGET_EXHAUSTED",
                    finished=True,
                )

            estimate = self.provider.estimate(request_bytes=request_bytes, repair=repair)
            if not self._preflight_allows(job, attempts, estimate):
                return self.repository.set_job_status(
                    escalation_job_id,
                    DeepAiEscalationStatus.NEEDS_HUMAN,
                    failure_code="DEEP_AI_BUDGET_PREFLIGHT_FAILED",
                    finished=True,
                )

            attempt_id = str(uuid4())
            self.repository.reserve_attempt(
                escalation_job_id=escalation_job_id,
                attempt_id=attempt_id,
                attempt_number=attempt_number,
                estimated_cost_usd=estimate.cost_usd,
            )
            self.repository.set_job_status(
                escalation_job_id,
                DeepAiEscalationStatus.EXECUTING,
            )
            try:
                response = self.provider.execute(
                    request_bytes=request_bytes,
                    attempt_id=attempt_id,
                    repair=repair,
                )
            except ProviderTransportAmbiguous:
                reconciled = self.provider.reconcile(attempt_id)
                if reconciled is None:
                    self.repository.set_attempt_status(
                        attempt_id,
                        DeepAiAttemptStatus.AMBIGUOUS,
                    )
                    return self.repository.set_job_status(
                        escalation_job_id,
                        DeepAiEscalationStatus.NEEDS_HUMAN,
                        failure_code="DEEP_AI_PROVIDER_AMBIGUOUS",
                        finished=True,
                    )
                response = reconciled
            except ProviderExecutionError as exc:
                self.repository.set_attempt_status(attempt_id, DeepAiAttemptStatus.FAILED)
                return self.repository.set_job_status(
                    escalation_job_id,
                    DeepAiEscalationStatus.FAILED,
                    failure_code="DEEP_AI_PROVIDER_FAILED",
                    error_message=type(exc).__name__,
                    finished=True,
                )

            stored = self.result_store.save(attempt_id=attempt_id, response=response)
            self.repository.bind_attempt_result(
                attempt_id,
                provider_request_id=response.provider_request_id,
                response_digest=stored.digest,
                response_relpath=stored.relpath,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                actual_cost_usd=response.actual_cost_usd,
                cost_source=response.cost_source,
            )
            attempts = self.repository.list_attempts(escalation_job_id)
            if not self._actual_usage_within_envelope(job, attempts):
                return self.repository.set_job_status(
                    escalation_job_id,
                    DeepAiEscalationStatus.NEEDS_HUMAN,
                    failure_code="DEEP_AI_ACTUAL_USAGE_EXCEEDED",
                    finished=True,
                )
            decision = self._after_response(job, response, attempt_number)
            if decision is not None:
                return decision
            # Structural-only failure on attempt 1 may consume the one bounded repair call.

    def _recover_incomplete_attempt(
        self,
        job: DeepAiEscalationRecord,
        attempts: list,
    ) -> DeepAiEscalationRecord | None:
        if not attempts:
            return None
        latest = attempts[-1]
        if latest.status is DeepAiAttemptStatus.AMBIGUOUS:
            return self.repository.set_job_status(
                job.escalation_job_id,
                DeepAiEscalationStatus.NEEDS_HUMAN,
                failure_code="DEEP_AI_PROVIDER_AMBIGUOUS",
                finished=True,
            )
        if latest.status is not DeepAiAttemptStatus.RESERVED:
            return None
        reconciled = self.provider.reconcile(latest.attempt_id)
        if reconciled is None:
            self.repository.set_attempt_status(
                latest.attempt_id,
                DeepAiAttemptStatus.AMBIGUOUS,
            )
            return self.repository.set_job_status(
                job.escalation_job_id,
                DeepAiEscalationStatus.NEEDS_HUMAN,
                failure_code="DEEP_AI_PROVIDER_AMBIGUOUS",
                finished=True,
            )
        stored = self.result_store.save(attempt_id=latest.attempt_id, response=reconciled)
        self.repository.bind_attempt_result(
            latest.attempt_id,
            provider_request_id=reconciled.provider_request_id,
            response_digest=stored.digest,
            response_relpath=stored.relpath,
            input_tokens=reconciled.input_tokens,
            output_tokens=reconciled.output_tokens,
            actual_cost_usd=reconciled.actual_cost_usd,
            cost_source=reconciled.cost_source,
        )
        attempts = self.repository.list_attempts(job.escalation_job_id)
        if not self._actual_usage_within_envelope(job, attempts):
            return self.repository.set_job_status(
                job.escalation_job_id,
                DeepAiEscalationStatus.NEEDS_HUMAN,
                failure_code="DEEP_AI_ACTUAL_USAGE_EXCEEDED",
                finished=True,
            )
        return self._after_response(job, reconciled, latest.attempt_number)

    @staticmethod
    def _preflight_allows(job, attempts, estimate) -> bool:  # type: ignore[no-untyped-def]
        if len(attempts) >= job.max_calls:
            return False
        if estimate.input_tokens > job.max_input_tokens:
            return False
        if estimate.output_tokens > job.max_output_tokens:
            return False
        spent = sum(
            (attempt.actual_cost_usd or Decimal("0"))
            for attempt in attempts
            if attempt.status is DeepAiAttemptStatus.COMPLETED
        )
        return spent + estimate.cost_usd <= job.max_cost_usd

    @staticmethod
    def _actual_usage_within_envelope(job, attempts) -> bool:  # type: ignore[no-untyped-def]
        completed = [
            attempt for attempt in attempts if attempt.status is DeepAiAttemptStatus.COMPLETED
        ]
        if len(completed) > job.max_calls:
            return False
        if any((item.input_tokens or 0) > job.max_input_tokens for item in completed):
            return False
        if any((item.output_tokens or 0) > job.max_output_tokens for item in completed):
            return False
        spent = sum((item.actual_cost_usd or Decimal("0")) for item in completed)
        return spent <= job.max_cost_usd

    def _after_response(
        self,
        job: DeepAiEscalationRecord,
        response: ProviderResponse,
        attempt_number: int,
    ) -> DeepAiEscalationRecord | None:
        if response.semantic_failure:
            return self.repository.set_job_status(
                job.escalation_job_id,
                DeepAiEscalationStatus.NEEDS_HUMAN,
                failure_code="DEEP_AI_PROVIDER_SEMANTIC_FAILURE",
                finished=True,
            )
        if response.structural_error:
            if attempt_number >= job.max_calls:
                return self.repository.set_job_status(
                    job.escalation_job_id,
                    DeepAiEscalationStatus.NEEDS_HUMAN,
                    failure_code="DEEP_AI_STRUCTURAL_REPAIR_EXHAUSTED",
                    finished=True,
                )
            return None
        return self.repository.set_job_status(
            job.escalation_job_id,
            DeepAiEscalationStatus.VALIDATING,
        )


class DeepAiWorkerExecutionLoop:
    """Promote only exact-approved frozen jobs and execute at most one job per poll."""

    CAPABILITY = "paid.ai.reasoning.v1"

    def __init__(
        self,
        *,
        repository: DeepAiRepository,
        approvals: HandoffApprovalService,
        policy: DeepAiEscalationPolicy,
        config: DeepAiWorkerProviderConfig,
        provider: PaidAiProviderAdapter,
        request_reader: DeepAiProviderRequestReader,
        result_store: DeepAiProviderResultStore,
    ) -> None:
        self.repository = repository
        self.approvals = approvals
        self.policy = policy
        self.config = config
        self.coordinator = DeepAiExecutionCoordinator(
            repository=repository,
            provider=provider,
            request_reader=request_reader,
            result_store=result_store,
            execution_enabled=config.execution_enabled,
        )

    def run_once(self) -> int:
        if not self.config.execution_enabled:
            return 0
        for job in self.repository.list_jobs(limit=100):
            if job.status is DeepAiEscalationStatus.APPROVED:
                if not self._promote_if_exact(job):
                    continue
                self.coordinator.execute(job.escalation_job_id)
                return 1
            if job.status in {
                DeepAiEscalationStatus.PROVIDER_READY,
                DeepAiEscalationStatus.CLAIMED,
                DeepAiEscalationStatus.EXECUTING,
            }:
                if not self._frozen_profile_matches(job):
                    self.repository.set_job_status(
                        job.escalation_job_id,
                        DeepAiEscalationStatus.NEEDS_HUMAN,
                        failure_code="DEEP_AI_WORKER_PROFILE_MISMATCH",
                        finished=True,
                    )
                    continue
                self.coordinator.execute(job.escalation_job_id)
                return 1
        return 0

    def _frozen_profile_matches(self, job: DeepAiEscalationRecord) -> bool:
        try:
            trusted = self.policy.for_source(job.source_kind)
        except ValueError:
            return False
        return (
            self.config.provider_profile_id == trusted.provider_profile_id
            and self.config.provider_adapter_id == trusted.provider_adapter_id
            and self.config.model_id == trusted.model_id
            and job.provider_profile_id == trusted.provider_profile_id
            and job.provider_profile_digest == trusted.provider_profile_digest
            and job.model_id == trusted.model_id
        )

    def _promote_if_exact(self, job: DeepAiEscalationRecord) -> bool:
        if not self._frozen_profile_matches(job):
            self.repository.set_job_status(
                job.escalation_job_id,
                DeepAiEscalationStatus.NEEDS_HUMAN,
                failure_code="DEEP_AI_WORKER_PROFILE_MISMATCH",
                finished=True,
            )
            return False
        if job.approval_id is None or job.approval_digest is None:
            self.repository.set_job_status(
                job.escalation_job_id,
                DeepAiEscalationStatus.NEEDS_HUMAN,
                failure_code="DEEP_AI_APPROVAL_MISSING",
                finished=True,
            )
            return False
        approval = self.approvals.get(job.approval_id)
        if approval.request_digest != job.approval_digest:
            self.repository.set_job_status(
                job.escalation_job_id,
                DeepAiEscalationStatus.NEEDS_HUMAN,
                failure_code="DEEP_AI_APPROVAL_DIGEST_MISMATCH",
                finished=True,
            )
            return False
        if approval.status == ApprovalStatus.REJECTED.value:
            self.repository.set_job_status(
                job.escalation_job_id,
                DeepAiEscalationStatus.REJECTED,
                failure_code="DEEP_AI_APPROVAL_REJECTED",
                finished=True,
            )
            return False
        if approval.status == ApprovalStatus.EXPIRED.value:
            self.repository.set_job_status(
                job.escalation_job_id,
                DeepAiEscalationStatus.CANCELLED,
                failure_code="DEEP_AI_APPROVAL_EXPIRED",
                finished=True,
            )
            return False
        if approval.status != ApprovalStatus.APPROVED.value:
            return False
        self.repository.set_job_status(
            job.escalation_job_id,
            DeepAiEscalationStatus.PROVIDER_READY,
        )
        return True


__all__ = [
    "DeepAiExecutionCoordinator",
    "DeepAiWorkerExecutionLoop",
    "ProviderTransportAmbiguous",
]
