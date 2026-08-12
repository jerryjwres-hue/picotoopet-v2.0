"""Durable repository for paid-AI escalation and quality-learning facts."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from picotoopet_core.db.database import Database

from .models import (
    DeepAiAttemptRecord,
    DeepAiAttemptStatus,
    DeepAiEscalationRecord,
    DeepAiEscalationStatus,
    DeepAiHumanAction,
    DeepAiLearningEvent,
    DeepAiValidationOutcome,
)


class DeepAiRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    def _money(value: str | Decimal) -> Decimal:
        try:
            parsed = Decimal(str(value))
        except InvalidOperation as exc:
            raise ValueError("DEEP_AI_COST_INVALID") from exc
        if not parsed.is_finite() or parsed < 0:
            raise ValueError("DEEP_AI_COST_INVALID")
        return parsed.quantize(Decimal("0.000001")).normalize()

    @classmethod
    def _money_text(cls, value: str | Decimal) -> str:
        parsed = cls._money(value)
        text = format(parsed, "f")
        if "." not in text:
            return f"{text}.00"
        whole, fraction = text.split(".", 1)
        fraction = fraction.rstrip("0")
        if len(fraction) < 2:
            fraction = fraction.ljust(2, "0")
        return f"{whole}.{fraction}"

    @staticmethod
    def _job_from_row(row: Any) -> DeepAiEscalationRecord:
        return DeepAiEscalationRecord(
            escalation_job_id=row["escalation_job_id"],
            source_kind=row["source_kind"],
            source_id=row["source_id"],
            source_digest=row["source_digest"],
            policy_version=row["policy_version"],
            sanitized_package_relpath=row["sanitized_package_relpath"],
            sanitized_package_digest=row["sanitized_package_digest"],
            sanitizer_version=row["sanitizer_version"],
            provider_profile_id=row["provider_profile_id"],
            provider_profile_digest=row["provider_profile_digest"],
            model_id=row["model_id"],
            max_input_tokens=row["max_input_tokens"],
            max_output_tokens=row["max_output_tokens"],
            max_calls=row["max_calls"],
            max_cost_usd=Decimal(row["max_cost_usd"]),
            status=DeepAiEscalationStatus(row["status"]),
            approval_id=row["approval_id"],
            approval_digest=row["approval_digest"],
            approval_expires_at=(
                datetime.fromisoformat(row["approval_expires_at"])
                if row["approval_expires_at"]
                else None
            ),
            validation_outcome=(
                DeepAiValidationOutcome(row["validation_outcome"])
                if row["validation_outcome"]
                else None
            ),
            accepted_result_digest=row["accepted_result_digest"],
            accepted_result_relpath=row["accepted_result_relpath"],
            failure_code=row["failure_code"],
            error_message=row["error_message"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            finished_at=(
                datetime.fromisoformat(row["finished_at"]) if row["finished_at"] else None
            ),
        )

    @staticmethod
    def _attempt_from_row(row: Any) -> DeepAiAttemptRecord:
        return DeepAiAttemptRecord(
            attempt_id=row["attempt_id"],
            escalation_job_id=row["escalation_job_id"],
            attempt_number=row["attempt_number"],
            status=DeepAiAttemptStatus(row["status"]),
            estimated_cost_usd=Decimal(row["estimated_cost_usd"]),
            provider_request_id=row["provider_request_id"],
            response_digest=row["response_digest"],
            response_relpath=row["response_relpath"],
            input_tokens=row["input_tokens"],
            output_tokens=row["output_tokens"],
            actual_cost_usd=(
                Decimal(row["actual_cost_usd"]) if row["actual_cost_usd"] else None
            ),
            cost_source=row["cost_source"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            completed_at=(
                datetime.fromisoformat(row["completed_at"])
                if row["completed_at"]
                else None
            ),
        )

    @staticmethod
    def _learning_from_row(row: Any) -> DeepAiLearningEvent:
        return DeepAiLearningEvent(
            event_id=row["event_id"],
            idempotency_key=row["idempotency_key"],
            project_key=row["project_key"],
            source_kind=row["source_kind"],
            source_id=row["source_id"],
            local_quality_outcome=row["local_quality_outcome"],
            escalation_job_id=row["escalation_job_id"],
            human_action=DeepAiHumanAction(row["human_action"]),
            reason_tags=json.loads(row["reason_tags_json"]),
            final_content_digest=row["final_content_digest"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def prepare_job(
        self,
        *,
        escalation_job_id: str,
        source_kind: str,
        source_id: str,
        source_digest: str,
        policy_version: str,
        sanitized_package_relpath: str,
        sanitized_package_digest: str,
        sanitizer_version: str,
        provider_profile_id: str,
        provider_profile_digest: str,
        model_id: str,
        max_input_tokens: int,
        max_output_tokens: int,
        max_calls: int,
        max_cost_usd: str | Decimal,
    ) -> DeepAiEscalationRecord:
        money_text = self._money_text(max_cost_usd)
        frozen = (
            sanitized_package_relpath,
            sanitized_package_digest,
            sanitizer_version,
            provider_profile_id,
            provider_profile_digest,
            model_id,
            max_input_tokens,
            max_output_tokens,
            max_calls,
            money_text,
        )
        with self.database.transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM deep_ai_escalation_jobs "
                "WHERE source_kind=? AND source_id=? AND source_digest=? AND policy_version=?",
                (source_kind, source_id, source_digest, policy_version),
            ).fetchone()
            if existing is not None:
                existing_frozen = (
                    existing["sanitized_package_relpath"],
                    existing["sanitized_package_digest"],
                    existing["sanitizer_version"],
                    existing["provider_profile_id"],
                    existing["provider_profile_digest"],
                    existing["model_id"],
                    existing["max_input_tokens"],
                    existing["max_output_tokens"],
                    existing["max_calls"],
                    self._money_text(existing["max_cost_usd"]),
                )
                if existing_frozen != frozen:
                    raise ValueError("DEEP_AI_EXECUTION_ENVELOPE_IMMUTABLE")
                return self._job_from_row(existing)
            timestamp = self._now()
            connection.execute(
                "INSERT INTO deep_ai_escalation_jobs("
                "escalation_job_id,source_kind,source_id,source_digest,policy_version,"
                "sanitized_package_relpath,sanitized_package_digest,sanitizer_version,"
                "provider_profile_id,provider_profile_digest,model_id,max_input_tokens,"
                "max_output_tokens,max_calls,max_cost_usd,status,created_at,updated_at"
                ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    escalation_job_id,
                    source_kind,
                    source_id,
                    source_digest,
                    policy_version,
                    sanitized_package_relpath,
                    sanitized_package_digest,
                    sanitizer_version,
                    provider_profile_id,
                    provider_profile_digest,
                    model_id,
                    max_input_tokens,
                    max_output_tokens,
                    max_calls,
                    money_text,
                    DeepAiEscalationStatus.PREPARED.value,
                    timestamp,
                    timestamp,
                ),
            )
        return self.get_job(escalation_job_id)

    def get_job(self, escalation_job_id: str) -> DeepAiEscalationRecord:
        row = self.database.fetchone(
            "SELECT * FROM deep_ai_escalation_jobs WHERE escalation_job_id=?",
            (escalation_job_id,),
        )
        if row is None:
            raise KeyError(escalation_job_id)
        return self._job_from_row(row)

    def list_jobs(self, *, limit: int = 100) -> list[DeepAiEscalationRecord]:
        rows = self.database.fetchall(
            "SELECT * FROM deep_ai_escalation_jobs ORDER BY created_at DESC LIMIT ?",
            (min(max(limit, 1), 500),),
        )
        return [self._job_from_row(row) for row in rows]

    def set_job_status(
        self,
        escalation_job_id: str,
        status: DeepAiEscalationStatus,
        *,
        failure_code: str | None = None,
        error_message: str | None = None,
        finished: bool = False,
    ) -> DeepAiEscalationRecord:
        now = self._now()
        self.database.execute(
            "UPDATE deep_ai_escalation_jobs SET status=?,failure_code=?,error_message=?,"
            "updated_at=?,finished_at=? WHERE escalation_job_id=?",
            (
                status.value,
                failure_code,
                error_message,
                now,
                now if finished else None,
                escalation_job_id,
            ),
        )
        return self.get_job(escalation_job_id)

    def bind_approval_once(
        self,
        escalation_job_id: str,
        *,
        approval_id: str,
        approval_digest: str,
        approval_expires_at: datetime,
    ) -> DeepAiEscalationRecord:
        expires_text = approval_expires_at.isoformat()
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM deep_ai_escalation_jobs WHERE escalation_job_id=?",
                (escalation_job_id,),
            ).fetchone()
            if row is None:
                raise KeyError(escalation_job_id)
            current = (
                row["approval_id"],
                row["approval_digest"],
                row["approval_expires_at"],
            )
            requested = (approval_id, approval_digest, expires_text)
            if current[0] is not None:
                if current != requested:
                    raise ValueError("DEEP_AI_APPROVAL_IMMUTABLE")
                return self._job_from_row(row)
            connection.execute(
                "UPDATE deep_ai_escalation_jobs SET approval_id=?,approval_digest=?,"
                "approval_expires_at=?,status=?,updated_at=? WHERE escalation_job_id=?",
                (
                    approval_id,
                    approval_digest,
                    expires_text,
                    DeepAiEscalationStatus.WAITING_APPROVAL.value,
                    self._now(),
                    escalation_job_id,
                ),
            )
        return self.get_job(escalation_job_id)

    def reserve_attempt(
        self,
        *,
        escalation_job_id: str,
        attempt_id: str,
        attempt_number: int,
        estimated_cost_usd: str | Decimal,
    ) -> DeepAiAttemptRecord:
        if attempt_number < 1:
            raise ValueError("DEEP_AI_ATTEMPT_NUMBER_INVALID")
        estimated = self._money_text(estimated_cost_usd)
        with self.database.transaction() as connection:
            job = connection.execute(
                "SELECT max_calls FROM deep_ai_escalation_jobs WHERE escalation_job_id=?",
                (escalation_job_id,),
            ).fetchone()
            if job is None:
                raise KeyError(escalation_job_id)
            if attempt_number > job["max_calls"]:
                raise ValueError("DEEP_AI_CALL_BUDGET_EXHAUSTED")
            existing = connection.execute(
                "SELECT * FROM deep_ai_attempts WHERE escalation_job_id=? AND attempt_number=?",
                (escalation_job_id, attempt_number),
            ).fetchone()
            if existing is not None:
                if (
                    existing["attempt_id"] == attempt_id
                    and self._money_text(existing["estimated_cost_usd"]) == estimated
                ):
                    return self._attempt_from_row(existing)
                raise ValueError("DEEP_AI_ATTEMPT_ALREADY_RESERVED")
            timestamp = self._now()
            connection.execute(
                "INSERT INTO deep_ai_attempts("
                "attempt_id,escalation_job_id,attempt_number,status,estimated_cost_usd,created_at,updated_at"
                ") VALUES (?,?,?,?,?,?,?)",
                (
                    attempt_id,
                    escalation_job_id,
                    attempt_number,
                    DeepAiAttemptStatus.RESERVED.value,
                    estimated,
                    timestamp,
                    timestamp,
                ),
            )
        return self.get_attempt(attempt_id)

    def get_attempt(self, attempt_id: str) -> DeepAiAttemptRecord:
        row = self.database.fetchone(
            "SELECT * FROM deep_ai_attempts WHERE attempt_id=?",
            (attempt_id,),
        )
        if row is None:
            raise KeyError(attempt_id)
        return self._attempt_from_row(row)

    def list_attempts(self, escalation_job_id: str) -> list[DeepAiAttemptRecord]:
        rows = self.database.fetchall(
            "SELECT * FROM deep_ai_attempts WHERE escalation_job_id=? ORDER BY attempt_number ASC",
            (escalation_job_id,),
        )
        return [self._attempt_from_row(row) for row in rows]

    def set_attempt_status(
        self,
        attempt_id: str,
        status: DeepAiAttemptStatus,
    ) -> DeepAiAttemptRecord:
        current = self.get_attempt(attempt_id)
        if current.status is DeepAiAttemptStatus.COMPLETED and status is not current.status:
            raise ValueError("DEEP_AI_COMPLETED_ATTEMPT_IMMUTABLE")
        self.database.execute(
            "UPDATE deep_ai_attempts SET status=?,updated_at=? WHERE attempt_id=?",
            (status.value, self._now(), attempt_id),
        )
        return self.get_attempt(attempt_id)

    def bind_attempt_result(
        self,
        attempt_id: str,
        *,
        provider_request_id: str,
        response_digest: str,
        response_relpath: str,
        input_tokens: int,
        output_tokens: int,
        actual_cost_usd: str | Decimal,
        cost_source: str,
    ) -> DeepAiAttemptRecord:
        actual = self._money_text(actual_cost_usd)
        requested = (
            provider_request_id,
            response_digest,
            response_relpath,
            input_tokens,
            output_tokens,
            actual,
            cost_source,
        )
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM deep_ai_attempts WHERE attempt_id=?",
                (attempt_id,),
            ).fetchone()
            if row is None:
                raise KeyError(attempt_id)
            if row["provider_request_id"] is not None:
                existing = (
                    row["provider_request_id"],
                    row["response_digest"],
                    row["response_relpath"],
                    row["input_tokens"],
                    row["output_tokens"],
                    self._money_text(row["actual_cost_usd"]),
                    row["cost_source"],
                )
                if existing != requested:
                    raise ValueError("DEEP_AI_USAGE_IMMUTABLE")
                return self._attempt_from_row(row)
            timestamp = self._now()
            connection.execute(
                "UPDATE deep_ai_attempts SET status=?,provider_request_id=?,response_digest=?,"
                "response_relpath=?,input_tokens=?,output_tokens=?,actual_cost_usd=?,cost_source=?,"
                "updated_at=?,completed_at=? WHERE attempt_id=?",
                (
                    DeepAiAttemptStatus.COMPLETED.value,
                    provider_request_id,
                    response_digest,
                    response_relpath,
                    input_tokens,
                    output_tokens,
                    actual,
                    cost_source,
                    timestamp,
                    timestamp,
                    attempt_id,
                ),
            )
        return self.get_attempt(attempt_id)

    def append_learning_event(
        self,
        *,
        event_id: str,
        idempotency_key: str,
        project_key: str,
        source_kind: str,
        source_id: str,
        local_quality_outcome: str,
        escalation_job_id: str | None,
        human_action: DeepAiHumanAction,
        reason_tags: list[str],
        final_content_digest: str | None,
    ) -> DeepAiLearningEvent:
        reason_json = json.dumps(
            reason_tags,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        requested = (
            project_key,
            source_kind,
            source_id,
            local_quality_outcome,
            escalation_job_id,
            human_action.value,
            reason_json,
            final_content_digest,
        )
        with self.database.transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM deep_ai_learning_events WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if existing is not None:
                current = (
                    existing["project_key"],
                    existing["source_kind"],
                    existing["source_id"],
                    existing["local_quality_outcome"],
                    existing["escalation_job_id"],
                    existing["human_action"],
                    existing["reason_tags_json"],
                    existing["final_content_digest"],
                )
                if current != requested:
                    raise ValueError("DEEP_AI_LEARNING_EVENT_IMMUTABLE")
                return self._learning_from_row(existing)
            connection.execute(
                "INSERT INTO deep_ai_learning_events("
                "event_id,idempotency_key,project_key,source_kind,source_id,local_quality_outcome,"
                "escalation_job_id,human_action,reason_tags_json,final_content_digest,created_at"
                ") VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    event_id,
                    idempotency_key,
                    project_key,
                    source_kind,
                    source_id,
                    local_quality_outcome,
                    escalation_job_id,
                    human_action.value,
                    reason_json,
                    final_content_digest,
                    self._now(),
                ),
            )
        row = self.database.fetchone(
            "SELECT * FROM deep_ai_learning_events WHERE event_id=?",
            (event_id,),
        )
        assert row is not None
        return self._learning_from_row(row)

    def list_learning_events(
        self,
        *,
        project_key: str | None = None,
        limit: int = 100,
    ) -> list[DeepAiLearningEvent]:
        capped = min(max(limit, 1), 500)
        if project_key is None:
            rows = self.database.fetchall(
                "SELECT * FROM deep_ai_learning_events ORDER BY created_at DESC LIMIT ?",
                (capped,),
            )
        else:
            rows = self.database.fetchall(
                "SELECT * FROM deep_ai_learning_events WHERE project_key=? "
                "ORDER BY created_at DESC LIMIT ?",
                (project_key, capped),
            )
        return [self._learning_from_row(row) for row in rows]
