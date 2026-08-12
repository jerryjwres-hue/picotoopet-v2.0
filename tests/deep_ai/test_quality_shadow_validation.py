from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest

from picotoopet_core.db.database import Database
from picotoopet_core.deep_ai.evaluation import (
    QualityEvaluationRepository,
    QualityEvaluationScope,
    QualityEvaluationService,
)
from picotoopet_core.deep_ai.learning import DeepAiLearningLedger
from picotoopet_core.deep_ai.models import DeepAiHumanAction
from picotoopet_core.deep_ai.repository import DeepAiRepository


def _shadow_module():  # type: ignore[no-untyped-def]
    module_name = "picotoopet_core.deep_ai.shadow"
    if importlib.util.find_spec(module_name) is None:
        pytest.fail(f"{module_name} is not implemented")
    return importlib.import_module(module_name)


def _database(tmp_path: Path) -> Database:
    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    return database


def _record_rejected_sample(repository: DeepAiRepository, *, index: int, project_key: str) -> None:
    source_id = f"shadow-source-{index:03d}"
    job = repository.prepare_job(
        escalation_job_id=str(uuid4()),
        source_kind="business.local_intelligence",
        source_id=source_id,
        source_digest=uuid4().hex * 2,
        policy_version="deep-ai.escalation.v1",
        sanitized_package_relpath=f"runtime/deep-ai/requests/{source_id}.json",
        sanitized_package_digest=uuid4().hex * 2,
        sanitizer_version="deep-ai.sanitizer.v1",
        provider_profile_id="paid.reasoning.v1",
        provider_profile_digest=uuid4().hex * 2,
        model_id="gpt-5.6-terra",
        max_input_tokens=12000,
        max_output_tokens=4000,
        max_calls=2,
        max_cost_usd="0.50",
    )
    ledger = DeepAiLearningLedger(repository)
    ledger.record_validation(
        idempotency_key=f"shadow:validation:{project_key}:{index}:v1",
        project_key=project_key,
        job=job,
        local_profile="reviews.voice_of_customer.v1",
        local_model_id="gpt-oss:20b",
        local_template_version="reviews.v1",
        local_attempt_count=1,
        local_quality_outcome="PASS",
        quality_reasons=[],
        paid_output_digest=uuid4().hex * 2,
        input_tokens=100,
        output_tokens=50,
        cost_usd="0.10",
        paid_validation_outcome="PASS",
        downstream_ref=f"result-package-{index:03d}",
    )
    ledger.record_feedback(
        idempotency_key=f"shadow:feedback:{project_key}:{index}:v1",
        project_key=project_key,
        job=job,
        action=DeepAiHumanAction.REJECTED,
        reason_tags=[],
        final_content_digest=uuid4().hex * 2,
        downstream_ref=f"result-package-{index:03d}",
    )


def _accepted_prompt_candidate(database: Database, *, count: int, project_key: str):  # type: ignore[no-untyped-def]
    deep_ai_repository = DeepAiRepository(database)
    for index in range(1, count + 1):
        _record_rejected_sample(deep_ai_repository, index=index, project_key=project_key)
    evaluation_repository = QualityEvaluationRepository(database)
    evaluation = QualityEvaluationService(
        repository=evaluation_repository,
        deep_ai_repository=deep_ai_repository,
    )
    snapshot = evaluation.create_snapshot(QualityEvaluationScope(project_key=project_key))
    run = evaluation.evaluate(snapshot.snapshot_id)
    candidate = next(
        item
        for item in evaluation.list_candidates(evaluation_run_id=run.evaluation_run_id)
        if item.candidate_class == "PROMPT_REVIEW" and item.cohort_dimension is None
    )
    evaluation.review_candidate(
        candidate.candidate_id,
        action="AcceptedForShadow",
        idempotency_key=f"candidate:{candidate.candidate_id}:accepted-for-shadow:v1",
    )
    return evaluation_repository, evaluation, evaluation.get_candidate(candidate.candidate_id)


def _service(database: Database, evaluation_repository: QualityEvaluationRepository):  # type: ignore[no-untyped-def]
    module = _shadow_module()
    repository = module.QualityShadowRepository(database)
    return module.QualityShadowService(
        repository=repository,
        evaluation_repository=evaluation_repository,
    )


def test_shadow_create_is_accepted_candidate_only_idempotent_and_zero_execution(tmp_path: Path) -> None:
    database = _database(tmp_path)
    try:
        evaluation_repository, evaluation, candidate = _accepted_prompt_candidate(
            database,
            count=60,
            project_key="shadow-supported",
        )
        service = _service(database, evaluation_repository)

        first = service.create(candidate.candidate_id)
        second = service.create(candidate.candidate_id)

        # Identity gate            One accepted candidate maps to exactly one immutable shadow run.
        assert first.shadow_run_id == second.shadow_run_id
        assert first.candidate_id == candidate.candidate_id
        assert first.shadow_profile_id == "quality.shadow.v1"
        assert first.split_version == "quality.shadow.split.v1"
        assert first.status == "Completed"
        assert first.verdict == "Supported"
        # Zero-execution gate      Shadow validation cannot spend, reopen Deep-AI, or change the candidate.
        assert database.scalar("SELECT COUNT(*) FROM deep_ai_attempts") == 0
        assert evaluation.get_candidate(candidate.candidate_id).status == "AcceptedForShadow"
        assert database.scalar("SELECT COUNT(*) FROM quality_shadow_runs") == 1
    finally:
        database.close()


def test_shadow_split_and_reconcile_are_deterministic_with_explicit_denominators(tmp_path: Path) -> None:
    database = _database(tmp_path)
    try:
        evaluation_repository, _, candidate = _accepted_prompt_candidate(
            database,
            count=60,
            project_key="shadow-reconcile",
        )
        service = _service(database, evaluation_repository)
        run = service.create(candidate.candidate_id)
        before = service.list_metrics(run.shadow_run_id)

        reconciled = service.reconcile(run.shadow_run_id)
        after = service.list_metrics(run.shadow_run_id)

        # Recovery gate            Reconcile reuses the same identity and exact deterministic arm facts.
        assert reconciled.shadow_run_id == run.shadow_run_id
        assert reconciled.report_digest == run.report_digest
        assert [item.model_dump() for item in after] == [item.model_dump() for item in before]
        rates = {
            (item.arm, item.metric_name): item
            for item in after
            if item.metric_name == "human_rejected_or_modified_rate"
        }
        assert set(rates) == {
            ("baseline", "human_rejected_or_modified_rate"),
            ("shadow", "human_rejected_or_modified_rate"),
        }
        for metric in rates.values():
            # Denominator gate       A/B evidence exposes exact numerator/denominator, not a rounded score.
            assert metric.denominator is not None and metric.denominator >= 5
            assert metric.numerator == metric.denominator
            assert metric.value == pytest.approx(1.0)
    finally:
        database.close()


def test_shadow_needs_more_data_when_two_holdout_arms_cannot_each_meet_minimum(tmp_path: Path) -> None:
    database = _database(tmp_path)
    try:
        evaluation_repository, _, candidate = _accepted_prompt_candidate(
            database,
            count=5,
            project_key="shadow-small",
        )
        service = _service(database, evaluation_repository)

        run = service.create(candidate.candidate_id)

        # Holdout gate             Five source decisions cannot make two independent arms of five decisions.
        assert run.verdict == "NeedsMoreData"
        assert database.scalar("SELECT COUNT(*) FROM deep_ai_attempts") == 0
    finally:
        database.close()


def test_shadow_rejects_non_accepted_candidate(tmp_path: Path) -> None:
    database = _database(tmp_path)
    try:
        evaluation_repository, evaluation, accepted = _accepted_prompt_candidate(
            database,
            count=10,
            project_key="shadow-eligibility",
        )
        # Eligibility gate         A new candidate in Prepared state must not inherit historical eligibility.
        database.execute(
            "UPDATE quality_improvement_candidates SET status='Prepared' WHERE candidate_id=?",
            (accepted.candidate_id,),
        )
        service = _service(database, evaluation_repository)

        with pytest.raises(ValueError, match="QUALITY_SHADOW_CANDIDATE_NOT_ACCEPTED"):
            service.create(accepted.candidate_id)
        assert evaluation.get_candidate(accepted.candidate_id).status == "Prepared"
        assert database.scalar("SELECT COUNT(*) FROM quality_shadow_runs") == 0
    finally:
        database.close()


def test_shadow_review_is_append_only_idempotent_and_fact_only(tmp_path: Path) -> None:
    database = _database(tmp_path)
    try:
        evaluation_repository, evaluation, candidate = _accepted_prompt_candidate(
            database,
            count=60,
            project_key="shadow-review",
        )
        service = _service(database, evaluation_repository)
        run = service.create(candidate.candidate_id)
        key = f"shadow-review:{run.shadow_run_id}:promotion:v1"

        first = service.review(
            run.shadow_run_id,
            action="AcceptedForPromotionReview",
            idempotency_key=key,
        )
        second = service.review(
            run.shadow_run_id,
            action="AcceptedForPromotionReview",
            idempotency_key=key,
        )

        # Review idempotency       The same bounded human decision is persisted exactly once.
        assert first.review_id == second.review_id
        assert database.scalar("SELECT COUNT(*) FROM quality_shadow_reviews") == 1
        # Fact-only gate           Promotion review never mutates execution policy or candidate eligibility.
        assert evaluation.get_candidate(candidate.candidate_id).status == "AcceptedForShadow"
        assert database.scalar("SELECT COUNT(*) FROM deep_ai_attempts") == 0
    finally:
        database.close()
