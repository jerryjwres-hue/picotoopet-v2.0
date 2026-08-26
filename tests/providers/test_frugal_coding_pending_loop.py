from __future__ import annotations

import json
from pathlib import Path

from picotoopet_core.db.database import Database
from picotoopet_core.deep_ai.frugal import FrugalAssessmentSignals
from picotoopet_core.deep_ai.frugal_repository import FrugalDecisionRepository
from picotoopet_core.handoffs.approvals import HandoffApprovalService
from picotoopet_core.handoffs.service import HandoffService
from picotoopet_core.providers.models import ProviderReadinessStatus, ProviderUsageStatus
from picotoopet_core.providers.service import ProviderSessionService
from picotoopet_core.queue.repository import QueueRepository


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
    return database, sessions, service


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


def _prepare(service, goal_id: str):  # type: ignore[no-untyped-def]
    return service.evaluate(
        goal_id=goal_id,
        task_class="repository_maintenance",
        title=f"Bounded repair {goal_id}",
        objective="Repair only the approved bounded repository issue.",
        signals=_signals(),
    )


def test_reconcile_pending_advances_only_previously_authorized_decisions(tmp_path: Path) -> None:
    database, sessions, service = _service(tmp_path)
    confirmed = _prepare(service, "goal-confirmed")
    waiting = _prepare(service, "goal-waiting")
    assert confirmed.handoff_id is not None
    assert waiting.handoff_id is not None
    _approve(database, confirmed.handoff_id)
    _approve(database, waiting.handoff_id)
    sessions.confirm_usage(
        confirmed.handoff_id,
        ProviderUsageStatus.CONFIRMED_AVAILABLE,
        idempotency_key="pending-loop-confirmed",
    )

    plans = service.reconcile_pending(limit=20)
    replay = service.reconcile_pending(limit=20)

    by_goal = {plan.decision.goal_id: plan for plan in plans}
    assert by_goal["goal-confirmed"].stage == "provider_session_waiting"
    assert by_goal["goal-confirmed"].session_id is not None
    assert by_goal["goal-waiting"].stage == "awaiting_usage_confirmation"
    assert by_goal["goal-waiting"].session_id is None
    assert database.scalar("SELECT COUNT(*) FROM provider_sessions") == 1
    replay_by_goal = {plan.decision.goal_id: plan for plan in replay}
    assert replay_by_goal["goal-confirmed"].session_id == by_goal["goal-confirmed"].session_id
    database.close()


def test_reconcile_pending_is_bounded_to_latest_distinct_goals(tmp_path: Path) -> None:
    database, _, service = _service(tmp_path)
    for index in range(5):
        _prepare(service, f"goal-{index}")

    plans = service.reconcile_pending(limit=3)

    assert len(plans) == 3
    assert len({plan.decision.goal_id for plan in plans}) == 3
    database.close()


def test_worker_reconciles_authorization_facts_before_provider_queueing() -> None:
    root = Path(__file__).resolve().parents[2]
    cli = (root / "src/picotoopet_core/cli.py").read_text(encoding="utf-8")

    reconcile = "services.coding_escalation.reconcile_pending(limit=20)"
    enqueue = "provider_coordinator.enqueue_pending()"
    assert reconcile in cli
    assert enqueue in cli
    assert cli.index(reconcile) < cli.index(enqueue)
