from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest

from picotoopet_core.db.database import Database
from picotoopet_core.deep_ai.learning import DeepAiLearningLedger
from picotoopet_core.deep_ai.models import DeepAiHumanAction
from picotoopet_core.deep_ai.repository import DeepAiRepository


def _evaluation_module():  # type: ignore[no-untyped-def]
    module_name = "picotoopet_core.deep_ai.evaluation"
    if importlib.util.find_spec(module_name) is None:
        pytest.fail(f"{module_name} is not implemented")
    return importlib.import_module(module_name)


def _database(tmp_path: Path) -> Database:
    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    return database


def _job(repository: DeepAiRepository, *, source_id: str):  # type: ignore[no-untyped-def]
    return repository.prepare_job(
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


def _record_sample(
    repository: DeepAiRepository,
    *,
    index: int,
    action: DeepAiHumanAction,
    paid_outcome: str,
    cost_usd: str,
    reason_tags: list[str] | None = None,
    local_outcome: str = "NEEDS_DEEP_AI",
    local_attempts: int = 2,
) -> None:
    job = _job(repository, source_id=f"evaluation-source-{index:03d}")
    ledger = DeepAiLearningLedger(repository)
    ledger.record_validation(
        idempotency_key=f"evaluation:validation:{index}:v1",
        project_key="pet-dryer-us",
        job=job,
        local_profile="reviews.voice_of_customer.v1",
        local_model_id="gpt-oss:20b",
        local_template_version="reviews.v1",
        local_attempt_count=local_attempts,
        local_quality_outcome=local_outcome,
        quality_reasons=["semantic uncertainty"],
        paid_output_digest=uuid4().hex * 2,
        input_tokens=1000,
        output_tokens=500,
        cost_usd=cost_usd,
        paid_validation_outcome=paid_outcome,
        downstream_ref=f"result-package-{index:03d}",
    )
    ledger.record_feedback(
        idempotency_key=f"evaluation:feedback:{index}:v1",
        project_key="pet-dryer-us",
        job=job,
        action=action,
        reason_tags=reason_tags or [],
        final_content_digest=uuid4().hex * 2,
        downstream_ref=f"result-package-{index:03d}",
    )


def _service(database: Database):  # type: ignore[no-untyped-def]
    module = _evaluation_module()
    deep_ai_repository = DeepAiRepository(database)
    evaluation_repository = module.QualityEvaluationRepository(database)
    return module.QualityEvaluationService(
        repository=evaluation_repository,
        deep_ai_repository=deep_ai_repository,
    )


def test_snapshot_is_project_scoped_immutable_idempotent_and_normalized(tmp_path: Path) -> None:
    database = _database(tmp_path)
    try:
        repository = DeepAiRepository(database)
        _record_sample(
            repository,
            index=1,
            action=DeepAiHumanAction.ACCEPTED,
            paid_outcome="PASS",
            cost_usd="0.10",
        )
        service = _service(database)
        module = _evaluation_module()
        scope = module.QualityEvaluationScope(
            project_key="pet-dryer-us",
            evaluation_profile_id="quality.offline.v1",
        )

        first = service.create_snapshot(scope)
        second = service.create_snapshot(scope)

        # Idempotency gate          Same canonical scope + source facts returns the same snapshot.
        assert first.snapshot_id == second.snapshot_id
        assert first.snapshot_digest == second.snapshot_digest
        assert first.project_key == "pet-dryer-us"
        assert first.member_count == 2
        # Normalization gate        Snapshot persistence stores references/digests, not raw execution content.
        columns = {
            row["name"]
            for row in database.fetchall("PRAGMA table_info(quality_evaluation_snapshot_members)")
        }
        forbidden_fragments = {
            "api_key",
            "prompt",
            "endpoint",
            "path",
            "payload",
            "workflow",
            "sql",
        }
        assert not any(
            fragment in column.lower()
            for column in columns
            for fragment in forbidden_fragments
        )
    finally:
        database.close()


def test_offline_evaluation_uses_explicit_denominators_and_missing_semantics(tmp_path: Path) -> None:
    database = _database(tmp_path)
    try:
        repository = DeepAiRepository(database)
        for index, action in enumerate(
            [
                DeepAiHumanAction.ACCEPTED,
                DeepAiHumanAction.REJECTED,
                DeepAiHumanAction.MODIFIED,
                DeepAiHumanAction.ACCEPTED,
                DeepAiHumanAction.ACCEPTED,
            ],
            start=1,
        ):
            _record_sample(
                repository,
                index=index,
                action=action,
                paid_outcome="PASS",
                cost_usd="0.10",
            )
        service = _service(database)
        module = _evaluation_module()
        snapshot = service.create_snapshot(
            module.QualityEvaluationScope(project_key="pet-dryer-us")
        )
        run = service.evaluate(snapshot.snapshot_id)
        metrics = {metric.metric_name: metric for metric in service.list_metrics(run.evaluation_run_id)}

        # Sample semantics gate     Validation + feedback facts merge into five evaluated work samples.
        assert metrics["sample_count"].value == 5
        assert metrics["human_decision_count"].value == 5
        assert metrics["human_rejected_or_modified_rate"].numerator == 2
        assert metrics["human_rejected_or_modified_rate"].denominator == 5
        assert metrics["human_rejected_or_modified_rate"].value == pytest.approx(0.4)
        # Missing-data gate         No absent metric is silently converted into a fake zero denominator.
        for metric in metrics.values():
            if metric.denominator == 0:
                assert metric.value is None
                assert metric.availability == "not_available"
    finally:
        database.close()


def test_candidate_rules_require_minimum_sample_and_use_frozen_thresholds(tmp_path: Path) -> None:
    database = _database(tmp_path)
    try:
        repository = DeepAiRepository(database)
        actions = [
            DeepAiHumanAction.REJECTED,
            DeepAiHumanAction.MODIFIED,
            DeepAiHumanAction.ACCEPTED,
            DeepAiHumanAction.ACCEPTED,
            DeepAiHumanAction.ACCEPTED,
        ]
        for index, action in enumerate(actions, start=1):
            _record_sample(
                repository,
                index=index,
                action=action,
                paid_outcome="PASS",
                cost_usd="0.35",
                reason_tags=["missing_evidence"] if index <= 3 else [],
            )
        service = _service(database)
        module = _evaluation_module()
        snapshot = service.create_snapshot(
            module.QualityEvaluationScope(project_key="pet-dryer-us")
        )
        run = service.evaluate(snapshot.snapshot_id)
        candidates = service.list_candidates(evaluation_run_id=run.evaluation_run_id)
        classes = {candidate.candidate_class for candidate in candidates}

        # Frozen rule gates         The constructed cohort meets A/B/C/E but not paid-failure rule D.
        assert "PROMPT_REVIEW" in classes
        assert "LOCAL_REASONING_REVIEW" in classes
        assert "EVIDENCE_SELECTION_REVIEW" in classes
        assert "COST_POLICY_REVIEW" in classes
        assert "PAID_ESCALATION_REVIEW" not in classes

        replay = service.evaluate(snapshot.snapshot_id)
        replay_candidates = service.list_candidates(evaluation_run_id=replay.evaluation_run_id)
        # Idempotency gate          Reconcile/evaluate replay does not multiply the same candidates.
        assert replay.evaluation_run_id == run.evaluation_run_id
        assert [item.candidate_id for item in replay_candidates] == [
            item.candidate_id for item in candidates
        ]
    finally:
        database.close()


def test_small_cohort_cannot_trigger_improvement_candidate(tmp_path: Path) -> None:
    database = _database(tmp_path)
    try:
        repository = DeepAiRepository(database)
        for index in range(1, 5):
            _record_sample(
                repository,
                index=index,
                action=DeepAiHumanAction.REJECTED,
                paid_outcome="NEEDS_HUMAN",
                cost_usd="0.50",
                reason_tags=["wrong_evidence"],
            )
        service = _service(database)
        module = _evaluation_module()
        snapshot = service.create_snapshot(
            module.QualityEvaluationScope(project_key="pet-dryer-us")
        )
        run = service.evaluate(snapshot.snapshot_id)

        # Small-sample gate         Four decisions are below the frozen minimum of five.
        assert service.list_candidates(evaluation_run_id=run.evaluation_run_id) == []
        assert any(
            metric.availability == "insufficient_sample"
            for metric in service.list_metrics(run.evaluation_run_id)
            if metric.cohort_key is not None
        )
    finally:
        database.close()


def test_candidate_review_is_fact_only_and_never_mutates_paid_execution(tmp_path: Path) -> None:
    database = _database(tmp_path)
    try:
        repository = DeepAiRepository(database)
        jobs = []
        for index in range(1, 6):
            _record_sample(
                repository,
                index=index,
                action=DeepAiHumanAction.REJECTED if index <= 2 else DeepAiHumanAction.ACCEPTED,
                paid_outcome="PASS",
                cost_usd="0.35",
            )
        jobs = repository.list_jobs(limit=100)
        before = {
            job.escalation_job_id: (
                job.status,
                job.provider_profile_id,
                job.model_id,
                job.max_calls,
                job.max_cost_usd,
                len(repository.list_attempts(job.escalation_job_id)),
            )
            for job in jobs
        }
        service = _service(database)
        module = _evaluation_module()
        snapshot = service.create_snapshot(
            module.QualityEvaluationScope(project_key="pet-dryer-us")
        )
        run = service.evaluate(snapshot.snapshot_id)
        candidate = service.list_candidates(evaluation_run_id=run.evaluation_run_id)[0]

        first = service.review_candidate(
            candidate.candidate_id,
            action="AcceptedForShadow",
            idempotency_key=f"review:{candidate.candidate_id}:shadow:v1",
        )
        second = service.review_candidate(
            candidate.candidate_id,
            action="AcceptedForShadow",
            idempotency_key=f"review:{candidate.candidate_id}:shadow:v1",
        )

        # Review idempotency        The same review fact is durable exactly once.
        assert first.review_id == second.review_id
        assert service.get_candidate(candidate.candidate_id).status == "AcceptedForShadow"
        # Zero-mutation gate        Review cannot reopen jobs, alter execution envelopes, or reserve calls.
        after = {
            job.escalation_job_id: (
                repository.get_job(job.escalation_job_id).status,
                repository.get_job(job.escalation_job_id).provider_profile_id,
                repository.get_job(job.escalation_job_id).model_id,
                repository.get_job(job.escalation_job_id).max_calls,
                repository.get_job(job.escalation_job_id).max_cost_usd,
                len(repository.list_attempts(job.escalation_job_id)),
            )
            for job in jobs
        }
        assert after == before
    finally:
        database.close()
