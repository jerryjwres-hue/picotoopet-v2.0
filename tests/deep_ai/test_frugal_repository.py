from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path

import pytest

from picotoopet_core.db.database import Database
from picotoopet_core.deep_ai.frugal import (
    FrugalAssessmentSignals,
    FrugalEscalationArbiter,
    FrugalEscalationInput,
    ProviderCandidate,
    ProviderHistorySnapshot,
)


def _database(tmp_path: Path) -> Database:
    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    return database


def _repository_module():  # type: ignore[no-untyped-def]
    module_name = "picotoopet_core.deep_ai.frugal_repository"
    if importlib.util.find_spec(module_name) is None:
        pytest.fail("frugal decision repository is not implemented")
    return importlib.import_module(module_name)


def _decision(goal_id: str = "goal-frugal-persist"):
    history = ProviderHistorySnapshot(success_count=0, sample_size=0)
    candidates = [
        ProviderCandidate(
            provider="codex",
            readiness="ready",
            expected_quality_uplift=0.45,
            history=history,
            cost_penalty=0.10,
            latency_penalty=0.10,
            permission_risk=0.10,
        ),
        ProviderCandidate(
            provider="claude_code",
            readiness="ready",
            expected_quality_uplift=0.45,
            history=history,
            cost_penalty=0.10,
            latency_penalty=0.10,
            permission_risk=0.10,
        ),
    ]
    return FrugalEscalationArbiter().decide(
        FrugalEscalationInput(
            goal_id=goal_id,
            task_class="repository_maintenance",
            signals=FrugalAssessmentSignals(
                contract_valid=True,
                validation_passed=False,
                coverage=0.70,
                contradiction_rate=0.10,
                model_confidence=0.65,
                risk_score=0.30,
                retry_count=0,
            ),
            candidates=candidates,
        )
    )


def test_schema_21_creates_core_owned_frugal_decision_table(tmp_path: Path) -> None:
    database = _database(tmp_path)
    try:
        # Schema retention gate      Schema 21 fact remains present after progress-ledger schema 22.
        assert database.scalar("SELECT MAX(version) FROM schema_migrations") == 22
        columns = {
            row["name"]
            for row in database.fetchall("PRAGMA table_info(deep_ai_frugal_decisions)")
        }
        assert {
            "decision_id",
            "goal_id",
            "decision_digest",
            "policy_version",
            "chosen_provider",
            "decision_json",
            "created_at",
        } <= columns
    finally:
        database.close()


def test_decision_persistence_is_digest_idempotent_and_read_only(tmp_path: Path) -> None:
    database = _database(tmp_path)
    try:
        repository = _repository_module().FrugalDecisionRepository(database)
        decision = _decision()

        first = repository.put(decision)
        repeated = repository.put(decision)
        loaded = repository.get(first.decision_id)
        latest = repository.latest_for_goal(decision.goal_id)

        assert repeated.decision_id == first.decision_id
        assert loaded.decision_digest == decision.decision_digest
        assert loaded.chosen_provider == "codex"
        assert latest.decision_id == first.decision_id
        assert latest.decision == decision

        with pytest.raises(ValueError, match="FRUGAL_DECISION_DIGEST_MISMATCH"):
            repository.put(decision.model_copy(update={"decision_digest": "0" * 64}))
    finally:
        database.close()


def test_same_goal_can_record_a_new_immutable_decision_after_new_facts(tmp_path: Path) -> None:
    database = _database(tmp_path)
    try:
        repository = _repository_module().FrugalDecisionRepository(database)
        first = repository.put(_decision())
        local = FrugalEscalationArbiter().decide(
            FrugalEscalationInput(
                goal_id="goal-frugal-persist",
                task_class="repository_maintenance",
                signals=FrugalAssessmentSignals(
                    contract_valid=True,
                    validation_passed=True,
                    coverage=1.0,
                    contradiction_rate=0.0,
                    model_confidence=0.95,
                    risk_score=0.0,
                    retry_count=0,
                ),
                candidates=[],
            )
        )
        second = repository.put(local)

        assert second.decision_id != first.decision_id
        assert second.chosen_provider == "none"
        assert repository.latest_for_goal(local.goal_id).decision_id == second.decision_id
        assert len(repository.list_for_goal(local.goal_id)) == 2
    finally:
        database.close()
