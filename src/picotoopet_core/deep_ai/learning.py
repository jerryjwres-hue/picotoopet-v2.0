"""Append-only quality-learning observations. This module records facts only."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from .models import DeepAiEscalationRecord, DeepAiHumanAction
from .repository import DeepAiRepository


class DeepAiLearningObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    idempotency_key: str
    project_key: str
    source_kind: str
    source_id: str
    escalation_job_id: str
    local_profile: str | None = None
    local_model_id: str | None = None
    local_template_version: str | None = None
    local_attempt_count: int | None = Field(default=None, ge=0)
    local_quality_outcome: str
    quality_reasons: list[str] = Field(default_factory=list)
    provider_profile_id: str
    provider_model_id: str
    sanitized_input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    paid_output_digest: str | None = None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    cost_usd: Decimal | None = Field(default=None, ge=Decimal("0"))
    paid_validation_outcome: str | None = None
    human_action: DeepAiHumanAction
    reason_tags: list[str] = Field(default_factory=list)
    final_content_digest: str | None = None
    downstream_ref: str | None = None


class DeepAiLearningLedger:
    """Durable observations with no provider execution or policy mutation methods."""

    def __init__(self, repository: DeepAiRepository) -> None:
        self.repository = repository

    @staticmethod
    def _canonical_details(payload: dict[str, object]) -> tuple[str, str]:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return encoded, hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def _record(
        self,
        *,
        idempotency_key: str,
        project_key: str,
        job: DeepAiEscalationRecord,
        local_quality_outcome: str,
        human_action: DeepAiHumanAction,
        reason_tags: list[str],
        final_content_digest: str | None,
        local_profile: str | None,
        local_model_id: str | None,
        local_template_version: str | None,
        local_attempt_count: int | None,
        quality_reasons: list[str],
        paid_output_digest: str | None,
        input_tokens: int | None,
        output_tokens: int | None,
        cost_usd: str | Decimal | None,
        paid_validation_outcome: str | None,
        downstream_ref: str | None,
    ) -> DeepAiLearningObservation:
        summary = self.repository.append_learning_event(
            event_id=str(uuid4()),
            idempotency_key=idempotency_key,
            project_key=project_key,
            source_kind=job.source_kind,
            source_id=job.source_id,
            local_quality_outcome=local_quality_outcome,
            escalation_job_id=job.escalation_job_id,
            human_action=human_action,
            reason_tags=reason_tags,
            final_content_digest=final_content_digest,
        )
        cost_text = None if cost_usd is None else format(Decimal(str(cost_usd)), "f")
        details = {
            "local_profile": local_profile,
            "local_model_id": local_model_id,
            "local_template_version": local_template_version,
            "local_attempt_count": local_attempt_count,
            "quality_reasons": quality_reasons,
            "provider_profile_id": job.provider_profile_id,
            "provider_model_id": job.model_id,
            "sanitized_input_digest": job.sanitized_package_digest,
            "paid_output_digest": paid_output_digest,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": cost_text,
            "paid_validation_outcome": paid_validation_outcome,
            "downstream_ref": downstream_ref,
        }
        _, details_digest = self._canonical_details(details)
        quality_json = json.dumps(
            quality_reasons,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        with self.repository.database.transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM deep_ai_learning_details WHERE event_id=?",
                (summary.event_id,),
            ).fetchone()
            if existing is None:
                connection.execute(
                    "INSERT INTO deep_ai_learning_details("
                    "event_id,local_profile,local_model_id,local_template_version,local_attempt_count,"
                    "quality_reasons_json,provider_profile_id,provider_model_id,sanitized_input_digest,"
                    "paid_output_digest,input_tokens,output_tokens,cost_usd,paid_validation_outcome,"
                    "downstream_ref,details_digest) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        summary.event_id,
                        local_profile,
                        local_model_id,
                        local_template_version,
                        local_attempt_count,
                        quality_json,
                        job.provider_profile_id,
                        job.model_id,
                        job.sanitized_package_digest,
                        paid_output_digest,
                        input_tokens,
                        output_tokens,
                        cost_text,
                        paid_validation_outcome,
                        downstream_ref,
                        details_digest,
                    ),
                )
            elif existing["details_digest"] != details_digest:
                raise ValueError("DEEP_AI_LEARNING_EVENT_IMMUTABLE")
        return DeepAiLearningObservation(
            event_id=summary.event_id,
            idempotency_key=summary.idempotency_key,
            project_key=summary.project_key,
            source_kind=summary.source_kind,
            source_id=summary.source_id,
            escalation_job_id=job.escalation_job_id,
            local_profile=local_profile,
            local_model_id=local_model_id,
            local_template_version=local_template_version,
            local_attempt_count=local_attempt_count,
            local_quality_outcome=local_quality_outcome,
            quality_reasons=quality_reasons,
            provider_profile_id=job.provider_profile_id,
            provider_model_id=job.model_id,
            sanitized_input_digest=job.sanitized_package_digest,
            paid_output_digest=paid_output_digest,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=Decimal(cost_text) if cost_text is not None else None,
            paid_validation_outcome=paid_validation_outcome,
            human_action=human_action,
            reason_tags=reason_tags,
            final_content_digest=final_content_digest,
            downstream_ref=downstream_ref,
        )

    def record_validation(
        self,
        *,
        idempotency_key: str,
        project_key: str,
        job: DeepAiEscalationRecord,
        local_profile: str,
        local_model_id: str,
        local_template_version: str,
        local_attempt_count: int,
        local_quality_outcome: str,
        quality_reasons: list[str],
        paid_output_digest: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: str | Decimal,
        paid_validation_outcome: str,
        downstream_ref: str | None,
    ) -> DeepAiLearningObservation:
        return self._record(
            idempotency_key=idempotency_key,
            project_key=project_key,
            job=job,
            local_quality_outcome=local_quality_outcome,
            human_action=DeepAiHumanAction.NO_DECISION,
            reason_tags=[],
            final_content_digest=None,
            local_profile=local_profile,
            local_model_id=local_model_id,
            local_template_version=local_template_version,
            local_attempt_count=local_attempt_count,
            quality_reasons=quality_reasons,
            paid_output_digest=paid_output_digest,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            paid_validation_outcome=paid_validation_outcome,
            downstream_ref=downstream_ref,
        )

    def record_feedback(
        self,
        *,
        idempotency_key: str,
        project_key: str,
        job: DeepAiEscalationRecord,
        action: DeepAiHumanAction,
        reason_tags: list[str],
        final_content_digest: str | None,
        downstream_ref: str | None,
    ) -> DeepAiLearningObservation:
        return self._record(
            idempotency_key=idempotency_key,
            project_key=project_key,
            job=job,
            local_quality_outcome="NEEDS_DEEP_AI",
            human_action=action,
            reason_tags=reason_tags,
            final_content_digest=final_content_digest,
            local_profile=None,
            local_model_id=None,
            local_template_version=None,
            local_attempt_count=None,
            quality_reasons=[],
            paid_output_digest=None,
            input_tokens=None,
            output_tokens=None,
            cost_usd=None,
            paid_validation_outcome=None,
            downstream_ref=downstream_ref,
        )
