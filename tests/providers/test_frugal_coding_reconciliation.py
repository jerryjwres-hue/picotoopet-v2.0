from __future__ import annotations

import json
from pathlib import Path

from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths
from picotoopet_core.db.database import Database
from picotoopet_core.deep_ai.frugal import FrugalAssessmentSignals
from picotoopet_core.deep_ai.frugal_repository import FrugalDecisionRepository
from picotoopet_core.handoffs.approvals import HandoffApprovalService
from picotoopet_core.handoffs.service import HandoffService
from picotoopet_core.providers.models import ProviderReadinessStatus, ProviderUsageStatus
from picotoopet_core.providers.service import ProviderSessionService
from picotoopet_core.queue.repository import QueueRepository
from picotoopet_core.services import build_services


def _signals() -> FrugalAssessmentSignals:
    return FrugalAssessmentSignals(
        contract_valid=True,
        validation_passed=False,
        coverage=0.70,
        contradiction_rate=0.10,
        model_confidence=0.65,
        risk_score=0.30,
        retry_count=0,
    )


def _service(tmp_path: Path):
    from picotoopet_core.providers.frugal_service import CodingEscalationService

    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    approvals = HandoffApprovalService(database, QueueRepository(database))
    handoffs = HandoffService(database, approvals)
    sessions = ProviderSessionService(
        database,
        handoffs,
        readiness_by_provider=lambda _provider: ProviderReadinessStatus.READY,
    )
    service = CodingEscalationService(
        database=database,
        handoffs=handoffs,
        provider_sessions=sessions,
        decisions=FrugalDecisionRepository(database),
    )
    return database, handoffs, sessions, service


def _approve(database: Database, handoff_id: str) -> None:
    row = database.fetchone(
        "SELECT preview_json FROM handoffs WHERE handoff_id = ?",
        (handoff_id,),
    )
    assert row is not None
    preview = json.loads(row["preview_json"])
    preview["status"] = "approved"
    database.execute(
        "UPDATE handoffs SET status = ?, preview_json = ? WHERE handoff_id = ?",
        (
            "approved",
            json.dumps(preview, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            handoff_id,
        ),
    )


def test_approved_handoff_without_usage_confirmation_spends_nothing(tmp_path: Path) -> None:
    database, _, _, service = _service(tmp_path)
    plan = service.evaluate(
        goal_id="goal-await-usage",
        task_class="repository_maintenance",
        title="Bounded repository repair",
        objective="Repair only the bounded repository issue.",
        signals=_signals(),
    )
    assert plan.handoff_id is not None
    _approve(database, plan.handoff_id)

    reconciled = service.reconcile("goal-await-usage")

    assert reconciled.stage == "awaiting_usage_confirmation"
    assert reconciled.session_id is None
    assert database.scalar("SELECT COUNT(*) FROM provider_sessions") == 0
    database.close()


def test_confirmed_usage_auto_creates_exactly_one_chosen_provider_session(tmp_path: Path) -> None:
    database, _, sessions, service = _service(tmp_path)
    plan = service.evaluate(
        goal_id="goal-auto-session",
        task_class="repository_maintenance",
        title="Bounded repository repair",
        objective="Repair only the bounded repository issue.",
        signals=_signals(),
    )
    assert plan.handoff_id is not None
    assert plan.decision.chosen_provider == "codex"
    _approve(database, plan.handoff_id)
    sessions.confirm_usage(
        plan.handoff_id,
        ProviderUsageStatus.CONFIRMED_AVAILABLE,
        idempotency_key="frugal-test-usage",
    )

    first = service.reconcile("goal-auto-session")
    replay = service.reconcile("goal-auto-session")

    assert first.stage == "provider_session_waiting"
    assert first.session_id is not None
    assert replay.session_id == first.session_id
    assert database.scalar("SELECT COUNT(*) FROM provider_sessions") == 1
    assert database.scalar(
        "SELECT provider FROM provider_sessions WHERE session_id = ?",
        (first.session_id,),
    ) == "codex"
    database.close()


def test_services_container_owns_one_frugal_coding_escalation_service(tmp_path: Path) -> None:
    settings = AppSettings(
        paths=RuntimePaths.from_root(tmp_path / "runtime"),
        api_token="0123456789abcdef0123456789abcdef",
    )
    services = build_services(settings)
    try:
        assert services.coding_escalation.database is services.database
        assert services.coding_escalation.handoffs is services.handoffs
        assert services.coding_escalation.provider_sessions is services.provider_sessions
    finally:
        services.close()
