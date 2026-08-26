from __future__ import annotations

import json
from pathlib import Path

from picotoopet_core.db.database import Database
from picotoopet_core.deep_ai.frugal import FrugalAssessmentSignals
from picotoopet_core.deep_ai.frugal_repository import FrugalDecisionRepository
from picotoopet_core.handoffs.approvals import HandoffApprovalService
from picotoopet_core.handoffs.service import HandoffService
from picotoopet_core.providers.models import ProviderReadinessStatus
from picotoopet_core.providers.service import ProviderSessionService
from picotoopet_core.queue.repository import QueueRepository


def _service(tmp_path: Path):
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
        readiness_by_provider=lambda _provider: ProviderReadinessStatus.READY,
    )
    service = CodingEscalationService(
        database=database,
        handoffs=handoffs,
        provider_sessions=provider_sessions,
        decisions=FrugalDecisionRepository(database),
    )
    return database, service


def _insert_terminal_sample(
    database: Database,
    *,
    index: int,
    task_class: str,
    status: str,
) -> None:
    now = "2026-08-19T00:00:00+00:00"
    expires = "2026-08-20T00:00:00+00:00"
    handoff_id = f"cohort-handoff-{index}"
    session_id = f"11111111-1111-1111-1111-{index:012d}"
    return_id = f"cohort-return-{index}"
    decision_digest = f"{index:064x}"
    request_digest = f"{index + 2:064x}"
    package_digest = f"{index + 4:064x}"
    manifest_digest = f"{index + 6:064x}"

    database.execute(
        "INSERT INTO deep_ai_frugal_decisions "
        "(decision_id, goal_id, decision_digest, policy_version, chosen_provider, "
        "decision_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            f"cohort-decision-{index}",
            f"cohort-goal-{index}",
            decision_digest,
            "frugal-coding.v1",
            "codex",
            json.dumps({"task_class": task_class}, separators=(",", ":")),
            now,
        ),
    )
    database.execute(
        "INSERT INTO handoffs (handoff_id, template_id, title, objective_summary, status, "
        "request_digest, package_digest, manifest_json, preview_json, approval_id, "
        "prepare_idempotency_key, approval_idempotency_key, created_at, updated_at, expires_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, '{}', '{}', NULL, ?, NULL, ?, ?, ?)",
        (
            handoff_id,
            "picotoopet-repo-maintenance-codex-v1",
            f"cohort history {index}",
            "bounded provider history cohort fixture",
            "approved",
            request_digest,
            package_digest,
            f"frugal-handoff:{decision_digest}",
            now,
            now,
            expires,
        ),
    )
    database.execute(
        "INSERT INTO returns (return_id, handoff_id, status, provider, request_digest, "
        "package_digest, manifest_digest, changed_file_count, event_count, "
        "validation_checks_json, preview_json, quarantine_code, idempotency_key, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, 1, 0, '[]', '{}', NULL, ?, ?, ?)",
        (
            return_id,
            handoff_id,
            "contract_validated",
            "codex",
            request_digest,
            package_digest,
            manifest_digest,
            f"cohort-return-key-{index}",
            now,
            now,
        ),
    )
    database.execute(
        "INSERT INTO provider_sessions (session_id, handoff_id, provider, status, request_digest, "
        "package_digest, budget_json, return_id, idempotency_key, created_at, updated_at, "
        "preview_json) VALUES (?, ?, ?, ?, ?, ?, '{}', ?, ?, ?, ?, '{}')",
        (
            session_id,
            handoff_id,
            "codex",
            "ready_for_review",
            request_digest,
            package_digest,
            return_id,
            f"cohort-session-key-{index}",
            now,
            now,
        ),
    )
    database.execute(
        "INSERT INTO provider_adoption_candidates (candidate_id, session_id, return_id, status, "
        "base_commit, change_set_digest, changed_file_count, validation_json, failure_code, "
        "idempotency_key, created_at, updated_at, finished_at, preview_json) "
        "VALUES (?, ?, ?, ?, ?, ?, 1, '[]', NULL, ?, ?, ?, ?, '{}')",
        (
            f"00000000-0000-0000-0000-{index:012d}",
            session_id,
            return_id,
            status,
            "c" * 40,
            f"{index + 8:064x}",
            f"cohort-candidate-key-{index}",
            now,
            now,
            now,
        ),
    )


def test_decision_history_uses_only_same_task_cohort(tmp_path: Path) -> None:
    database, service = _service(tmp_path)
    _insert_terminal_sample(
        database,
        index=1,
        task_class="repository_maintenance",
        status="adoption_ready",
    )
    _insert_terminal_sample(
        database,
        index=2,
        task_class="bounded_code_repair",
        status="validation_failed",
    )

    plan = service.evaluate(
        goal_id="cohort-new-repository-maintenance",
        task_class="repository_maintenance",
        title="Repository maintenance cohort decision",
        objective="Use only comparable repository-maintenance outcomes for provider history.",
        signals=FrugalAssessmentSignals(
            contract_valid=True,
            validation_passed=False,
            coverage=0.70,
            contradiction_rate=0.10,
            model_confidence=0.65,
            risk_score=0.30,
            retry_count=0,
        ),
    )

    codex_history = next(
        item for item in plan.decision.provider_history if item.provider == "codex"
    )
    assert codex_history.success_count == 1
    assert codex_history.sample_size == 1
    database.close()
