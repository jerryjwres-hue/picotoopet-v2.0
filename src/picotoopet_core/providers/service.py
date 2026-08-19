"""Manual usage confirmation, fixed budget and bounded coding-provider session facts."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import uuid4

from picotoopet_core.db.database import Database
from picotoopet_core.handoffs.models import HandoffRecord, HandoffStatus
from picotoopet_core.handoffs.service import HandoffService

from .models import (
    ProviderBudget,
    ProviderName,
    ProviderReadinessStatus,
    ProviderSessionRecord,
    ProviderSessionStatus,
    ProviderStatusRecord,
    ProviderUsageConfirmationRecord,
    ProviderUsageStatus,
)


class ProviderSessionError(RuntimeError):
    """Provider Session domain error."""


class ProviderSessionConflict(ProviderSessionError):
    """Resource, idempotency key or state conflict."""


class ProviderSessionPolicyError(ProviderSessionError):
    """Request violates fixed budget, approval or credential boundaries."""


class ProviderSessionService:
    """Mac Core source of truth for bounded Codex and Claude Code sessions."""

    _PROVIDERS = frozenset({"codex", "claude_code"})
    _BUDGET = ProviderBudget()
    _EXECUTION_NOTICES = {
        "codex": (
            "仅允许一次人工额度确认后的低预算 Codex Session；Mac Worker 在隔离 Git "
            "worktree 中执行，禁止自动充值、重试、提交、推送、PR、合并、标签或发布。"
        ),
        "claude_code": (
            "仅允许一次人工额度确认后的低预算 Claude Code Session；Mac Worker 在隔离 Git "
            "worktree 中执行，禁止自动充值、重试、提交、推送、PR、合并、标签或发布。"
        ),
    }
    _ONE_SESSION_MESSAGES = {
        "codex": "每个 approved Handoff 只能启动一次真实 Codex Session。",
        "claude_code": "每个 approved Handoff 只能启动一次真实 Claude Code Session。",
    }
    _TERMINAL_STATES = frozenset(
        {
            ProviderSessionStatus.READY_FOR_REVIEW,
            ProviderSessionStatus.CANCELLED,
            ProviderSessionStatus.TIMED_OUT,
            ProviderSessionStatus.STOPPED_BY_BUDGET,
            ProviderSessionStatus.STOPPED_BY_POLICY,
            ProviderSessionStatus.PROVIDER_FAILED,
            ProviderSessionStatus.RETURN_QUARANTINED,
            ProviderSessionStatus.VALIDATION_FAILED,
            ProviderSessionStatus.FAILED,
        }
    )

    def __init__(
        self,
        database: Database,
        handoffs: HandoffService,
        *,
        clock: Callable[[], datetime] | None = None,
        readiness: Callable[[], ProviderReadinessStatus] | None = None,
        readiness_by_provider: Callable[[ProviderName], ProviderReadinessStatus] | None = None,
    ) -> None:
        self.database = database
        self.handoffs = handoffs
        self._clock = clock or (lambda: datetime.now(UTC))
        legacy_codex_readiness = readiness or (lambda: ProviderReadinessStatus.UNAVAILABLE)
        if readiness_by_provider is None:
            self._readiness_by_provider = lambda provider: (
                legacy_codex_readiness()
                if provider == "codex"
                else ProviderReadinessStatus.UNAVAILABLE
            )
        else:
            self._readiness_by_provider = readiness_by_provider

    def provider_status(self, provider: ProviderName = "codex") -> ProviderStatusRecord:
        """Return minimal provider-specific readiness without reading credentials or Usage pages."""

        provider = self._require_provider_name(provider)
        readiness = self._readiness_by_provider(provider)
        label = "Codex" if provider == "codex" else "Claude Code"
        messages = {
            ProviderReadinessStatus.READY: f"Mac Worker 已检测到本机 {label} CLI 和可用认证。",
            ProviderReadinessStatus.NOT_AUTHENTICATED: f"Mac Worker 的 {label} CLI 尚未完成本机登录。",
            ProviderReadinessStatus.UNAVAILABLE: f"Mac Worker 尚未报告 {label} CLI 就绪状态。",
            ProviderReadinessStatus.POLICY_BLOCKED: f"{label} 因本地安全策略被阻止。",
        }
        return ProviderStatusRecord(
            provider=provider,
            readiness=readiness,
            message=messages[readiness],
        )

    def confirm_usage(
        self,
        handoff_id: str,
        status: ProviderUsageStatus,
        *,
        idempotency_key: str,
    ) -> ProviderUsageConfirmationRecord:
        """Record one short-lived account-level confirmation for the Handoff-bound provider."""

        key = self._require_idempotency_key(idempotency_key)
        handoff = self._require_provider_handoff(handoff_id)
        provider = cast(ProviderName, handoff.provider)
        existing = self.database.fetchone(
            "SELECT handoff_id, provider, status, preview_json "
            "FROM provider_usage_confirmations WHERE idempotency_key = ?",
            (key,),
        )
        if existing is not None:
            if (
                existing["handoff_id"] != handoff_id
                or existing["provider"] != provider
                or existing["status"] != status.value
            ):
                raise ProviderSessionConflict("Idempotency-Key 已绑定不同的额度确认。")
            return ProviderUsageConfirmationRecord.model_validate(
                json.loads(existing["preview_json"])
            )

        now = self._now()
        expires_at = now + timedelta(minutes=15)
        record = ProviderUsageConfirmationRecord(
            confirmation_id=str(uuid4()),
            handoff_id=handoff.handoff_id,
            provider=provider,
            status=status,
            request_digest=handoff.request_digest,
            package_digest=handoff.package_digest,
            budget=self._BUDGET,
            confirmed_at=now,
            expires_at=expires_at,
        )
        preview_json = self._canonical_json(record.model_dump(mode="json"))
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO provider_usage_confirmations (
                    confirmation_id, handoff_id, provider, status, request_digest,
                    package_digest, budget_json, idempotency_key, confirmed_at,
                    expires_at, preview_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.confirmation_id,
                    record.handoff_id,
                    provider,
                    record.status.value,
                    record.request_digest,
                    record.package_digest,
                    self._canonical_json(record.budget.model_dump(mode="json")),
                    key,
                    now.isoformat(),
                    expires_at.isoformat(),
                    preview_json,
                ),
            )
        return record

    def create_codex_session(
        self,
        handoff_id: str,
        *,
        idempotency_key: str,
    ) -> ProviderSessionRecord:
        """Create one bounded Codex Session for an exact approved Codex Handoff."""

        return self._create_provider_session(
            handoff_id,
            provider="codex",
            idempotency_key=idempotency_key,
        )

    def create_claude_code_session(
        self,
        handoff_id: str,
        *,
        idempotency_key: str,
    ) -> ProviderSessionRecord:
        """Create one bounded Claude Code Session for an exact approved Claude Handoff."""

        return self._create_provider_session(
            handoff_id,
            provider="claude_code",
            idempotency_key=idempotency_key,
        )

    def _create_provider_session(
        self,
        handoff_id: str,
        *,
        provider: ProviderName,
        idempotency_key: str,
    ) -> ProviderSessionRecord:
        provider = self._require_provider_name(provider)
        key = self._require_idempotency_key(idempotency_key)
        existing = self.database.fetchone(
            "SELECT handoff_id, provider, preview_json FROM provider_sessions "
            "WHERE idempotency_key = ?",
            (key,),
        )
        if existing is not None:
            if existing["handoff_id"] != handoff_id or existing["provider"] != provider:
                raise ProviderSessionConflict("Idempotency-Key 已绑定不同的 Handoff 或 Provider。")
            return ProviderSessionRecord.model_validate(json.loads(existing["preview_json"]))

        handoff = self._require_provider_handoff(handoff_id, expected_provider=provider)
        previous = self.database.fetchone(
            "SELECT session_id FROM provider_sessions WHERE handoff_id = ? AND provider = ?",
            (handoff_id, provider),
        )
        if previous is not None:
            raise ProviderSessionConflict(self._ONE_SESSION_MESSAGES[provider])
        active_count = int(
            self.database.scalar(
                "SELECT COUNT(*) FROM provider_sessions WHERE status NOT IN "
                "('ready_for_review','cancelled','timed_out','stopped_by_budget',"
                "'stopped_by_policy','provider_failed','return_quarantined',"
                "'validation_failed','failed')"
            )
            or 0
        )
        if active_count >= self._BUDGET.concurrency:
            raise ProviderSessionPolicyError("当前已有真实 Coding Provider Session 正在运行。")

        confirmation = self._latest_confirmation(handoff)
        if confirmation.status is not ProviderUsageStatus.CONFIRMED_AVAILABLE:
            raise ProviderSessionPolicyError("额度状态不是 confirmed_available，不能启动。")
        if confirmation.expires_at <= self._now():
            raise ProviderSessionPolicyError("额度人工确认已过期。")

        now = self._now()
        record = ProviderSessionRecord(
            session_id=str(uuid4()),
            handoff_id=handoff.handoff_id,
            provider=provider,
            status=ProviderSessionStatus.WAITING_PROVIDER_READY,
            request_digest=handoff.request_digest,
            package_digest=handoff.package_digest,
            budget=self._BUDGET,
            created_at=now,
            updated_at=now,
            execution_notice=self._EXECUTION_NOTICES[provider],
        )
        preview_json = self._canonical_json(record.model_dump(mode="json"))
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO provider_sessions (
                    session_id, handoff_id, provider, status, request_digest,
                    package_digest, budget_json, turns_used, elapsed_seconds,
                    changed_file_count, return_id, failure_code,
                    provider_usage_unknown, idempotency_key, created_at, updated_at,
                    finished_at, preview_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, 0, NULL, NULL, 1, ?, ?, ?, NULL, ?)
                """,
                (
                    record.session_id,
                    record.handoff_id,
                    provider,
                    record.status.value,
                    record.request_digest,
                    record.package_digest,
                    self._canonical_json(record.budget.model_dump(mode="json")),
                    key,
                    now.isoformat(),
                    now.isoformat(),
                    preview_json,
                ),
            )
        return record

    def list_sessions(self, *, limit: int = 100) -> list[ProviderSessionRecord]:
        bounded = max(1, min(limit, 100))
        rows = self.database.fetchall(
            "SELECT preview_json FROM provider_sessions ORDER BY created_at DESC LIMIT ?",
            (bounded,),
        )
        return [
            ProviderSessionRecord.model_validate(json.loads(row["preview_json"]))
            for row in rows
        ]

    def get_session(self, session_id: str) -> ProviderSessionRecord:
        row = self.database.fetchone(
            "SELECT preview_json FROM provider_sessions WHERE session_id = ?",
            (session_id,),
        )
        if row is None:
            raise KeyError(f"Provider Session 不存在：{session_id}")
        return ProviderSessionRecord.model_validate(json.loads(row["preview_json"]))

    def cancel_session(self, session_id: str) -> ProviderSessionRecord:
        current = self.get_session(session_id)
        if current.status in self._TERMINAL_STATES:
            return current
        return self.transition(
            session_id,
            ProviderSessionStatus.CANCELLED,
            failure_code="PROVIDER_CANCELLED",
            finished=True,
        )

    def transition(
        self,
        session_id: str,
        status: ProviderSessionStatus,
        *,
        turns_used: int | None = None,
        elapsed_seconds: int | None = None,
        changed_file_count: int | None = None,
        return_id: str | None = None,
        failure_code: str | None = None,
        provider_usage_unknown: bool | None = None,
        finished: bool = False,
    ) -> ProviderSessionRecord:
        """Worker/Core optimistic state update for safe progress facts."""

        current = self.get_session(session_id)
        now = self._now()
        update = {
            "status": status,
            "turns_used": current.turns_used if turns_used is None else turns_used,
            "elapsed_seconds": (
                current.elapsed_seconds if elapsed_seconds is None else elapsed_seconds
            ),
            "changed_file_count": (
                current.changed_file_count
                if changed_file_count is None
                else changed_file_count
            ),
            "return_id": current.return_id if return_id is None else return_id,
            "failure_code": failure_code,
            "provider_usage_unknown": (
                current.provider_usage_unknown
                if provider_usage_unknown is None
                else provider_usage_unknown
            ),
            "updated_at": now,
            "finished_at": now if finished else current.finished_at,
        }
        preview = current.model_copy(update=update)
        preview_json = self._canonical_json(preview.model_dump(mode="json"))
        with self.database.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE provider_sessions
                SET status = ?, turns_used = ?, elapsed_seconds = ?,
                    changed_file_count = ?, return_id = ?, failure_code = ?,
                    provider_usage_unknown = ?, updated_at = ?, finished_at = ?,
                    preview_json = ?
                WHERE session_id = ? AND status = ?
                """,
                (
                    preview.status.value,
                    preview.turns_used,
                    preview.elapsed_seconds,
                    preview.changed_file_count,
                    preview.return_id,
                    preview.failure_code,
                    int(preview.provider_usage_unknown),
                    now.isoformat(),
                    preview.finished_at.isoformat() if preview.finished_at else None,
                    preview_json,
                    session_id,
                    current.status.value,
                ),
            )
            if cursor.rowcount != 1:
                raise ProviderSessionConflict("Provider Session 状态已由其他请求更新。")
        return preview

    def _latest_confirmation(
        self,
        handoff: HandoffRecord,
    ) -> ProviderUsageConfirmationRecord:
        provider = cast(ProviderName, handoff.provider)
        row = self.database.fetchone(
            """
            SELECT preview_json FROM provider_usage_confirmations
            WHERE handoff_id = ? AND provider = ? AND request_digest = ?
              AND package_digest = ?
            ORDER BY confirmed_at DESC LIMIT 1
            """,
            (
                handoff.handoff_id,
                provider,
                handoff.request_digest,
                handoff.package_digest,
            ),
        )
        if row is None:
            raise ProviderSessionPolicyError("尚未记录此 Handoff 的额度人工确认。")
        return ProviderUsageConfirmationRecord.model_validate(
            json.loads(row["preview_json"])
        )

    def _require_provider_handoff(
        self,
        handoff_id: str,
        *,
        expected_provider: ProviderName | None = None,
    ) -> HandoffRecord:
        handoff = self.handoffs.get(handoff_id)
        if handoff.status is not HandoffStatus.APPROVED:
            raise ProviderSessionPolicyError("只有 approved Handoff 可以使用 Coding Provider。")
        if handoff.provider not in self._PROVIDERS:
            raise ProviderSessionPolicyError("Handoff 未绑定受控 Coding Provider。")
        if expected_provider is not None and handoff.provider != expected_provider:
            raise ProviderSessionPolicyError("Handoff 与请求的 Coding Provider 不匹配。")
        if handoff.expires_at <= self._now():
            raise ProviderSessionPolicyError("Handoff 已过期。")
        return handoff

    @classmethod
    def _require_provider_name(cls, provider: str) -> ProviderName:
        if provider not in cls._PROVIDERS:
            raise ProviderSessionPolicyError("未知 Coding Provider。")
        return cast(ProviderName, provider)

    @staticmethod
    def _require_idempotency_key(value: str) -> str:
        key = value.strip()
        if not 1 <= len(key) <= 200 or any(ord(character) < 33 for character in key):
            raise ProviderSessionPolicyError("Idempotency-Key 不符合固定安全格式。")
        return key

    @staticmethod
    def _canonical_json(value: object) -> str:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
