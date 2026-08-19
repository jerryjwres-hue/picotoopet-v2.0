"""Core-owned frugal coding-provider selection and bounded Handoff preparation."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict

from picotoopet_core.db.database import Database
from picotoopet_core.deep_ai.frugal import (
    FrugalAssessmentSignals,
    FrugalEscalationArbiter,
    FrugalEscalationInput,
    ProviderCandidate,
    ProviderEscalationDecision,
    ProviderHistorySnapshot,
)
from picotoopet_core.deep_ai.frugal_repository import FrugalDecisionRepository
from picotoopet_core.handoffs.models import HandoffPrepareRequest, HandoffStatus
from picotoopet_core.handoffs.service import HandoffService

from .models import (
    ProviderName,
    ProviderSessionRecord,
    ProviderSessionStatus,
    ProviderUsageConfirmationRecord,
    ProviderUsageStatus,
)
from .service import ProviderSessionService

PlanStage = Literal[
    "local_only",
    "manual_review",
    "awaiting_handoff_approval",
    "awaiting_usage_confirmation",
    "provider_session_waiting",
    "provider_session_active",
    "provider_ready_for_review",
]


class CodingEscalationPlan(BaseModel):
    """Read-only product projection of one Core-owned frugal decision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    decision: ProviderEscalationDecision
    stage: PlanStage
    handoff_id: str | None = None
    session_id: str | None = None


class CodingEscalationService:
    """Choose zero or one coding provider without accepting a caller-selected provider."""

    _TEMPLATES: dict[ProviderName, str] = {
        "codex": "picotoopet-repo-maintenance-codex-v1",
        "claude_code": "picotoopet-repo-maintenance-claude-code-v1",
    }
    _TERMINAL_VALIDATION_FAILURES = frozenset(
        {
            "artifact_invalid",
            "base_mismatch",
            "policy_blocked",
            "validation_failed",
            "failed",
        }
    )
    _ACTIVE_SESSION_STATES = frozenset(
        {
            ProviderSessionStatus.STAGING,
            ProviderSessionStatus.RUNNING,
            ProviderSessionStatus.RETURNING,
            ProviderSessionStatus.VALIDATING,
        }
    )

    def __init__(
        self,
        *,
        database: Database,
        handoffs: HandoffService,
        provider_sessions: ProviderSessionService,
        decisions: FrugalDecisionRepository,
        arbiter: FrugalEscalationArbiter | None = None,
    ) -> None:
        self.database = database
        self.handoffs = handoffs
        self.provider_sessions = provider_sessions
        self.decisions = decisions
        self.arbiter = arbiter or FrugalEscalationArbiter()

    def evaluate(
        self,
        *,
        goal_id: str,
        task_class: str,
        title: str,
        objective: str,
        signals: FrugalAssessmentSignals,
    ) -> CodingEscalationPlan:
        """Persist a deterministic decision and prepare at most one approval-bound Handoff."""

        sessions_used, attempted, previous_outcome = self._goal_execution_state(goal_id)
        candidates = tuple(self._candidate(provider) for provider in ("codex", "claude_code"))
        decision = self.arbiter.decide(
            FrugalEscalationInput(
                goal_id=goal_id,
                task_class=task_class,
                signals=signals,
                candidates=candidates,
                sessions_used=sessions_used,
                attempted_providers=attempted,
                previous_validation_outcome=previous_outcome,
            )
        )
        self.decisions.put(decision)

        if decision.action == "local_only":
            return CodingEscalationPlan(decision=decision, stage="local_only")
        if decision.action != "external_provider" or decision.chosen_provider == "none":
            return CodingEscalationPlan(decision=decision, stage="manual_review")

        provider = cast(ProviderName, decision.chosen_provider)
        prepare_key = self._handoff_key(decision.decision_digest)
        handoff = self.handoffs.prepare(
            HandoffPrepareRequest(
                template_id=self._TEMPLATES[provider],  # type: ignore[arg-type]
                title=title,
                objective=objective,
                expires_seconds=1800,
            ),
            idempotency_key=prepare_key,
        )
        if handoff.status is HandoffStatus.PREPARED:
            handoff = self.handoffs.submit_for_approval(
                handoff.handoff_id,
                idempotency_key=self._approval_key(decision.decision_digest),
            )
        return self._plan_for_handoff(decision, handoff.handoff_id)

    def reconcile(self, goal_id: str) -> CodingEscalationPlan:
        """Advance one chosen provider after existing approval and Usage gates are satisfied."""

        decision = self.decisions.latest_for_goal(goal_id).decision
        if decision.action == "local_only":
            return CodingEscalationPlan(decision=decision, stage="local_only")
        if decision.action != "external_provider" or decision.chosen_provider == "none":
            return CodingEscalationPlan(decision=decision, stage="manual_review")

        handoff_row = self.database.fetchone(
            "SELECT handoff_id FROM handoffs WHERE prepare_idempotency_key = ?",
            (self._handoff_key(decision.decision_digest),),
        )
        if handoff_row is None:
            return CodingEscalationPlan(decision=decision, stage="manual_review")
        handoff_id = str(handoff_row["handoff_id"])
        handoff = self.handoffs.get(handoff_id)
        if handoff.status is HandoffStatus.PREPARED:
            handoff = self.handoffs.submit_for_approval(
                handoff_id,
                idempotency_key=self._approval_key(decision.decision_digest),
            )
        if handoff.status is HandoffStatus.WAITING_APPROVAL:
            return CodingEscalationPlan(
                decision=decision,
                stage="awaiting_handoff_approval",
                handoff_id=handoff_id,
            )
        if handoff.status is not HandoffStatus.APPROVED:
            return CodingEscalationPlan(
                decision=decision,
                stage="manual_review",
                handoff_id=handoff_id,
            )

        provider = cast(ProviderName, decision.chosen_provider)
        existing = self._session_for_handoff(handoff_id, provider)
        if existing is not None:
            return self._plan_for_session(decision, handoff_id, existing)

        confirmation = self._latest_usage_confirmation(handoff_id, provider)
        if (
            confirmation is None
            or confirmation.status is not ProviderUsageStatus.CONFIRMED_AVAILABLE
            or confirmation.expires_at <= datetime.now(UTC)
        ):
            return CodingEscalationPlan(
                decision=decision,
                stage="awaiting_usage_confirmation",
                handoff_id=handoff_id,
            )

        session_key = self._session_key(decision.decision_digest)
        if provider == "codex":
            session = self.provider_sessions.create_codex_session(
                handoff_id,
                idempotency_key=session_key,
            )
        else:
            session = self.provider_sessions.create_claude_code_session(
                handoff_id,
                idempotency_key=session_key,
            )
        return self._plan_for_session(decision, handoff_id, session)

    def reconcile_pending(self, *, limit: int = 20) -> list[CodingEscalationPlan]:
        """Boundedly advance only Goals whose latest decision still authorizes one provider."""

        safe_limit = max(1, min(int(limit), 100))
        rows = self.database.fetchall(
            """
            SELECT decision.goal_id
            FROM deep_ai_frugal_decisions AS decision
            WHERE decision.chosen_provider IN ('codex', 'claude_code')
              AND NOT EXISTS (
                  SELECT 1
                  FROM deep_ai_frugal_decisions AS newer
                  WHERE newer.goal_id = decision.goal_id
                    AND (
                        newer.created_at > decision.created_at
                        OR (
                            newer.created_at = decision.created_at
                            AND newer.decision_id > decision.decision_id
                        )
                    )
              )
            ORDER BY decision.created_at DESC, decision.decision_id DESC
            LIMIT ?
            """,
            (safe_limit,),
        )
        return [self.reconcile(str(row["goal_id"])) for row in rows]

    def provider_history(self, provider: ProviderName) -> ProviderHistorySnapshot:
        """Count only completed local adoption-validation outcomes, never provider self-reports."""

        rows = self.database.fetchall(
            """
            SELECT pac.status
            FROM provider_adoption_candidates AS pac
            JOIN provider_sessions AS ps ON ps.session_id = pac.session_id
            WHERE ps.provider = ?
            ORDER BY pac.created_at, pac.candidate_id
            """,
            (provider,),
        )
        success_count = 0
        sample_size = 0
        for row in rows:
            status = str(row["status"])
            if status == "adoption_ready":
                success_count += 1
                sample_size += 1
            elif status in self._TERMINAL_VALIDATION_FAILURES:
                sample_size += 1
        return ProviderHistorySnapshot(
            success_count=success_count,
            sample_size=sample_size,
        )

    def _candidate(self, provider: ProviderName) -> ProviderCandidate:
        readiness = self.provider_sessions.provider_status(provider).readiness.value
        return ProviderCandidate(
            provider=provider,
            readiness=readiness,  # type: ignore[arg-type]
            history=self.provider_history(provider),
            expected_quality_uplift=0.45,
            cost_penalty=0.10,
            latency_penalty=0.10,
            permission_risk=0.10,
        )

    def _plan_for_handoff(
        self,
        decision: ProviderEscalationDecision,
        handoff_id: str,
    ) -> CodingEscalationPlan:
        handoff = self.handoffs.get(handoff_id)
        if handoff.status is HandoffStatus.WAITING_APPROVAL:
            stage: PlanStage = "awaiting_handoff_approval"
        elif handoff.status is HandoffStatus.APPROVED:
            stage = "awaiting_usage_confirmation"
        else:
            stage = "manual_review"
        return CodingEscalationPlan(
            decision=decision,
            stage=stage,
            handoff_id=handoff_id,
        )

    def _session_for_handoff(
        self,
        handoff_id: str,
        provider: ProviderName,
    ) -> ProviderSessionRecord | None:
        row = self.database.fetchone(
            "SELECT preview_json FROM provider_sessions WHERE handoff_id = ? AND provider = ? "
            "ORDER BY created_at, session_id LIMIT 1",
            (handoff_id, provider),
        )
        if row is None:
            return None
        return ProviderSessionRecord.model_validate(json.loads(row["preview_json"]))

    def _latest_usage_confirmation(
        self,
        handoff_id: str,
        provider: ProviderName,
    ) -> ProviderUsageConfirmationRecord | None:
        handoff = self.handoffs.get(handoff_id)
        row = self.database.fetchone(
            """
            SELECT preview_json FROM provider_usage_confirmations
            WHERE handoff_id = ? AND provider = ? AND request_digest = ?
              AND package_digest = ?
            ORDER BY confirmed_at DESC LIMIT 1
            """,
            (handoff_id, provider, handoff.request_digest, handoff.package_digest),
        )
        if row is None:
            return None
        return ProviderUsageConfirmationRecord.model_validate(json.loads(row["preview_json"]))

    def _plan_for_session(
        self,
        decision: ProviderEscalationDecision,
        handoff_id: str,
        session: ProviderSessionRecord,
    ) -> CodingEscalationPlan:
        if session.status is ProviderSessionStatus.WAITING_PROVIDER_READY:
            stage: PlanStage = "provider_session_waiting"
        elif session.status in self._ACTIVE_SESSION_STATES:
            stage = "provider_session_active"
        elif session.status is ProviderSessionStatus.READY_FOR_REVIEW:
            stage = "provider_ready_for_review"
        else:
            stage = "manual_review"
        return CodingEscalationPlan(
            decision=decision,
            stage=stage,
            handoff_id=handoff_id,
            session_id=session.session_id,
        )

    def _goal_execution_state(
        self,
        goal_id: str,
    ) -> tuple[int, tuple[ProviderName, ...], Literal["pass", "failed", "uncertain"] | None]:
        records = list(reversed(self.decisions.list_for_goal(goal_id, limit=100)))
        seen_sessions: set[str] = set()
        attempts: list[ProviderName] = []
        latest_session_id: str | None = None
        for record in records:
            decision = record.decision
            if decision.action != "external_provider" or decision.chosen_provider == "none":
                continue
            handoff = self.database.fetchone(
                "SELECT handoff_id FROM handoffs WHERE prepare_idempotency_key = ?",
                (self._handoff_key(decision.decision_digest),),
            )
            if handoff is None:
                continue
            session = self.database.fetchone(
                "SELECT session_id, provider FROM provider_sessions "
                "WHERE handoff_id = ? ORDER BY created_at, session_id LIMIT 1",
                (handoff["handoff_id"],),
            )
            if session is None or session["session_id"] in seen_sessions:
                continue
            seen_sessions.add(session["session_id"])
            attempts.append(cast(ProviderName, session["provider"]))
            latest_session_id = session["session_id"]

        if len(attempts) > 2:
            raise RuntimeError("FRUGAL_PROVIDER_SESSION_LIMIT_BREACHED")
        outcome = self._validation_outcome(latest_session_id) if latest_session_id else None
        return len(attempts), tuple(attempts), outcome

    def _validation_outcome(
        self,
        session_id: str,
    ) -> Literal["pass", "failed", "uncertain"] | None:
        row = self.database.fetchone(
            "SELECT status FROM provider_adoption_candidates WHERE session_id = ? "
            "ORDER BY created_at DESC, candidate_id DESC LIMIT 1",
            (session_id,),
        )
        if row is None:
            return None
        status = str(row["status"])
        if status == "adoption_ready":
            return "pass"
        if status in self._TERMINAL_VALIDATION_FAILURES:
            return "failed"
        return None

    @staticmethod
    def _handoff_key(decision_digest: str) -> str:
        return f"frugal-handoff:{decision_digest}"

    @staticmethod
    def _approval_key(decision_digest: str) -> str:
        return f"frugal-approval:{decision_digest}"

    @staticmethod
    def _session_key(decision_digest: str) -> str:
        return f"frugal-session:{decision_digest}"
