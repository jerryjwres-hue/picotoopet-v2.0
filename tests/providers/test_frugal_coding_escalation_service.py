from __future__ import annotations

from pathlib import Path

from picotoopet_core.db.database import Database
from picotoopet_core.deep_ai.frugal import FrugalAssessmentSignals
from picotoopet_core.deep_ai.frugal_repository import FrugalDecisionRepository
from picotoopet_core.handoffs.approvals import HandoffApprovalService
from picotoopet_core.handoffs.service import HandoffService
from picotoopet_core.providers.models import ProviderReadinessStatus
from picotoopet_core.providers.service import ProviderSessionService
from picotoopet_core.queue.repository import QueueRepository


def _service(tmp_path: Path, readiness: dict[str, ProviderReadinessStatus]):
    from picotoopet_core.providers.frugal_service import CodingEscalationService

    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    queue = QueueRepository(database)
    approvals = HandoffApprovalService(database, queue)
    handoffs = HandoffService(database, approvals)
    provider_sessions = ProviderSessionService(
        database,
        handoffs,
        readiness_by_provider=lambda provider: readiness[provider],
    )
    service = CodingEscalationService(
        database=database,
        handoffs=handoffs,
        provider_sessions=provider_sessions,
        decisions=FrugalDecisionRepository(database),
    )
    return database, service


def _signals(*, high: bool = False) -> FrugalAssessmentSignals:
    if high:
        return FrugalAssessmentSignals(
            contract_valid=True,
            validation_passed=True,
            coverage=1.0,
            contradiction_rate=0.0,
            model_confidence=0.95,
            risk_score=0.0,
            retry_count=0,
        )
    return FrugalAssessmentSignals(
        contract_valid=True,
        validation_passed=False,
        coverage=0.70,
        contradiction_rate=0.10,
        model_confidence=0.65,
        risk_score=0.30,
        retry_count=0,
    )


def test_high_confidence_local_result_persists_decision_and_spends_nothing(tmp_path: Path) -> None:
    database, service = _service(
        tmp_path,
        {
            "codex": ProviderReadinessStatus.READY,
            "claude_code": ProviderReadinessStatus.READY,
        },
    )

    plan = service.evaluate(
        goal_id="goal-local-only",
        task_class="repository_maintenance",
        title="Local repair is already validated",
        objective="Keep the validated local repair and do not spend provider quota.",
        signals=_signals(high=True),
    )

    assert plan.decision.action == "local_only"
    assert plan.decision.chosen_provider == "none"
    assert plan.stage == "local_only"
    assert plan.handoff_id is None
    assert database.scalar("SELECT COUNT(*) FROM deep_ai_frugal_decisions") == 1
    assert database.scalar("SELECT COUNT(*) FROM handoffs") == 0
    assert database.scalar("SELECT COUNT(*) FROM provider_sessions") == 0
    database.close()


def test_non_coding_goal_can_never_prepare_a_coding_provider_handoff(tmp_path: Path) -> None:
    database, service = _service(
        tmp_path,
        {
            "codex": ProviderReadinessStatus.READY,
            "claude_code": ProviderReadinessStatus.READY,
        },
    )

    plan = service.evaluate(
        goal_id="goal-product-research",
        task_class="product_research",
        title="Research task",
        objective="Research a product and produce evidence.",
        signals=_signals(),
    )

    assert plan.decision.eligibility is False
    assert plan.decision.chosen_provider == "none"
    assert database.scalar("SELECT COUNT(*) FROM handoffs") == 0
    database.close()


def test_cold_start_tie_prepares_only_codex_and_submits_one_approval(tmp_path: Path) -> None:
    database, service = _service(
        tmp_path,
        {
            "codex": ProviderReadinessStatus.READY,
            "claude_code": ProviderReadinessStatus.READY,
        },
    )

    plan = service.evaluate(
        goal_id="goal-cold-tie",
        task_class="repository_maintenance",
        title="Bounded repository repair",
        objective="Repair the bounded repository issue without publishing changes.",
        signals=_signals(),
    )
    replay = service.evaluate(
        goal_id="goal-cold-tie",
        task_class="repository_maintenance",
        title="Bounded repository repair",
        objective="Repair the bounded repository issue without publishing changes.",
        signals=_signals(),
    )

    assert plan.decision.chosen_provider == "codex"
    assert plan.stage == "awaiting_handoff_approval"
    assert plan.handoff_id is not None
    assert replay.handoff_id == plan.handoff_id
    assert database.scalar("SELECT COUNT(*) FROM deep_ai_frugal_decisions") == 1
    assert database.scalar("SELECT COUNT(*) FROM handoffs") == 1
    assert database.scalar("SELECT COUNT(*) FROM approvals") == 1
    assert database.scalar("SELECT COUNT(*) FROM provider_sessions") == 0
    row = database.fetchone("SELECT preview_json FROM handoffs LIMIT 1")
    assert row is not None
    assert '"provider":"codex"' in row["preview_json"]
    database.close()


def test_unready_codex_routes_to_ready_claude_without_calling_both(tmp_path: Path) -> None:
    database, service = _service(
        tmp_path,
        {
            "codex": ProviderReadinessStatus.NOT_AUTHENTICATED,
            "claude_code": ProviderReadinessStatus.READY,
        },
    )

    plan = service.evaluate(
        goal_id="goal-claude-only-ready",
        task_class="bounded_code_repair",
        title="Bounded code repair",
        objective="Produce one bounded repair candidate for local validation.",
        signals=_signals(),
    )

    assert plan.decision.chosen_provider == "claude_code"
    assert plan.stage == "awaiting_handoff_approval"
    assert database.scalar("SELECT COUNT(*) FROM handoffs") == 1
    row = database.fetchone("SELECT preview_json FROM handoffs LIMIT 1")
    assert row is not None
    assert '"provider":"claude_code"' in row["preview_json"]
    assert database.scalar("SELECT COUNT(*) FROM provider_sessions") == 0
    database.close()


def test_provider_history_counts_only_terminal_local_validation_outcomes(tmp_path: Path) -> None:
    database, service = _service(
        tmp_path,
        {
            "codex": ProviderReadinessStatus.READY,
            "claude_code": ProviderReadinessStatus.READY,
        },
    )

    database.execute(
        "INSERT INTO provider_sessions (session_id, handoff_id, provider, status, request_digest, "
        "package_digest, budget_json, idempotency_key, created_at, updated_at, preview_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "11111111-1111-1111-1111-111111111111",
            "history-handoff-1",
            "codex",
            "ready_for_review",
            "a" * 64,
            "b" * 64,
            "{}",
            "history-session-1",
            "2026-08-19T00:00:00+00:00",
            "2026-08-19T00:00:00+00:00",
            "{}",
        ),
    )
    for index, status in enumerate(("adoption_ready", "validation_failed", "queued"), start=1):
        database.execute(
            "INSERT INTO provider_adoption_candidates (candidate_id, session_id, return_id, status, "
            "base_commit, change_set_digest, changed_file_count, validation_json, failure_code, "
            "idempotency_key, created_at, updated_at, finished_at, preview_json) "
            "VALUES (?, ?, ?, ?, ?, ?, 1, '[]', NULL, ?, ?, ?, NULL, '{}')",
            (
                f"00000000-0000-0000-0000-00000000000{index}",
                "11111111-1111-1111-1111-111111111111",
                f"return-history-{index}",
                status,
                "c" * 40,
                f"{index}" * 64,
                f"history-candidate-{index}",
                "2026-08-19T00:00:00+00:00",
                "2026-08-19T00:00:00+00:00",
            ),
        )

    history = service.provider_history("codex")

    assert history.success_count == 1
    assert history.sample_size == 2
    database.close()
