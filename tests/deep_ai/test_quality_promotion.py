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
from picotoopet_core.deep_ai.shadow import QualityShadowRepository, QualityShadowService


def _promotion_module():  # type: ignore[no-untyped-def]
    module_name = "picotoopet_core.deep_ai.promotion"
    if importlib.util.find_spec(module_name) is None:
        pytest.fail(f"{module_name} is not implemented")
    return importlib.import_module(module_name)


def _database(tmp_path: Path) -> Database:
    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    return database


def _record_rejected_sample(
    repository: DeepAiRepository,
    *,
    index: int,
    project_key: str,
    batch: str,
) -> None:
    source_id = f"promotion-source-{project_key}-{batch}-{index:03d}"
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
        idempotency_key=f"promotion:validation:{project_key}:{batch}:{index}:v1",
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
        downstream_ref=f"result-package-{project_key}-{batch}-{index:03d}",
    )
    ledger.record_feedback(
        idempotency_key=f"promotion:feedback:{project_key}:{batch}:{index}:v1",
        project_key=project_key,
        job=job,
        action=DeepAiHumanAction.REJECTED,
        reason_tags=[],
        final_content_digest=uuid4().hex * 2,
        downstream_ref=f"result-package-{project_key}-{batch}-{index:03d}",
    )


def _supported_shadow(
    database: Database,
    *,
    project_key: str,
    accepted_for_promotion: bool = True,
):  # type: ignore[no-untyped-def]
    deep_ai_repository = DeepAiRepository(database)
    batch = uuid4().hex[:12]
    for index in range(1, 61):
        _record_rejected_sample(
            deep_ai_repository,
            index=index,
            project_key=project_key,
            batch=batch,
        )
    evaluation_repository = QualityEvaluationRepository(database)
    evaluation = QualityEvaluationService(
        repository=evaluation_repository,
        deep_ai_repository=deep_ai_repository,
    )
    snapshot = evaluation.create_snapshot(QualityEvaluationScope(project_key=project_key))
    evaluation_run = evaluation.evaluate(snapshot.snapshot_id)
    candidate = next(
        item
        for item in evaluation.list_candidates(evaluation_run_id=evaluation_run.evaluation_run_id)
        if item.candidate_class == "PROMPT_REVIEW" and item.cohort_dimension is None
    )
    evaluation.review_candidate(
        candidate.candidate_id,
        action="AcceptedForShadow",
        idempotency_key=f"promotion:candidate:{candidate.candidate_id}:shadow:v1",
    )
    shadow_repository = QualityShadowRepository(database)
    shadow_service = QualityShadowService(
        repository=shadow_repository,
        evaluation_repository=evaluation_repository,
    )
    shadow_run = shadow_service.create(candidate.candidate_id)
    assert shadow_run.verdict == "Supported"
    if accepted_for_promotion:
        shadow_service.review(
            shadow_run.shadow_run_id,
            action="AcceptedForPromotionReview",
            idempotency_key=f"promotion:shadow:{shadow_run.shadow_run_id}:accepted:v1",
        )
    return evaluation_repository, shadow_repository, shadow_run


def _service(database: Database, evaluation_repository, shadow_repository):  # type: ignore[no-untyped-def]
    module = _promotion_module()
    repository = module.QualityPromotionRepository(database)
    return module.QualityPromotionService(
        repository=repository,
        shadow_repository=shadow_repository,
        evaluation_repository=evaluation_repository,
    )


def test_promotion_requires_supported_shadow_and_exact_terminal_review(tmp_path: Path) -> None:
    database = _database(tmp_path)
    try:
        evaluation_repository, shadow_repository, shadow_run = _supported_shadow(
            database,
            project_key="promotion-ineligible",
            accepted_for_promotion=False,
        )
        service = _service(database, evaluation_repository, shadow_repository)

        with pytest.raises(ValueError, match="QUALITY_PROMOTION_SHADOW_NOT_ACCEPTED"):
            service.create(shadow_run.shadow_run_id)
        assert database.scalar("SELECT COUNT(*) FROM quality_promotions") == 0
        assert database.scalar("SELECT COUNT(*) FROM deep_ai_attempts") == 0
    finally:
        database.close()


def test_promotion_create_is_idempotent_versioned_and_has_exact_activation_request(tmp_path: Path) -> None:
    database = _database(tmp_path)
    try:
        evaluation_repository, shadow_repository, shadow_run = _supported_shadow(
            database,
            project_key="promotion-create",
        )
        service = _service(database, evaluation_repository, shadow_repository)

        first = service.create(shadow_run.shadow_run_id)
        second = service.create(shadow_run.shadow_run_id)
        approval = service.get_activation_request(first.promotion_id)

        # Identity gate            One immutable Shadow run maps to exactly one Promotion proposal/version.
        assert first.promotion_id == second.promotion_id
        assert first.version_no == 1
        assert first.status == "AwaitingApproval"
        assert first.promotion_profile_id == "quality.promotion.v1"
        assert len(first.proposal_digest) == 64
        # Exact approval gate      Activation stays pending until the caller echoes the frozen request digest.
        assert approval.approval_kind == "PromotionActivation"
        assert approval.status == "Pending"
        assert approval.promotion_id == first.promotion_id
        assert len(approval.request_digest) == 64
        assert database.scalar("SELECT COUNT(*) FROM quality_promotions") == 1
        assert database.scalar("SELECT COUNT(*) FROM deep_ai_attempts") == 0
    finally:
        database.close()


def test_activation_supersedes_prior_version_and_keeps_exactly_one_active(tmp_path: Path) -> None:
    database = _database(tmp_path)
    try:
        eval_a, shadow_repo_a, shadow_a = _supported_shadow(database, project_key="promotion-slot")
        service = _service(database, eval_a, shadow_repo_a)
        first = service.create(shadow_a.shadow_run_id)
        approval_a = service.get_activation_request(first.promotion_id)
        activated_a = service.decide_activation(
            first.promotion_id,
            decision="Approved",
            request_digest=approval_a.request_digest,
            idempotency_key=f"activate:{first.promotion_id}:v1",
        )
        assert activated_a.status == "Active"

        # Version gate             A genuinely new immutable Shadow evidence set receives the next Core version.
        eval_b, shadow_repo_b, shadow_b = _supported_shadow(database, project_key="promotion-slot")
        service = _service(database, eval_b, shadow_repo_b)
        second = service.create(shadow_b.shadow_run_id)
        approval_b = service.get_activation_request(second.promotion_id)
        activated_b = service.decide_activation(
            second.promotion_id,
            decision="Approved",
            request_digest=approval_b.request_digest,
            idempotency_key=f"activate:{second.promotion_id}:v1",
        )

        assert second.version_no == first.version_no + 1
        assert activated_b.status == "Active"
        assert activated_b.supersedes_promotion_id == first.promotion_id
        assert service.get_promotion(first.promotion_id).status == "Superseded"
        assert service.get_active("promotion-slot", "PROMPT_REVIEW").promotion_id == second.promotion_id
        assert database.scalar(
            "SELECT COUNT(*) FROM quality_promotions WHERE slot_key=? AND status='Active'",
            (activated_b.slot_key,),
        ) == 1
        assert database.scalar("SELECT COUNT(*) FROM deep_ai_attempts") == 0
    finally:
        database.close()


def test_activation_fails_closed_on_stale_digest_and_conflicting_decision(tmp_path: Path) -> None:
    database = _database(tmp_path)
    try:
        evaluation_repository, shadow_repository, shadow_run = _supported_shadow(
            database,
            project_key="promotion-stale",
        )
        service = _service(database, evaluation_repository, shadow_repository)
        promotion = service.create(shadow_run.shadow_run_id)
        approval = service.get_activation_request(promotion.promotion_id)

        with pytest.raises(ValueError, match="QUALITY_PROMOTION_APPROVAL_DIGEST_CHANGED"):
            service.decide_activation(
                promotion.promotion_id,
                decision="Approved",
                request_digest="0" * 64,
                idempotency_key="promotion-stale:wrong:v1",
            )
        service.decide_activation(
            promotion.promotion_id,
            decision="Rejected",
            request_digest=approval.request_digest,
            idempotency_key="promotion-stale:reject:v1",
        )
        with pytest.raises(ValueError, match="QUALITY_PROMOTION_APPROVAL_TERMINAL"):
            service.decide_activation(
                promotion.promotion_id,
                decision="Approved",
                request_digest=approval.request_digest,
                idempotency_key="promotion-stale:approve-after-reject:v1",
            )
        assert service.get_promotion(promotion.promotion_id).status == "Rejected"
    finally:
        database.close()


def test_approved_rollback_restores_immediate_predecessor_and_is_fact_only(tmp_path: Path) -> None:
    database = _database(tmp_path)
    try:
        eval_a, shadow_repo_a, shadow_a = _supported_shadow(database, project_key="promotion-rollback")
        service = _service(database, eval_a, shadow_repo_a)
        first = service.create(shadow_a.shadow_run_id)
        first_request = service.get_activation_request(first.promotion_id)
        service.decide_activation(
            first.promotion_id,
            decision="Approved",
            request_digest=first_request.request_digest,
            idempotency_key=f"activate:{first.promotion_id}:v1",
        )

        eval_b, shadow_repo_b, shadow_b = _supported_shadow(database, project_key="promotion-rollback")
        service = _service(database, eval_b, shadow_repo_b)
        second = service.create(shadow_b.shadow_run_id)
        second_request = service.get_activation_request(second.promotion_id)
        service.decide_activation(
            second.promotion_id,
            decision="Approved",
            request_digest=second_request.request_digest,
            idempotency_key=f"activate:{second.promotion_id}:v1",
        )

        rollback = service.request_rollback(second.promotion_id, "RegressionObserved")
        result = service.decide_rollback(
            second.promotion_id,
            decision="Approved",
            request_digest=rollback.request_digest,
            idempotency_key=f"rollback:{second.promotion_id}:v1",
        )

        assert result.status == "RolledBack"
        assert service.get_promotion(first.promotion_id).status == "Active"
        assert service.get_active("promotion-rollback", "PROMPT_REVIEW").promotion_id == first.promotion_id
        assert database.scalar("SELECT COUNT(*) FROM quality_promotion_rollbacks") == 1
        # Zero-authority gate      Governance rollback performs no paid/local/runtime execution.
        assert database.scalar("SELECT COUNT(*) FROM deep_ai_attempts") == 0
    finally:
        database.close()


def test_rollback_reason_is_closed_and_only_current_active_can_request(tmp_path: Path) -> None:
    database = _database(tmp_path)
    try:
        evaluation_repository, shadow_repository, shadow_run = _supported_shadow(
            database,
            project_key="promotion-rollback-guard",
        )
        service = _service(database, evaluation_repository, shadow_repository)
        promotion = service.create(shadow_run.shadow_run_id)

        with pytest.raises(ValueError, match="QUALITY_PROMOTION_ROLLBACK_NOT_ACTIVE"):
            service.request_rollback(promotion.promotion_id, "OperatorDecision")

        approval = service.get_activation_request(promotion.promotion_id)
        service.decide_activation(
            promotion.promotion_id,
            decision="Approved",
            request_digest=approval.request_digest,
            idempotency_key=f"activate:{promotion.promotion_id}:v1",
        )
        with pytest.raises(ValueError, match="QUALITY_PROMOTION_ROLLBACK_REASON_FORBIDDEN"):
            service.request_rollback(promotion.promotion_id, "ArbitraryFreeText")
    finally:
        database.close()
