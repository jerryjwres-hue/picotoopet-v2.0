"""Approval-gated orchestration for Deep-AI escalation preparation/readiness."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from picotoopet_core.business.models import BusinessWorkPackageStatus
from picotoopet_core.business.repository import BusinessRepository
from picotoopet_core.creative.models import CreativeJobStatus
from picotoopet_core.creative.repository import CreativeRepository
from picotoopet_core.domain.enums import ApprovalStatus
from picotoopet_core.handoffs.approvals import HandoffApprovalService

from .models import DeepAiEscalationRecord, DeepAiEscalationStatus
from .policy import DeepAiEscalationPolicy
from .repository import DeepAiRepository
from .sanitizer import DeepAiSanitizer, DeepAiSourceContext
from .store import DeepAiSanitizedPackageStore


class DeepAiSourceResolver(Protocol):
    def resolve(self, source_kind: str, source_id: str) -> DeepAiSourceContext: ...


class CoreDeepAiSourceResolver:
    """Resolve only existing durable Business/Creative NEEDS_DEEP_AI facts."""

    def __init__(
        self,
        business_repository: BusinessRepository,
        creative_repository: CreativeRepository,
    ) -> None:
        self.business_repository = business_repository
        self.creative_repository = creative_repository

    def resolve(self, source_kind: str, source_id: str) -> DeepAiSourceContext:
        if source_kind == "business.local_intelligence":
            work = self.business_repository.get_work_package(source_id)
            if work.status is not BusinessWorkPackageStatus.NEEDS_DEEP_AI:
                raise ValueError("DEEP_AI_SOURCE_NOT_NEEDS_DEEP_AI")
            handoff = self.business_repository.handoff_for(source_id)
            if handoff is None:
                raise ValueError("DEEP_AI_MANUAL_HANDOFF_REQUIRED")
            return DeepAiSourceContext(
                source_kind=source_kind,
                source_id=source_id,
                source_digest=handoff.source_digest,
                project_key=work.project_key,
                source_profile=work.analysis_profile.value,
                quality_outcome="NEEDS_DEEP_AI",
                quality_reasons=handoff.quality_reasons,
                evidence_snippets=handoff.quality_reasons,
                local_result_digest=handoff.local_result_digest,
                return_schema=handoff.return_schema,
                manual_handoff_id=handoff.handoff_id,
                manual_handoff_digest=handoff.package_digest,
            )
        if source_kind == "creative.intelligence":
            job = self.creative_repository.get_job(source_id)
            if job.status is not CreativeJobStatus.NEEDS_DEEP_AI:
                raise ValueError("DEEP_AI_SOURCE_NOT_NEEDS_DEEP_AI")
            handoff = self.creative_repository.handoff_for(source_id)
            if handoff is None:
                raise ValueError("DEEP_AI_MANUAL_HANDOFF_REQUIRED")
            return DeepAiSourceContext(
                source_kind=source_kind,
                source_id=source_id,
                source_digest=handoff.source_set_digest,
                project_key=job.project_key,
                source_profile=job.creative_profile.value,
                quality_outcome="NEEDS_DEEP_AI",
                quality_reasons=handoff.quality_reasons,
                evidence_snippets=handoff.quality_reasons,
                local_result_digest=handoff.failed_result_digest,
                return_schema=handoff.return_schema,
                manual_handoff_id=handoff.handoff_id,
                manual_handoff_digest=handoff.package_digest,
            )
        raise ValueError("DEEP_AI_SOURCE_NOT_ELIGIBLE")


class DeepAiReadiness(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    escalation_job_id: str
    execution_enabled: bool
    provider_ready: bool
    reason_code: str
    manual_handoff_id: str | None = None


class DeepAiEscalationService:
    APPROVAL_TYPE = "deep-ai.execute-v1"

    def __init__(
        self,
        *,
        repository: DeepAiRepository,
        store: DeepAiSanitizedPackageStore,
        approvals: HandoffApprovalService,
        source_resolver: DeepAiSourceResolver,
        policy: DeepAiEscalationPolicy,
        approval_ttl: timedelta = timedelta(hours=1),
    ) -> None:
        self.repository = repository
        self.store = store
        self.approvals = approvals
        self.source_resolver = source_resolver
        self.policy = policy
        self.approval_ttl = approval_ttl
        self.sanitizer = DeepAiSanitizer()

    def prepare_from_source(
        self,
        *,
        source_kind: str,
        source_id: str,
        requested_by: str,
    ) -> DeepAiEscalationRecord:
        profile = self.policy.for_source(source_kind)
        context = self.source_resolver.resolve(source_kind, source_id)
        if context.quality_outcome != "NEEDS_DEEP_AI":
            raise ValueError("DEEP_AI_SOURCE_NOT_NEEDS_DEEP_AI")
        package = self.sanitizer.build(context)
        stored = self.store.save(package)
        job = self.repository.prepare_job(
            escalation_job_id=str(uuid4()),
            source_kind=context.source_kind,
            source_id=context.source_id,
            source_digest=context.source_digest,
            policy_version=self.policy.policy_version,
            sanitized_package_relpath=stored.relpath,
            sanitized_package_digest=stored.digest,
            sanitizer_version=self.sanitizer.SANITIZER_VERSION,
            provider_profile_id=profile.provider_profile_id,
            provider_profile_digest=profile.provider_profile_digest,
            model_id=profile.model_id,
            max_input_tokens=profile.max_input_tokens,
            max_output_tokens=profile.max_output_tokens,
            max_calls=profile.max_calls,
            max_cost_usd=profile.max_cost_usd,
        )
        if job.approval_id is None:
            job = self._create_and_bind_approval(job, requested_by=requested_by)
        return self.reconcile(job.escalation_job_id)

    def _create_and_bind_approval(
        self,
        job: DeepAiEscalationRecord,
        *,
        requested_by: str,
    ) -> DeepAiEscalationRecord:
        now = datetime.now(UTC)
        expires_at = now + self.approval_ttl
        scope: dict[str, object] = {
            "action": "deep-ai-paid-execution",
            "escalation_job_id": job.escalation_job_id,
            "source_kind": job.source_kind,
            "source_id": job.source_id,
            "source_digest": job.source_digest,
            "sanitized_package_digest": job.sanitized_package_digest,
            "provider_profile_id": job.provider_profile_id,
            "provider_profile_digest": job.provider_profile_digest,
            "model_id": job.model_id,
            "max_input_tokens": job.max_input_tokens,
            "max_output_tokens": job.max_output_tokens,
            "max_calls": job.max_calls,
            "max_cost_usd": format(job.max_cost_usd, ".2f"),
            "policy_version": job.policy_version,
        }
        with self.repository.database.transaction() as connection:
            current = connection.execute(
                "SELECT approval_id FROM deep_ai_escalation_jobs WHERE escalation_job_id=?",
                (job.escalation_job_id,),
            ).fetchone()
            if current is None:
                raise KeyError(job.escalation_job_id)
            if current["approval_id"] is None:
                grant = self.approvals.request_resource_in_transaction(
                    connection,
                    approval_type=self.APPROVAL_TYPE,
                    scope=scope,
                    requested_by=requested_by,
                    expires_at=expires_at,
                    requested_at=now,
                )
                approval_row = connection.execute(
                    "SELECT * FROM approvals WHERE approval_id=?",
                    (grant.approval_id,),
                ).fetchone()
                assert approval_row is not None
                approval_digest = self.approvals._request_digest(approval_row)
                connection.execute(
                    "UPDATE deep_ai_escalation_jobs SET approval_id=?,approval_digest=?,"
                    "approval_expires_at=?,status=?,updated_at=? WHERE escalation_job_id=?",
                    (
                        grant.approval_id,
                        approval_digest,
                        expires_at.isoformat(),
                        DeepAiEscalationStatus.WAITING_APPROVAL.value,
                        now.isoformat(),
                        job.escalation_job_id,
                    ),
                )
        return self.repository.get_job(job.escalation_job_id)

    def _set_status(
        self,
        escalation_job_id: str,
        status: DeepAiEscalationStatus,
        *,
        failure_code: str | None = None,
        finished: bool = False,
    ) -> DeepAiEscalationRecord:
        current = self.repository.get_job(escalation_job_id)
        if current.status is status and current.failure_code == failure_code:
            return current
        now = datetime.now(UTC).isoformat()
        self.repository.database.execute(
            "UPDATE deep_ai_escalation_jobs SET status=?,failure_code=?,updated_at=?,"
            "finished_at=? WHERE escalation_job_id=?",
            (
                status.value,
                failure_code,
                now,
                now if finished else None,
                escalation_job_id,
            ),
        )
        return self.repository.get_job(escalation_job_id)

    def reconcile(self, escalation_job_id: str) -> DeepAiEscalationRecord:
        job = self.repository.get_job(escalation_job_id)
        if job.approval_id is None:
            return job
        approval = self.approvals.get(job.approval_id)
        if approval.request_digest != job.approval_digest:
            return self._set_status(
                escalation_job_id,
                DeepAiEscalationStatus.NEEDS_HUMAN,
                failure_code="DEEP_AI_APPROVAL_DIGEST_MISMATCH",
                finished=True,
            )
        if approval.status == ApprovalStatus.REJECTED.value:
            return self._set_status(
                escalation_job_id,
                DeepAiEscalationStatus.REJECTED,
                failure_code="DEEP_AI_APPROVAL_REJECTED",
                finished=True,
            )
        if approval.status == ApprovalStatus.EXPIRED.value:
            return self._set_status(
                escalation_job_id,
                DeepAiEscalationStatus.CANCELLED,
                failure_code="DEEP_AI_APPROVAL_EXPIRED",
                finished=True,
            )
        if approval.status == ApprovalStatus.PENDING.value:
            return self._set_status(escalation_job_id, DeepAiEscalationStatus.WAITING_APPROVAL)
        if approval.status != ApprovalStatus.APPROVED.value:
            return job
        profile = self.policy.for_source(job.source_kind)
        if (
            profile.provider_profile_id != job.provider_profile_id
            or profile.provider_profile_digest != job.provider_profile_digest
            or profile.model_id != job.model_id
        ):
            return self._set_status(
                escalation_job_id,
                DeepAiEscalationStatus.NEEDS_HUMAN,
                failure_code="DEEP_AI_TRUSTED_PROFILE_CHANGED",
                finished=True,
            )
        if not profile.execution_enabled:
            return self._set_status(escalation_job_id, DeepAiEscalationStatus.APPROVED)
        return self._set_status(escalation_job_id, DeepAiEscalationStatus.APPROVED)

    def readiness(self, escalation_job_id: str) -> DeepAiReadiness:
        job = self.repository.get_job(escalation_job_id)
        context = self.source_resolver.resolve(job.source_kind, job.source_id)
        profile = self.policy.for_source(job.source_kind)
        if not profile.execution_enabled:
            return DeepAiReadiness(
                escalation_job_id=job.escalation_job_id,
                execution_enabled=False,
                provider_ready=False,
                reason_code="DEEP_AI_EXECUTION_DISABLED",
                manual_handoff_id=context.manual_handoff_id,
            )
        return DeepAiReadiness(
            escalation_job_id=job.escalation_job_id,
            execution_enabled=True,
            provider_ready=job.status is DeepAiEscalationStatus.PROVIDER_READY,
            reason_code=(
                "DEEP_AI_PROVIDER_READY"
                if job.status is DeepAiEscalationStatus.PROVIDER_READY
                else "DEEP_AI_WORKER_PROVIDER_NOT_READY"
            ),
            manual_handoff_id=context.manual_handoff_id,
        )

    def claim_provider_ready(self, *, limit: int = 10) -> list[DeepAiEscalationRecord]:
        bounded = max(1, min(limit, 100))
        return [
            job
            for job in self.repository.list_jobs(limit=bounded)
            if job.status is DeepAiEscalationStatus.PROVIDER_READY
        ]
