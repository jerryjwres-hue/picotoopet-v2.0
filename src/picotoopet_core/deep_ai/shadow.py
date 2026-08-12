"""Deterministic 2.3.24.1 controlled-shadow validation with zero model execution."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from picotoopet_core.db.database import Database

from .evaluation import (
    MIN_HUMAN_DECISIONS,
    QualityEvaluationRepository,
    QualityEvaluationService,
    QualityImprovementCandidate,
    _EvaluationSample,
)

SHADOW_PROFILE_ID = "quality.shadow.v1"
SPLIT_VERSION = "quality.shadow.split.v1"
SHADOW_ARMS = ("baseline", "shadow")
SHADOW_VERDICTS = frozenset({"Supported", "NeedsMoreData", "NotReproduced"})
SHADOW_REVIEW_ACTIONS = frozenset(
    {"Reviewed", "AcceptedForPromotionReview", "Rejected", "Cancelled"}
)
SHADOW_TERMINAL_REVIEW_ACTIONS = frozenset(
    {"AcceptedForPromotionReview", "Rejected", "Cancelled"}
)


def _now() -> datetime:
    return datetime.now(UTC)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _parse_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


class QualityShadowRun(BaseModel):
    """Immutable identity plus deterministic result for one accepted candidate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    shadow_run_id: str
    candidate_id: str
    evaluation_run_id: str
    snapshot_id: str
    project_key: str
    candidate_class: str
    candidate_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    evaluation_report_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    shadow_profile_id: Literal["quality.shadow.v1"] = SHADOW_PROFILE_ID
    split_version: Literal["quality.shadow.split.v1"] = SPLIT_VERSION
    status: str
    verdict: str
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    report_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime
    completed_at: datetime | None


class QualityShadowArmMetric(BaseModel):
    """One bounded metric fact for one deterministic holdout arm."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    metric_id: str
    shadow_run_id: str
    arm: Literal["baseline", "shadow"]
    metric_name: str
    value: int | float | None
    numerator: int | float | None
    denominator: int | float | None
    availability: str
    arm_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class QualityShadowReview(BaseModel):
    """Append-only human review fact; it has no runtime-policy authority."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    review_id: str
    shadow_run_id: str
    action: str
    idempotency_key: str
    created_at: datetime


class QualityShadowRepository:
    """Schema-17 storage for deterministic Shadow runs, arm metrics, and review facts."""

    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _run_from_row(row: Any) -> QualityShadowRun:
        return QualityShadowRun(
            shadow_run_id=row["shadow_run_id"],
            candidate_id=row["candidate_id"],
            evaluation_run_id=row["evaluation_run_id"],
            snapshot_id=row["snapshot_id"],
            project_key=row["project_key"],
            candidate_class=row["candidate_class"],
            candidate_digest=row["candidate_digest"],
            snapshot_digest=row["snapshot_digest"],
            evaluation_report_digest=row["evaluation_report_digest"],
            shadow_profile_id=row["shadow_profile_id"],
            split_version=row["split_version"],
            status=row["status"],
            verdict=row["verdict"],
            input_digest=row["input_digest"],
            report_digest=row["report_digest"],
            created_at=datetime.fromisoformat(row["created_at"]),
            completed_at=_parse_datetime(row["completed_at"]),
        )

    @staticmethod
    def _metric_from_row(row: Any) -> QualityShadowArmMetric:
        value = json.loads(row["value_json"]) if row["value_json"] is not None else None
        return QualityShadowArmMetric(
            metric_id=row["metric_id"],
            shadow_run_id=row["shadow_run_id"],
            arm=row["arm"],
            metric_name=row["metric_name"],
            value=value,
            numerator=row["numerator"],
            denominator=row["denominator"],
            availability=row["availability"],
            arm_digest=row["arm_digest"],
        )

    def get_run_for_candidate(self, candidate_id: str) -> QualityShadowRun | None:
        row = self.database.fetchone(
            "SELECT * FROM quality_shadow_runs WHERE candidate_id=?",
            (candidate_id,),
        )
        return None if row is None else self._run_from_row(row)

    def get_run(self, shadow_run_id: str) -> QualityShadowRun:
        row = self.database.fetchone(
            "SELECT * FROM quality_shadow_runs WHERE shadow_run_id=?",
            (shadow_run_id,),
        )
        if row is None:
            raise KeyError(shadow_run_id)
        return self._run_from_row(row)

    def list_runs(
        self,
        *,
        candidate_id: str | None = None,
        limit: int = 100,
    ) -> list[QualityShadowRun]:
        bounded = min(max(limit, 1), 500)
        if candidate_id is None:
            rows = self.database.fetchall(
                "SELECT * FROM quality_shadow_runs ORDER BY created_at DESC LIMIT ?",
                (bounded,),
            )
        else:
            rows = self.database.fetchall(
                "SELECT * FROM quality_shadow_runs WHERE candidate_id=? "
                "ORDER BY created_at DESC LIMIT ?",
                (candidate_id, bounded),
            )
        return [self._run_from_row(row) for row in rows]

    def ensure_run_identity(
        self,
        *,
        candidate: QualityImprovementCandidate,
        evaluation_report_digest: str,
        snapshot_digest: str,
        input_digest: str,
    ) -> QualityShadowRun:
        existing = self.get_run_for_candidate(candidate.candidate_id)
        if existing is not None:
            if existing.input_digest != input_digest:
                raise ValueError("QUALITY_SHADOW_SOURCE_IDENTITY_CHANGED")
            return existing

        shadow_run_id = str(uuid4())
        created_at = _now().isoformat()
        # Recovery identity         A unique pending digest permits crash-safe run creation without collisions.
        pending_report_digest = _digest(
            {
                "shadow_run_id": shadow_run_id,
                "input_digest": input_digest,
                "state": "Prepared",
            }
        )
        try:
            self.database.execute(
                "INSERT INTO quality_shadow_runs("
                "shadow_run_id,candidate_id,evaluation_run_id,snapshot_id,project_key,"
                "candidate_class,candidate_digest,snapshot_digest,evaluation_report_digest,"
                "shadow_profile_id,split_version,status,verdict,input_digest,report_digest,"
                "created_at,completed_at"
                ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    shadow_run_id,
                    candidate.candidate_id,
                    candidate.evaluation_run_id,
                    candidate.snapshot_id,
                    candidate.project_key,
                    candidate.candidate_class,
                    candidate.candidate_digest,
                    snapshot_digest,
                    evaluation_report_digest,
                    SHADOW_PROFILE_ID,
                    SPLIT_VERSION,
                    "Prepared",
                    "Pending",
                    input_digest,
                    pending_report_digest,
                    created_at,
                    None,
                ),
            )
        except Exception:
            existing = self.get_run_for_candidate(candidate.candidate_id)
            if existing is None:
                raise
            if existing.input_digest != input_digest:
                raise ValueError("QUALITY_SHADOW_SOURCE_IDENTITY_CHANGED")
            return existing
        return self.get_run(shadow_run_id)

    def replace_metrics(
        self,
        shadow_run_id: str,
        metrics: list[dict[str, object]],
    ) -> None:
        # Recovery boundary         Derived schema-17 facts are safe to replace deterministically.
        with self.database.transaction() as connection:
            connection.execute(
                "DELETE FROM quality_shadow_arm_metrics WHERE shadow_run_id=?",
                (shadow_run_id,),
            )
            for metric in metrics:
                connection.execute(
                    "INSERT INTO quality_shadow_arm_metrics("
                    "metric_id,shadow_run_id,arm,metric_name,value_json,numerator,denominator,"
                    "availability,arm_digest) VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        str(uuid4()),
                        shadow_run_id,
                        metric["arm"],
                        metric["metric_name"],
                        _canonical_json(metric["value"])
                        if metric["value"] is not None
                        else None,
                        metric["numerator"],
                        metric["denominator"],
                        metric["availability"],
                        metric["arm_digest"],
                    ),
                )

    def finalize_run(
        self,
        shadow_run_id: str,
        *,
        verdict: str,
        report_digest: str,
    ) -> QualityShadowRun:
        if verdict not in SHADOW_VERDICTS:
            raise ValueError("QUALITY_SHADOW_VERDICT_FORBIDDEN")
        completed_at = _now().isoformat()
        self.database.execute(
            "UPDATE quality_shadow_runs SET status='Completed',verdict=?,report_digest=?,"
            "completed_at=? WHERE shadow_run_id=?",
            (verdict, report_digest, completed_at, shadow_run_id),
        )
        return self.get_run(shadow_run_id)

    def list_metrics(self, shadow_run_id: str) -> list[QualityShadowArmMetric]:
        self.get_run(shadow_run_id)
        rows = self.database.fetchall(
            "SELECT * FROM quality_shadow_arm_metrics WHERE shadow_run_id=? "
            "ORDER BY arm ASC,metric_name ASC",
            (shadow_run_id,),
        )
        return [self._metric_from_row(row) for row in rows]

    def review(
        self,
        shadow_run_id: str,
        *,
        action: str,
        idempotency_key: str,
    ) -> QualityShadowReview:
        if action not in SHADOW_REVIEW_ACTIONS:
            raise ValueError("QUALITY_SHADOW_REVIEW_ACTION_FORBIDDEN")
        run = self.get_run(shadow_run_id)
        if action == "AcceptedForPromotionReview" and run.verdict != "Supported":
            raise ValueError("QUALITY_SHADOW_PROMOTION_REVIEW_NOT_SUPPORTED")
        existing = self.database.fetchone(
            "SELECT * FROM quality_shadow_reviews WHERE idempotency_key=?",
            (idempotency_key,),
        )
        if existing is not None:
            if existing["shadow_run_id"] != shadow_run_id or existing["action"] != action:
                raise ValueError("QUALITY_SHADOW_REVIEW_IMMUTABLE")
            return QualityShadowReview(
                review_id=existing["review_id"],
                shadow_run_id=existing["shadow_run_id"],
                action=existing["action"],
                idempotency_key=existing["idempotency_key"],
                created_at=datetime.fromisoformat(existing["created_at"]),
            )

        terminal = self.database.fetchone(
            "SELECT action FROM quality_shadow_reviews WHERE shadow_run_id=? "
            "AND action IN ('AcceptedForPromotionReview','Rejected','Cancelled') "
            "ORDER BY created_at DESC LIMIT 1",
            (shadow_run_id,),
        )
        if terminal is not None and terminal["action"] != action:
            raise ValueError("QUALITY_SHADOW_REVIEW_TERMINAL")

        review_id = str(uuid4())
        created_at = _now().isoformat()
        review_digest = _digest(
            {
                "shadow_run_id": shadow_run_id,
                "action": action,
                "idempotency_key": idempotency_key,
            }
        )
        self.database.execute(
            "INSERT INTO quality_shadow_reviews("
            "review_id,shadow_run_id,idempotency_key,action,review_digest,created_at"
            ") VALUES (?,?,?,?,?,?)",
            (
                review_id,
                shadow_run_id,
                idempotency_key,
                action,
                review_digest,
                created_at,
            ),
        )
        return QualityShadowReview(
            review_id=review_id,
            shadow_run_id=shadow_run_id,
            action=action,
            idempotency_key=idempotency_key,
            created_at=datetime.fromisoformat(created_at),
        )


class QualityShadowService:
    """Closed offline A/B holdout validator; no model/provider/runtime mutation methods exist."""

    def __init__(
        self,
        *,
        repository: QualityShadowRepository,
        evaluation_repository: QualityEvaluationRepository,
    ) -> None:
        self.repository = repository
        self.evaluation_repository = evaluation_repository

    @staticmethod
    def _candidate_sample_matches(
        candidate: QualityImprovementCandidate,
        sample: _EvaluationSample,
    ) -> bool:
        if candidate.cohort_dimension is None:
            return True
        getters = {
            "stage_profile": lambda item: item.local_profile,
            "template_version": lambda item: item.local_template_version,
            "local_model": lambda item: item.local_model_id,
            "provider_profile": lambda item: item.provider_profile_id,
            "paid_model": lambda item: item.provider_model_id,
        }
        getter = getters.get(candidate.cohort_dimension)
        if getter is None:
            raise ValueError("QUALITY_SHADOW_COHORT_DIMENSION_FORBIDDEN")
        return getter(sample) == candidate.cohort_key

    @staticmethod
    def _arm_for(candidate_digest: str, sample_key: str) -> str:
        assignment = hashlib.sha256(
            f"{SPLIT_VERSION}{candidate_digest}{sample_key}".encode("utf-8")
        ).digest()
        return "baseline" if assignment[-1] & 1 == 0 else "shadow"

    @staticmethod
    def _metric_map(rows: list[dict[str, object]]) -> dict[str, dict[str, object]]:
        return {str(row["metric_name"]): row for row in rows}

    @staticmethod
    def _number(metrics: dict[str, dict[str, object]], name: str) -> float:
        value = metrics[name]["value"]
        return float(value) if value is not None else 0.0

    @classmethod
    def _has_sufficient_data(
        cls,
        candidate_class: str,
        metrics: dict[str, dict[str, object]],
    ) -> bool:
        if cls._number(metrics, "human_decision_count") < MIN_HUMAN_DECISIONS:
            return False
        if candidate_class == "PROMPT_REVIEW":
            return True
        if candidate_class == "LOCAL_REASONING_REVIEW":
            return (
                cls._number(metrics, "local_known_count") > 0
                and cls._number(metrics, "paid_validation_count") >= 3
            )
        if candidate_class == "EVIDENCE_SELECTION_REVIEW":
            return True
        if candidate_class == "PAID_ESCALATION_REVIEW":
            return cls._number(metrics, "paid_validation_count") >= 5
        if candidate_class == "COST_POLICY_REVIEW":
            return (
                cls._number(metrics, "paid_validation_count") >= 5
                and cls._number(metrics, "paid_pass_count") > 0
            )
        raise ValueError("QUALITY_SHADOW_CANDIDATE_CLASS_FORBIDDEN")

    @classmethod
    def _rule_supported(
        cls,
        candidate_class: str,
        metrics: dict[str, dict[str, object]],
    ) -> bool:
        if not cls._has_sufficient_data(candidate_class, metrics):
            return False
        if candidate_class == "PROMPT_REVIEW":
            return cls._number(metrics, "human_rejected_or_modified_rate") >= 0.35
        if candidate_class == "LOCAL_REASONING_REVIEW":
            return (
                cls._number(metrics, "local_needs_deep_ai_rate") >= 0.30
                and cls._number(metrics, "paid_pass_count") >= 3
                and cls._number(metrics, "paid_pass_rate") >= 0.70
            )
        if candidate_class == "EVIDENCE_SELECTION_REVIEW":
            return (
                cls._number(metrics, "evidence_feedback_count") >= 3
                and cls._number(metrics, "evidence_feedback_rate") >= 0.25
            )
        if candidate_class == "PAID_ESCALATION_REVIEW":
            return (
                cls._number(metrics, "paid_validation_count") >= 5
                and cls._number(metrics, "paid_failure_rate") >= 0.30
            )
        if candidate_class == "COST_POLICY_REVIEW":
            return (
                cls._number(metrics, "paid_pass_count") >= 5
                and cls._number(metrics, "cost_per_paid_pass") >= 0.30
            )
        raise ValueError("QUALITY_SHADOW_CANDIDATE_CLASS_FORBIDDEN")

    def _source(self, candidate_id: str) -> tuple[QualityImprovementCandidate, Any, Any]:
        candidate = self.evaluation_repository.get_candidate(candidate_id)
        if candidate.status != "AcceptedForShadow":
            raise ValueError("QUALITY_SHADOW_CANDIDATE_NOT_ACCEPTED")
        evaluation_run = self.evaluation_repository.get_run(candidate.evaluation_run_id)
        if evaluation_run.status != "Completed":
            raise ValueError("QUALITY_SHADOW_EVALUATION_NOT_COMPLETED")
        snapshot = self.evaluation_repository.get_snapshot(candidate.snapshot_id)
        if evaluation_run.snapshot_id != snapshot.snapshot_id:
            raise ValueError("QUALITY_SHADOW_SOURCE_IDENTITY_CHANGED")
        return candidate, evaluation_run, snapshot

    def _derive(
        self,
        *,
        candidate: QualityImprovementCandidate,
        snapshot: Any,
        input_digest: str,
    ) -> tuple[list[dict[str, object]], str, str]:
        rows = self.evaluation_repository.snapshot_learning_rows(snapshot.snapshot_id)
        samples = [
            sample
            for sample in QualityEvaluationService._samples(rows)
            if self._candidate_sample_matches(candidate, sample)
        ]
        arms: dict[str, list[_EvaluationSample]] = {"baseline": [], "shadow": []}
        for sample in samples:
            arms[self._arm_for(candidate.candidate_digest, sample.sample_key)].append(sample)

        all_metrics: list[dict[str, object]] = []
        arm_maps: dict[str, dict[str, dict[str, object]]] = {}
        for arm in SHADOW_ARMS:
            arm_samples = arms[arm]
            arm_digest = _digest(
                {
                    "input_digest": input_digest,
                    "arm": arm,
                    "sample_keys": sorted(sample.sample_key for sample in arm_samples),
                }
            )
            metric_rows = QualityEvaluationService._metric_rows(
                QualityEvaluationService.__new__(QualityEvaluationService),
                arm_samples,
                cohort_dimension="shadow_arm",
                cohort_key=arm,
                cohort_digest=arm_digest,
                minimum_sample_gate=False,
            )
            normalized_rows: list[dict[str, object]] = []
            for row in metric_rows:
                normalized = {
                    "arm": arm,
                    "metric_name": row["metric_name"],
                    "value": row["value"],
                    "numerator": row["numerator"],
                    "denominator": row["denominator"],
                    "availability": row["availability"],
                    "arm_digest": arm_digest,
                }
                normalized_rows.append(normalized)
                all_metrics.append(normalized)
            arm_maps[arm] = self._metric_map(normalized_rows)

        sufficient = {
            arm: self._has_sufficient_data(candidate.candidate_class, arm_maps[arm])
            for arm in SHADOW_ARMS
        }
        supported = {
            arm: self._rule_supported(candidate.candidate_class, arm_maps[arm])
            for arm in SHADOW_ARMS
        }
        if not all(sufficient.values()):
            verdict = "NeedsMoreData"
        elif all(supported.values()):
            verdict = "Supported"
        else:
            verdict = "NotReproduced"

        report_digest = _digest(
            {
                "input_digest": input_digest,
                "profile": SHADOW_PROFILE_ID,
                "split_version": SPLIT_VERSION,
                "candidate_class": candidate.candidate_class,
                "metrics": all_metrics,
                "sufficient": sufficient,
                "supported": supported,
                "verdict": verdict,
            }
        )
        return all_metrics, verdict, report_digest

    def create(self, candidate_id: str) -> QualityShadowRun:
        candidate, evaluation_run, snapshot = self._source(candidate_id)
        input_digest = _digest(
            {
                "candidate_id": candidate.candidate_id,
                "candidate_digest": candidate.candidate_digest,
                "candidate_class": candidate.candidate_class,
                "evaluation_run_id": evaluation_run.evaluation_run_id,
                "evaluation_report_digest": evaluation_run.report_digest,
                "snapshot_id": snapshot.snapshot_id,
                "snapshot_digest": snapshot.snapshot_digest,
                "shadow_profile_id": SHADOW_PROFILE_ID,
                "split_version": SPLIT_VERSION,
            }
        )
        run = self.repository.ensure_run_identity(
            candidate=candidate,
            evaluation_report_digest=evaluation_run.report_digest,
            snapshot_digest=snapshot.snapshot_digest,
            input_digest=input_digest,
        )
        metrics, verdict, report_digest = self._derive(
            candidate=candidate,
            snapshot=snapshot,
            input_digest=input_digest,
        )
        self.repository.replace_metrics(run.shadow_run_id, metrics)
        return self.repository.finalize_run(
            run.shadow_run_id,
            verdict=verdict,
            report_digest=report_digest,
        )

    def reconcile(self, shadow_run_id: str) -> QualityShadowRun:
        run = self.repository.get_run(shadow_run_id)
        # Recovery gate             Reconcile never broadens authority; it replays the same accepted candidate.
        reconciled = self.create(run.candidate_id)
        if reconciled.shadow_run_id != shadow_run_id:
            raise ValueError("QUALITY_SHADOW_RUN_IDENTITY_CHANGED")
        return reconciled

    def get_run(self, shadow_run_id: str) -> QualityShadowRun:
        return self.repository.get_run(shadow_run_id)

    def list_runs(
        self,
        *,
        candidate_id: str | None = None,
        limit: int = 100,
    ) -> list[QualityShadowRun]:
        return self.repository.list_runs(candidate_id=candidate_id, limit=limit)

    def list_metrics(self, shadow_run_id: str) -> list[QualityShadowArmMetric]:
        return self.repository.list_metrics(shadow_run_id)

    def review(
        self,
        shadow_run_id: str,
        *,
        action: str,
        idempotency_key: str,
    ) -> QualityShadowReview:
        # Fact-only gate            This operation writes schema-17 review facts only.
        return self.repository.review(
            shadow_run_id,
            action=action,
            idempotency_key=idempotency_key,
        )
