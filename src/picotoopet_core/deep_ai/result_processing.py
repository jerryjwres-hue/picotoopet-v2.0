"""Deterministic processing of already-paid provider results.

This stage never calls a provider. It validates one durably committed response, applies an
idempotent source continuation on PASS, appends one idempotent learning observation, then
freezes the validation outcome and terminal escalation state in SQLite.
"""

from __future__ import annotations

from typing import Protocol

from .learning import DeepAiLearningLedger
from .models import (
    DeepAiAttemptStatus,
    DeepAiEscalationRecord,
    DeepAiEscalationStatus,
    DeepAiValidationOutcome,
)
from .provider import DeepAiProviderResultStore
from .repository import DeepAiRepository
from .sanitizer import DeepAiSourceContext
from .validation import DeepAiResultValidator


class DeepAiContinuation(Protocol):
    def apply_pass(
        self,
        *,
        job: DeepAiEscalationRecord,
        output: dict[str, object],
        output_digest: str,
    ) -> str: ...


class DeepAiResultSourceResolver(Protocol):
    def resolve(self, source_kind: str, source_id: str) -> DeepAiSourceContext: ...


_TERMINAL_VALIDATED = frozenset(
    {
        DeepAiEscalationStatus.COMPLETED,
        DeepAiEscalationStatus.NEEDS_HUMAN,
        DeepAiEscalationStatus.REJECTED,
    }
)


class DeepAiResultProcessor:
    """Finalize one `Validating` escalation without any provider execution authority."""

    def __init__(
        self,
        *,
        repository: DeepAiRepository,
        result_store: DeepAiProviderResultStore,
        source_resolver: DeepAiResultSourceResolver,
        validator: DeepAiResultValidator,
        continuation: DeepAiContinuation,
        learning: DeepAiLearningLedger,
    ) -> None:
        self.repository = repository
        self.result_store = result_store
        self.source_resolver = source_resolver
        self.validator = validator
        self.continuation = continuation
        self.learning = learning

    def process(self, escalation_job_id: str) -> DeepAiEscalationRecord:
        job = self.repository.get_job(escalation_job_id)
        if job.status in _TERMINAL_VALIDATED and job.validation_outcome is not None:
            return job
        if job.status is not DeepAiEscalationStatus.VALIDATING:
            return job

        attempts = [
            attempt
            for attempt in self.repository.list_attempts(escalation_job_id)
            if attempt.status is DeepAiAttemptStatus.COMPLETED
        ]
        if not attempts:
            return self._freeze(
                job,
                outcome=DeepAiValidationOutcome.NEEDS_HUMAN,
                status=DeepAiEscalationStatus.NEEDS_HUMAN,
                accepted_result_digest=None,
                accepted_result_relpath=None,
                failure_code="DEEP_AI_PROVIDER_RESULT_MISSING",
            )
        attempt = attempts[-1]
        if attempt.response_relpath is None or attempt.response_digest is None:
            return self._freeze(
                job,
                outcome=DeepAiValidationOutcome.NEEDS_HUMAN,
                status=DeepAiEscalationStatus.NEEDS_HUMAN,
                accepted_result_digest=None,
                accepted_result_relpath=None,
                failure_code="DEEP_AI_PROVIDER_RESULT_MISSING",
            )

        response = self.result_store.read(attempt.response_relpath)
        context = self.source_resolver.resolve(job.source_kind, job.source_id)
        decision = self.validator.validate(
            output=response.output,
            return_schema=context.return_schema,
            # Sanitized v1 sends bounded snippets, not arbitrary externally supplied IDs.
            # A provider therefore may omit evidence_refs; any invented ref is rejected.
            allowed_evidence_refs=set(),
        )

        downstream_ref: str | None = None
        terminal_status: DeepAiEscalationStatus
        failure_code: str | None
        accepted_digest: str | None = None
        accepted_relpath: str | None = None
        if decision.outcome is DeepAiValidationOutcome.PASS:
            downstream_ref = self.continuation.apply_pass(
                job=job,
                output=response.output,
                output_digest=decision.output_digest,
            )
            terminal_status = DeepAiEscalationStatus.COMPLETED
            failure_code = None
            accepted_digest = attempt.response_digest
            accepted_relpath = attempt.response_relpath
        elif decision.outcome is DeepAiValidationOutcome.NEEDS_HUMAN:
            terminal_status = DeepAiEscalationStatus.NEEDS_HUMAN
            failure_code = decision.reasons[0] if decision.reasons else "DEEP_AI_VALIDATION_NEEDS_HUMAN"
        else:
            terminal_status = DeepAiEscalationStatus.REJECTED
            failure_code = decision.reasons[0] if decision.reasons else "DEEP_AI_VALIDATION_REJECTED"

        self.learning.record_validation(
            idempotency_key=(
                f"deep-ai:validation:{job.escalation_job_id}:{attempt.response_digest}:"
                f"{decision.outcome.value}"
            ),
            project_key=context.project_key,
            job=job,
            local_profile=context.source_profile,
            local_model_id="source-local-model",
            local_template_version="source-stage-template",
            local_attempt_count=2,
            local_quality_outcome=context.quality_outcome,
            quality_reasons=context.quality_reasons,
            paid_output_digest=decision.output_digest,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cost_usd=response.actual_cost_usd,
            paid_validation_outcome=decision.outcome.value,
            downstream_ref=downstream_ref,
        )

        return self._freeze(
            job,
            outcome=decision.outcome,
            status=terminal_status,
            accepted_result_digest=accepted_digest,
            accepted_result_relpath=accepted_relpath,
            failure_code=failure_code,
        )

    def _freeze(
        self,
        job: DeepAiEscalationRecord,
        *,
        outcome: DeepAiValidationOutcome,
        status: DeepAiEscalationStatus,
        accepted_result_digest: str | None,
        accepted_result_relpath: str | None,
        failure_code: str | None,
    ) -> DeepAiEscalationRecord:
        now = self.repository._now()
        with self.repository.database.transaction() as connection:
            current = connection.execute(
                "SELECT validation_outcome,accepted_result_digest,accepted_result_relpath,status,failure_code "
                "FROM deep_ai_escalation_jobs WHERE escalation_job_id=?",
                (job.escalation_job_id,),
            ).fetchone()
            if current is None:
                raise KeyError(job.escalation_job_id)
            if current["validation_outcome"] is not None:
                frozen = (
                    current["validation_outcome"],
                    current["accepted_result_digest"],
                    current["accepted_result_relpath"],
                    current["status"],
                    current["failure_code"],
                )
                requested = (
                    outcome.value,
                    accepted_result_digest,
                    accepted_result_relpath,
                    status.value,
                    failure_code,
                )
                if frozen != requested:
                    raise ValueError("DEEP_AI_VALIDATION_IMMUTABLE")
                return self.repository.get_job(job.escalation_job_id)
            connection.execute(
                "UPDATE deep_ai_escalation_jobs SET validation_outcome=?,accepted_result_digest=?,"
                "accepted_result_relpath=?,status=?,failure_code=?,error_message=NULL,updated_at=?,"
                "finished_at=? WHERE escalation_job_id=?",
                (
                    outcome.value,
                    accepted_result_digest,
                    accepted_result_relpath,
                    status.value,
                    failure_code,
                    now,
                    now,
                    job.escalation_job_id,
                ),
            )
        return self.repository.get_job(job.escalation_job_id)
