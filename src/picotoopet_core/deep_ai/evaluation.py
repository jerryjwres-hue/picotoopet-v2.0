"""Deterministic 2.3.23.1 quality evaluation and non-executable improvement candidates."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from statistics import mean
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from picotoopet_core.db.database import Database

from .repository import DeepAiRepository

EVALUATION_PROFILE_ID = "quality.offline.v1"
RULE_VERSION = "quality.offline.v1"
MIN_HUMAN_DECISIONS = 5
EVIDENCE_REASON_TAGS = frozenset(
    {
        "missing_evidence",
        "weak_evidence",
        "wrong_evidence",
        "insufficient_context",
    }
)
CANDIDATE_CLASSES = frozenset(
    {
        "PROMPT_REVIEW",
        "LOCAL_REASONING_REVIEW",
        "EVIDENCE_SELECTION_REVIEW",
        "PAID_ESCALATION_REVIEW",
        "COST_POLICY_REVIEW",
    }
)
REVIEW_ACTIONS = frozenset({"Reviewed", "AcceptedForShadow", "Rejected", "Cancelled"})
TERMINAL_REVIEW_STATES = frozenset({"AcceptedForShadow", "Rejected", "Cancelled"})


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


class QualityEvaluationScope(BaseModel):
    """Closed user scope; it cannot carry arbitrary data, SQL, formulas, or execution policy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_key: str = Field(min_length=1, max_length=200)
    evaluation_profile_id: Literal["quality.offline.v1"] = EVALUATION_PROFILE_ID
    stage_profile: str | None = Field(default=None, min_length=1, max_length=200)
    start_at: datetime | None = None
    end_at: datetime | None = None
    limit: int = Field(default=10000, ge=1, le=10000)


class QualityEvaluationSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot_id: str
    project_key: str
    evaluation_profile_id: str
    stage_profile: str | None
    start_at: datetime | None
    end_at: datetime | None
    limit_count: int
    scope_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    member_count: int = Field(ge=0)
    created_at: datetime


class QualityEvaluationRun(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    evaluation_run_id: str
    snapshot_id: str
    evaluation_profile_id: str
    rule_version: str
    status: str
    report_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime
    completed_at: datetime | None


class QualityEvaluationMetric(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    metric_id: str
    evaluation_run_id: str
    metric_name: str
    value: int | float | None
    numerator: int | float | None
    denominator: int | float | None
    availability: str
    cohort_dimension: str | None
    cohort_key: str | None
    cohort_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class QualityImprovementCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: str
    project_key: str
    evaluation_run_id: str
    snapshot_id: str
    rule_version: str
    candidate_class: str
    cohort_dimension: str | None
    cohort_key: str | None
    cohort_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    trigger: dict[str, object]
    reason_codes: list[str]
    status: str
    candidate_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime
    updated_at: datetime


class QualityImprovementCandidateReview(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    review_id: str
    candidate_id: str
    action: str
    idempotency_key: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class _EvaluationSample:
    sample_key: str
    local_profile: str | None
    local_model_id: str | None
    local_template_version: str | None
    local_attempt_count: int | None
    local_quality_outcome: str | None
    provider_profile_id: str | None
    provider_model_id: str | None
    paid_validation_outcome: str | None
    input_tokens: int | None
    output_tokens: int | None
    cost_usd: Decimal | None
    human_action: str
    reason_tags: tuple[str, ...]
    downstream_ref: str | None


class QualityEvaluationRepository:
    """Schema-16 persistence plus read-only access to immutable schema-15 learning facts."""

    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _snapshot_from_row(row: Any) -> QualityEvaluationSnapshot:
        return QualityEvaluationSnapshot(
            snapshot_id=row["snapshot_id"],
            project_key=row["project_key"],
            evaluation_profile_id=row["evaluation_profile_id"],
            stage_profile=row["stage_profile"],
            start_at=_parse_datetime(row["start_at"]),
            end_at=_parse_datetime(row["end_at"]),
            limit_count=row["limit_count"],
            scope_digest=row["scope_digest"],
            snapshot_digest=row["snapshot_digest"],
            member_count=row["member_count"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    @staticmethod
    def _run_from_row(row: Any) -> QualityEvaluationRun:
        return QualityEvaluationRun(
            evaluation_run_id=row["evaluation_run_id"],
            snapshot_id=row["snapshot_id"],
            evaluation_profile_id=row["evaluation_profile_id"],
            rule_version=row["rule_version"],
            status=row["status"],
            report_digest=row["report_digest"],
            created_at=datetime.fromisoformat(row["created_at"]),
            completed_at=_parse_datetime(row["completed_at"]),
        )

    @staticmethod
    def _metric_from_row(row: Any) -> QualityEvaluationMetric:
        value = json.loads(row["value_json"]) if row["value_json"] is not None else None
        return QualityEvaluationMetric(
            metric_id=row["metric_id"],
            evaluation_run_id=row["evaluation_run_id"],
            metric_name=row["metric_name"],
            value=value,
            numerator=row["numerator"],
            denominator=row["denominator"],
            availability=row["availability"],
            cohort_dimension=row["cohort_dimension"],
            cohort_key=row["cohort_key"],
            cohort_digest=row["cohort_digest"],
        )

    @staticmethod
    def _candidate_from_row(row: Any) -> QualityImprovementCandidate:
        return QualityImprovementCandidate(
            candidate_id=row["candidate_id"],
            project_key=row["project_key"],
            evaluation_run_id=row["evaluation_run_id"],
            snapshot_id=row["snapshot_id"],
            rule_version=row["rule_version"],
            candidate_class=row["candidate_class"],
            cohort_dimension=row["cohort_dimension"],
            cohort_key=row["cohort_key"],
            cohort_digest=row["cohort_digest"],
            trigger=json.loads(row["trigger_json"]),
            reason_codes=json.loads(row["reason_codes_json"]),
            status=row["status"],
            candidate_digest=row["candidate_digest"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def select_learning_rows(self, scope: QualityEvaluationScope) -> list[dict[str, object]]:
        clauses = ["e.project_key=?"]
        parameters: list[object] = [scope.project_key]
        if scope.start_at is not None:
            clauses.append("e.created_at>=?")
            parameters.append(scope.start_at.isoformat())
        if scope.end_at is not None:
            clauses.append("e.created_at<=?")
            parameters.append(scope.end_at.isoformat())
        if scope.stage_profile is not None:
            # Scope gate               Keep validation + feedback facts for the same trusted stage identity.
            clauses.append(
                "e.escalation_job_id IN ("
                "SELECT e2.escalation_job_id FROM deep_ai_learning_events e2 "
                "JOIN deep_ai_learning_details d2 ON d2.event_id=e2.event_id "
                "WHERE e2.project_key=? AND d2.local_profile=?"
                ")"
            )
            parameters.extend([scope.project_key, scope.stage_profile])
        parameters.append(scope.limit)
        rows = self.database.fetchall(
            "SELECT e.event_id,e.idempotency_key,e.project_key,e.source_kind,e.source_id,"
            "e.local_quality_outcome,e.escalation_job_id,e.human_action,e.reason_tags_json,"
            "e.final_content_digest,e.created_at,d.local_profile,d.local_model_id,"
            "d.local_template_version,d.local_attempt_count,d.quality_reasons_json,"
            "d.provider_profile_id,d.provider_model_id,d.sanitized_input_digest,"
            "d.paid_output_digest,d.input_tokens,d.output_tokens,d.cost_usd,"
            "d.paid_validation_outcome,d.downstream_ref,d.details_digest "
            "FROM deep_ai_learning_events e "
            "LEFT JOIN deep_ai_learning_details d ON d.event_id=e.event_id "
            f"WHERE {' AND '.join(clauses)} "
            "ORDER BY e.created_at ASC,e.event_id ASC LIMIT ?",
            parameters,
        )
        return [dict(row) for row in rows]

    def create_snapshot(
        self,
        *,
        scope: QualityEvaluationScope,
        scope_digest: str,
        snapshot_digest: str,
        members: list[tuple[str, str]],
    ) -> QualityEvaluationSnapshot:
        existing = self.database.fetchone(
            "SELECT * FROM quality_evaluation_snapshots WHERE snapshot_digest=?",
            (snapshot_digest,),
        )
        if existing is not None:
            return self._snapshot_from_row(existing)
        snapshot_id = str(uuid4())
        created_at = _now().isoformat()
        with self.database.transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM quality_evaluation_snapshots WHERE snapshot_digest=?",
                (snapshot_digest,),
            ).fetchone()
            if existing is not None:
                return self._snapshot_from_row(existing)
            connection.execute(
                "INSERT INTO quality_evaluation_snapshots("
                "snapshot_id,project_key,evaluation_profile_id,stage_profile,start_at,end_at,"
                "limit_count,scope_digest,snapshot_digest,member_count,created_at"
                ") VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    snapshot_id,
                    scope.project_key,
                    scope.evaluation_profile_id,
                    scope.stage_profile,
                    scope.start_at.isoformat() if scope.start_at else None,
                    scope.end_at.isoformat() if scope.end_at else None,
                    scope.limit,
                    scope_digest,
                    snapshot_digest,
                    len(members),
                    created_at,
                ),
            )
            for ordinal, (event_id, event_digest) in enumerate(members):
                connection.execute(
                    "INSERT INTO quality_evaluation_snapshot_members("
                    "snapshot_id,ordinal,event_id,event_digest) VALUES (?,?,?,?)",
                    (snapshot_id, ordinal, event_id, event_digest),
                )
        return self.get_snapshot(snapshot_id)

    def get_snapshot(self, snapshot_id: str) -> QualityEvaluationSnapshot:
        row = self.database.fetchone(
            "SELECT * FROM quality_evaluation_snapshots WHERE snapshot_id=?",
            (snapshot_id,),
        )
        if row is None:
            raise KeyError(snapshot_id)
        return self._snapshot_from_row(row)

    def list_snapshots(
        self,
        *,
        project_key: str | None = None,
        limit: int = 100,
    ) -> list[QualityEvaluationSnapshot]:
        if project_key is None:
            rows = self.database.fetchall(
                "SELECT * FROM quality_evaluation_snapshots ORDER BY created_at DESC LIMIT ?",
                (min(max(limit, 1), 500),),
            )
        else:
            rows = self.database.fetchall(
                "SELECT * FROM quality_evaluation_snapshots WHERE project_key=? "
                "ORDER BY created_at DESC LIMIT ?",
                (project_key, min(max(limit, 1), 500)),
            )
        return [self._snapshot_from_row(row) for row in rows]

    def snapshot_learning_rows(self, snapshot_id: str) -> list[dict[str, object]]:
        rows = self.database.fetchall(
            "SELECT e.event_id,e.idempotency_key,e.project_key,e.source_kind,e.source_id,"
            "e.local_quality_outcome,e.escalation_job_id,e.human_action,e.reason_tags_json,"
            "e.final_content_digest,e.created_at,d.local_profile,d.local_model_id,"
            "d.local_template_version,d.local_attempt_count,d.quality_reasons_json,"
            "d.provider_profile_id,d.provider_model_id,d.sanitized_input_digest,"
            "d.paid_output_digest,d.input_tokens,d.output_tokens,d.cost_usd,"
            "d.paid_validation_outcome,d.downstream_ref,d.details_digest "
            "FROM quality_evaluation_snapshot_members m "
            "JOIN deep_ai_learning_events e ON e.event_id=m.event_id "
            "LEFT JOIN deep_ai_learning_details d ON d.event_id=e.event_id "
            "WHERE m.snapshot_id=? ORDER BY m.ordinal ASC",
            (snapshot_id,),
        )
        return [dict(row) for row in rows]

    def get_run_for_snapshot(self, snapshot_id: str) -> QualityEvaluationRun | None:
        row = self.database.fetchone(
            "SELECT * FROM quality_evaluation_runs WHERE snapshot_id=?",
            (snapshot_id,),
        )
        return None if row is None else self._run_from_row(row)

    def create_completed_run(
        self,
        *,
        snapshot: QualityEvaluationSnapshot,
        report_digest: str,
    ) -> QualityEvaluationRun:
        existing = self.get_run_for_snapshot(snapshot.snapshot_id)
        if existing is not None:
            return existing
        run_id = str(uuid4())
        timestamp = _now().isoformat()
        with self.database.transaction() as connection:
            existing_row = connection.execute(
                "SELECT * FROM quality_evaluation_runs WHERE snapshot_id=?",
                (snapshot.snapshot_id,),
            ).fetchone()
            if existing_row is not None:
                return self._run_from_row(existing_row)
            connection.execute(
                "INSERT INTO quality_evaluation_runs("
                "evaluation_run_id,snapshot_id,evaluation_profile_id,rule_version,status,"
                "report_digest,created_at,completed_at) VALUES (?,?,?,?,?,?,?,?)",
                (
                    run_id,
                    snapshot.snapshot_id,
                    snapshot.evaluation_profile_id,
                    RULE_VERSION,
                    "Completed",
                    report_digest,
                    timestamp,
                    timestamp,
                ),
            )
        return self.get_run(run_id)

    def get_run(self, evaluation_run_id: str) -> QualityEvaluationRun:
        row = self.database.fetchone(
            "SELECT * FROM quality_evaluation_runs WHERE evaluation_run_id=?",
            (evaluation_run_id,),
        )
        if row is None:
            raise KeyError(evaluation_run_id)
        return self._run_from_row(row)

    def list_runs(self, *, limit: int = 100) -> list[QualityEvaluationRun]:
        rows = self.database.fetchall(
            "SELECT * FROM quality_evaluation_runs ORDER BY created_at DESC LIMIT ?",
            (min(max(limit, 1), 500),),
        )
        return [self._run_from_row(row) for row in rows]

    def replace_metrics(
        self,
        evaluation_run_id: str,
        metrics: list[dict[str, object]],
    ) -> None:
        with self.database.transaction() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM quality_evaluation_metrics WHERE evaluation_run_id=?",
                (evaluation_run_id,),
            ).fetchone()[0]
            if count:
                return
            for metric in metrics:
                connection.execute(
                    "INSERT INTO quality_evaluation_metrics("
                    "metric_id,evaluation_run_id,metric_name,value_json,numerator,denominator,"
                    "availability,cohort_dimension,cohort_key,cohort_digest"
                    ") VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        str(uuid4()),
                        evaluation_run_id,
                        metric["metric_name"],
                        _canonical_json(metric["value"])
                        if metric["value"] is not None
                        else None,
                        metric["numerator"],
                        metric["denominator"],
                        metric["availability"],
                        metric["cohort_dimension"],
                        metric["cohort_key"],
                        metric["cohort_digest"],
                    ),
                )

    def list_metrics(self, evaluation_run_id: str) -> list[QualityEvaluationMetric]:
        rows = self.database.fetchall(
            "SELECT * FROM quality_evaluation_metrics WHERE evaluation_run_id=? "
            "ORDER BY cohort_dimension,cohort_key,metric_name",
            (evaluation_run_id,),
        )
        return [self._metric_from_row(row) for row in rows]

    def ensure_candidate(
        self,
        *,
        project_key: str,
        evaluation_run_id: str,
        snapshot_id: str,
        candidate_class: str,
        cohort_dimension: str | None,
        cohort_key: str | None,
        cohort_digest: str,
        trigger: dict[str, object],
        reason_codes: list[str],
    ) -> QualityImprovementCandidate:
        if candidate_class not in CANDIDATE_CLASSES:
            raise ValueError("QUALITY_CANDIDATE_CLASS_FORBIDDEN")
        existing = self.database.fetchone(
            "SELECT * FROM quality_improvement_candidates WHERE evaluation_run_id=? "
            "AND rule_version=? AND candidate_class=? AND cohort_digest=?",
            (evaluation_run_id, RULE_VERSION, candidate_class, cohort_digest),
        )
        if existing is not None:
            return self._candidate_from_row(existing)
        candidate_payload = {
            "project_key": project_key,
            "evaluation_run_id": evaluation_run_id,
            "snapshot_id": snapshot_id,
            "rule_version": RULE_VERSION,
            "candidate_class": candidate_class,
            "cohort_dimension": cohort_dimension,
            "cohort_key": cohort_key,
            "cohort_digest": cohort_digest,
            "trigger": trigger,
            "reason_codes": reason_codes,
        }
        candidate_digest = _digest(candidate_payload)
        candidate_id = str(uuid4())
        timestamp = _now().isoformat()
        try:
            self.database.execute(
                "INSERT INTO quality_improvement_candidates("
                "candidate_id,project_key,evaluation_run_id,snapshot_id,rule_version,"
                "candidate_class,cohort_dimension,cohort_key,cohort_digest,trigger_json,"
                "reason_codes_json,status,candidate_digest,created_at,updated_at"
                ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    candidate_id,
                    project_key,
                    evaluation_run_id,
                    snapshot_id,
                    RULE_VERSION,
                    candidate_class,
                    cohort_dimension,
                    cohort_key,
                    cohort_digest,
                    _canonical_json(trigger),
                    _canonical_json(reason_codes),
                    "Prepared",
                    candidate_digest,
                    timestamp,
                    timestamp,
                ),
            )
        except Exception:
            existing = self.database.fetchone(
                "SELECT * FROM quality_improvement_candidates WHERE evaluation_run_id=? "
                "AND rule_version=? AND candidate_class=? AND cohort_digest=?",
                (evaluation_run_id, RULE_VERSION, candidate_class, cohort_digest),
            )
            if existing is None:
                raise
            return self._candidate_from_row(existing)
        return self.get_candidate(candidate_id)

    def get_candidate(self, candidate_id: str) -> QualityImprovementCandidate:
        row = self.database.fetchone(
            "SELECT * FROM quality_improvement_candidates WHERE candidate_id=?",
            (candidate_id,),
        )
        if row is None:
            raise KeyError(candidate_id)
        return self._candidate_from_row(row)

    def list_candidates(
        self,
        *,
        evaluation_run_id: str | None = None,
        limit: int = 200,
    ) -> list[QualityImprovementCandidate]:
        bounded = min(max(limit, 1), 500)
        if evaluation_run_id is None:
            rows = self.database.fetchall(
                "SELECT * FROM quality_improvement_candidates "
                "ORDER BY created_at ASC,candidate_class ASC LIMIT ?",
                (bounded,),
            )
        else:
            rows = self.database.fetchall(
                "SELECT * FROM quality_improvement_candidates WHERE evaluation_run_id=? "
                "ORDER BY created_at ASC,candidate_class ASC LIMIT ?",
                (evaluation_run_id, bounded),
            )
        return [self._candidate_from_row(row) for row in rows]

    def review_candidate(
        self,
        candidate_id: str,
        *,
        action: str,
        idempotency_key: str,
    ) -> QualityImprovementCandidateReview:
        if action not in REVIEW_ACTIONS:
            raise ValueError("QUALITY_CANDIDATE_REVIEW_ACTION_FORBIDDEN")
        existing = self.database.fetchone(
            "SELECT * FROM quality_improvement_candidate_reviews WHERE idempotency_key=?",
            (idempotency_key,),
        )
        if existing is not None:
            if existing["candidate_id"] != candidate_id or existing["action"] != action:
                raise ValueError("QUALITY_CANDIDATE_REVIEW_IMMUTABLE")
            return QualityImprovementCandidateReview(
                review_id=existing["review_id"],
                candidate_id=existing["candidate_id"],
                action=existing["action"],
                idempotency_key=existing["idempotency_key"],
                created_at=datetime.fromisoformat(existing["created_at"]),
            )
        review_id = str(uuid4())
        timestamp = _now().isoformat()
        review_digest = _digest(
            {
                "candidate_id": candidate_id,
                "action": action,
                "idempotency_key": idempotency_key,
            }
        )
        with self.database.transaction() as connection:
            candidate = connection.execute(
                "SELECT status FROM quality_improvement_candidates WHERE candidate_id=?",
                (candidate_id,),
            ).fetchone()
            if candidate is None:
                raise KeyError(candidate_id)
            if candidate["status"] in TERMINAL_REVIEW_STATES and candidate["status"] != action:
                raise ValueError("QUALITY_CANDIDATE_TERMINAL")
            connection.execute(
                "INSERT INTO quality_improvement_candidate_reviews("
                "review_id,candidate_id,idempotency_key,action,review_digest,created_at"
                ") VALUES (?,?,?,?,?,?)",
                (review_id, candidate_id, idempotency_key, action, review_digest, timestamp),
            )
            connection.execute(
                "UPDATE quality_improvement_candidates SET status=?,updated_at=? "
                "WHERE candidate_id=?",
                (action, timestamp, candidate_id),
            )
        return QualityImprovementCandidateReview(
            review_id=review_id,
            candidate_id=candidate_id,
            action=action,
            idempotency_key=idempotency_key,
            created_at=datetime.fromisoformat(timestamp),
        )


class QualityEvaluationService:
    """Source-controlled offline evaluator with no local/paid model or policy-mutation methods."""

    def __init__(
        self,
        *,
        repository: QualityEvaluationRepository,
        deep_ai_repository: DeepAiRepository,
    ) -> None:
        self.repository = repository
        # Authority boundary          Kept only for immutable terminal-history identity checks in tests/API.
        self.deep_ai_repository = deep_ai_repository

    @staticmethod
    def _event_digest(row: dict[str, object]) -> str:
        return _digest(
            {
                "event_id": row["event_id"],
                "idempotency_key": row["idempotency_key"],
                "project_key": row["project_key"],
                "source_kind": row["source_kind"],
                "source_id": row["source_id"],
                "local_quality_outcome": row["local_quality_outcome"],
                "escalation_job_id": row["escalation_job_id"],
                "human_action": row["human_action"],
                "reason_tags_json": row["reason_tags_json"],
                "final_content_digest": row["final_content_digest"],
                "details_digest": row["details_digest"],
            }
        )

    def create_snapshot(self, scope: QualityEvaluationScope) -> QualityEvaluationSnapshot:
        if scope.end_at is not None and scope.start_at is not None and scope.end_at < scope.start_at:
            raise ValueError("QUALITY_EVALUATION_TIME_RANGE_INVALID")
        rows = self.repository.select_learning_rows(scope)
        scope_payload = scope.model_dump(mode="json")
        scope_digest = _digest(scope_payload)
        members = [(str(row["event_id"]), self._event_digest(row)) for row in rows]
        snapshot_digest = _digest(
            {
                "profile": EVALUATION_PROFILE_ID,
                "scope_digest": scope_digest,
                "members": members,
            }
        )
        return self.repository.create_snapshot(
            scope=scope,
            scope_digest=scope_digest,
            snapshot_digest=snapshot_digest,
            members=members,
        )

    def get_snapshot(self, snapshot_id: str) -> QualityEvaluationSnapshot:
        return self.repository.get_snapshot(snapshot_id)

    def list_snapshots(
        self,
        *,
        project_key: str | None = None,
        limit: int = 100,
    ) -> list[QualityEvaluationSnapshot]:
        return self.repository.list_snapshots(project_key=project_key, limit=limit)

    @staticmethod
    def _samples(rows: list[dict[str, object]]) -> list[_EvaluationSample]:
        grouped: dict[str, list[dict[str, object]]] = {}
        for row in rows:
            key = str(
                row["escalation_job_id"]
                or f"{row['source_kind']}:{row['source_id']}"
            )
            grouped.setdefault(key, []).append(row)
        samples: list[_EvaluationSample] = []
        for sample_key in sorted(grouped):
            group = grouped[sample_key]
            validation_rows = [
                row
                for row in group
                if row["local_profile"] is not None
                or row["paid_validation_outcome"] is not None
            ]
            validation = validation_rows[-1] if validation_rows else group[-1]
            decisions = [row for row in group if row["human_action"] != "NoDecision"]
            feedback = decisions[-1] if decisions else group[-1]
            tags = sorted(
                {
                    str(tag)
                    for row in decisions
                    for tag in json.loads(str(row["reason_tags_json"] or "[]"))
                }
            )
            cost = validation["cost_usd"]
            samples.append(
                _EvaluationSample(
                    sample_key=sample_key,
                    local_profile=(
                        str(validation["local_profile"])
                        if validation["local_profile"] is not None
                        else None
                    ),
                    local_model_id=(
                        str(validation["local_model_id"])
                        if validation["local_model_id"] is not None
                        else None
                    ),
                    local_template_version=(
                        str(validation["local_template_version"])
                        if validation["local_template_version"] is not None
                        else None
                    ),
                    local_attempt_count=(
                        int(validation["local_attempt_count"])
                        if validation["local_attempt_count"] is not None
                        else None
                    ),
                    local_quality_outcome=(
                        str(validation["local_quality_outcome"])
                        if validation["local_quality_outcome"] is not None
                        else None
                    ),
                    provider_profile_id=(
                        str(validation["provider_profile_id"])
                        if validation["provider_profile_id"] is not None
                        else None
                    ),
                    provider_model_id=(
                        str(validation["provider_model_id"])
                        if validation["provider_model_id"] is not None
                        else None
                    ),
                    paid_validation_outcome=(
                        str(validation["paid_validation_outcome"])
                        if validation["paid_validation_outcome"] is not None
                        else None
                    ),
                    input_tokens=(
                        int(validation["input_tokens"])
                        if validation["input_tokens"] is not None
                        else None
                    ),
                    output_tokens=(
                        int(validation["output_tokens"])
                        if validation["output_tokens"] is not None
                        else None
                    ),
                    cost_usd=Decimal(str(cost)) if cost is not None else None,
                    human_action=str(feedback["human_action"]),
                    reason_tags=tuple(tags),
                    downstream_ref=(
                        str(validation["downstream_ref"])
                        if validation["downstream_ref"] is not None
                        else None
                    ),
                )
            )
        return samples

    @staticmethod
    def _ratio(
        numerator: int | float,
        denominator: int | float,
        *,
        insufficient: bool = False,
    ) -> tuple[float | None, str]:
        if insufficient:
            return None, "insufficient_sample"
        if denominator == 0:
            return None, "not_available"
        return float(numerator) / float(denominator), "available"

    @staticmethod
    def _p95(values: list[int]) -> float | None:
        if not values:
            return None
        ordered = sorted(values)
        index = max(0, min(len(ordered) - 1, (95 * len(ordered) + 99) // 100 - 1))
        return float(ordered[index])

    def _metric_rows(
        self,
        samples: list[_EvaluationSample],
        *,
        cohort_dimension: str | None,
        cohort_key: str | None,
        cohort_digest: str,
        minimum_sample_gate: bool,
    ) -> list[dict[str, object]]:
        decisions = [sample for sample in samples if sample.human_action != "NoDecision"]
        rejected = sum(sample.human_action == "Rejected" for sample in decisions)
        modified = sum(sample.human_action == "Modified" for sample in decisions)
        accepted = sum(sample.human_action == "Accepted" for sample in decisions)
        local_known = [sample for sample in samples if sample.local_quality_outcome is not None]
        local_needs_deep = sum(
            sample.local_quality_outcome == "NEEDS_DEEP_AI" for sample in local_known
        )
        attempts = [
            sample.local_attempt_count
            for sample in samples
            if sample.local_attempt_count is not None
        ]
        paid = [sample for sample in samples if sample.paid_validation_outcome is not None]
        paid_pass = sum(sample.paid_validation_outcome == "PASS" for sample in paid)
        paid_needs_human = sum(
            sample.paid_validation_outcome == "NEEDS_HUMAN" for sample in paid
        )
        paid_reject = sum(sample.paid_validation_outcome == "REJECT" for sample in paid)
        evidence_feedback = sum(
            bool(EVIDENCE_REASON_TAGS.intersection(sample.reason_tags)) for sample in decisions
        )
        total_input_tokens = sum(sample.input_tokens or 0 for sample in paid)
        total_output_tokens = sum(sample.output_tokens or 0 for sample in paid)
        total_cost = sum((sample.cost_usd or Decimal("0")) for sample in paid)
        downstream = sum(sample.downstream_ref is not None for sample in samples)
        insufficient = minimum_sample_gate and len(decisions) < MIN_HUMAN_DECISIONS

        def metric(
            name: str,
            value: int | float | None,
            numerator: int | float | None = None,
            denominator: int | float | None = None,
            availability: str = "available",
        ) -> dict[str, object]:
            return {
                "metric_name": name,
                "value": value,
                "numerator": numerator,
                "denominator": denominator,
                "availability": availability,
                "cohort_dimension": cohort_dimension,
                "cohort_key": cohort_key,
                "cohort_digest": cohort_digest,
            }

        rows = [
            metric("sample_count", len(samples)),
            metric("human_decision_count", len(decisions)),
            metric("human_accepted_count", accepted),
            metric("human_rejected_count", rejected),
            metric("human_modified_count", modified),
            metric("human_no_decision_count", len(samples) - len(decisions)),
        ]
        ratio, availability = self._ratio(
            rejected + modified,
            len(decisions),
            insufficient=insufficient,
        )
        rows.append(
            metric(
                "human_rejected_or_modified_rate",
                ratio,
                rejected + modified,
                len(decisions),
                availability,
            )
        )
        local_rate, local_availability = self._ratio(
            local_needs_deep,
            len(local_known),
            insufficient=insufficient,
        )
        rows.extend(
            [
                metric("local_known_count", len(local_known)),
                metric("local_needs_deep_ai_count", local_needs_deep),
                metric(
                    "local_needs_deep_ai_rate",
                    local_rate,
                    local_needs_deep,
                    len(local_known),
                    local_availability,
                ),
                metric(
                    "local_attempt_mean",
                    float(mean(attempts)) if attempts else None,
                    availability="available" if attempts else "not_available",
                ),
                metric(
                    "local_attempt_p95",
                    self._p95(attempts),
                    availability="available" if attempts else "not_available",
                ),
                metric("paid_validation_count", len(paid)),
                metric("paid_pass_count", paid_pass),
                metric("paid_needs_human_count", paid_needs_human),
                metric("paid_reject_count", paid_reject),
            ]
        )
        paid_pass_rate, paid_availability = self._ratio(paid_pass, len(paid))
        paid_failure_rate, paid_failure_availability = self._ratio(
            paid_needs_human + paid_reject,
            len(paid),
        )
        evidence_rate, evidence_availability = self._ratio(
            evidence_feedback,
            len(decisions),
            insufficient=insufficient,
        )
        downstream_rate, downstream_availability = self._ratio(downstream, len(samples))
        cost_per_pass = float(total_cost / paid_pass) if paid_pass else None
        rows.extend(
            [
                metric(
                    "paid_pass_rate",
                    paid_pass_rate,
                    paid_pass,
                    len(paid),
                    paid_availability,
                ),
                metric(
                    "paid_failure_rate",
                    paid_failure_rate,
                    paid_needs_human + paid_reject,
                    len(paid),
                    paid_failure_availability,
                ),
                metric("evidence_feedback_count", evidence_feedback),
                metric(
                    "evidence_feedback_rate",
                    evidence_rate,
                    evidence_feedback,
                    len(decisions),
                    evidence_availability,
                ),
                metric("paid_calls", len(paid)),
                metric("paid_input_tokens", total_input_tokens),
                metric("paid_output_tokens", total_output_tokens),
                metric("paid_cost_usd", float(total_cost)),
                metric(
                    "cost_per_paid_pass",
                    cost_per_pass,
                    float(total_cost),
                    paid_pass,
                    "available" if paid_pass else "not_available",
                ),
                metric(
                    "downstream_reference_rate",
                    downstream_rate,
                    downstream,
                    len(samples),
                    downstream_availability,
                ),
            ]
        )
        return rows

    @staticmethod
    def _cohorts(samples: list[_EvaluationSample]) -> list[tuple[str, str, list[_EvaluationSample]]]:
        dimensions = {
            "stage_profile": lambda sample: sample.local_profile,
            "template_version": lambda sample: sample.local_template_version,
            "local_model": lambda sample: sample.local_model_id,
            "provider_profile": lambda sample: sample.provider_profile_id,
            "paid_model": lambda sample: sample.provider_model_id,
        }
        cohorts: list[tuple[str, str, list[_EvaluationSample]]] = []
        for dimension, getter in dimensions.items():
            keys = sorted({value for sample in samples if (value := getter(sample)) is not None})
            for key in keys:
                cohorts.append((dimension, str(key), [s for s in samples if getter(s) == key]))
        return cohorts

    def _build_metrics(
        self,
        snapshot: QualityEvaluationSnapshot,
        samples: list[_EvaluationSample],
    ) -> list[dict[str, object]]:
        global_digest = _digest(
            {"snapshot_digest": snapshot.snapshot_digest, "cohort": "all"}
        )
        rows = self._metric_rows(
            samples,
            cohort_dimension=None,
            cohort_key=None,
            cohort_digest=global_digest,
            minimum_sample_gate=False,
        )
        for dimension, key, cohort_samples in self._cohorts(samples):
            cohort_digest = _digest(
                {
                    "snapshot_digest": snapshot.snapshot_digest,
                    "dimension": dimension,
                    "key": key,
                    "samples": [sample.sample_key for sample in cohort_samples],
                }
            )
            rows.extend(
                self._metric_rows(
                    cohort_samples,
                    cohort_dimension=dimension,
                    cohort_key=key,
                    cohort_digest=cohort_digest,
                    minimum_sample_gate=True,
                )
            )
        return rows

    @staticmethod
    def _metric_map(
        metrics: list[QualityEvaluationMetric],
    ) -> dict[tuple[str | None, str | None, str], QualityEvaluationMetric]:
        return {
            (metric.cohort_dimension, metric.cohort_key, metric.metric_name): metric
            for metric in metrics
        }

    def _create_candidates(
        self,
        *,
        snapshot: QualityEvaluationSnapshot,
        run: QualityEvaluationRun,
        metrics: list[QualityEvaluationMetric],
    ) -> None:
        grouped: dict[tuple[str | None, str | None, str], dict[str, QualityEvaluationMetric]] = {}
        for metric in metrics:
            identity = (metric.cohort_dimension, metric.cohort_key, metric.cohort_digest)
            grouped.setdefault(identity, {})[metric.metric_name] = metric
        for (dimension, key, cohort_digest), cohort_metrics in grouped.items():
            decisions = cohort_metrics["human_decision_count"].value or 0
            if decisions < MIN_HUMAN_DECISIONS:
                continue

            def value(name: str) -> float:
                metric_value = cohort_metrics[name].value
                return float(metric_value) if metric_value is not None else 0.0

            def trigger_for(names: list[str]) -> dict[str, object]:
                return {
                    name: {
                        "value": cohort_metrics[name].value,
                        "numerator": cohort_metrics[name].numerator,
                        "denominator": cohort_metrics[name].denominator,
                        "availability": cohort_metrics[name].availability,
                    }
                    for name in names
                }

            candidates: list[tuple[str, list[str], list[str]]] = []
            if value("human_rejected_or_modified_rate") >= 0.35:
                candidates.append(
                    (
                        "PROMPT_REVIEW",
                        ["human_rejected_or_modified_rate"],
                        ["HUMAN_REJECTED_OR_MODIFIED_RATE_HIGH"],
                    )
                )
            if (
                value("local_needs_deep_ai_rate") >= 0.30
                and value("paid_pass_count") >= 3
                and value("paid_pass_rate") >= 0.70
            ):
                candidates.append(
                    (
                        "LOCAL_REASONING_REVIEW",
                        ["local_needs_deep_ai_rate", "paid_pass_count", "paid_pass_rate"],
                        ["LOCAL_ESCALATION_RATE_HIGH_PAID_SUCCESS_HIGH"],
                    )
                )
            if (
                value("evidence_feedback_count") >= 3
                and value("evidence_feedback_rate") >= 0.25
            ):
                candidates.append(
                    (
                        "EVIDENCE_SELECTION_REVIEW",
                        ["evidence_feedback_count", "evidence_feedback_rate"],
                        ["EVIDENCE_FEEDBACK_RATE_HIGH"],
                    )
                )
            if (
                value("paid_validation_count") >= 5
                and value("paid_failure_rate") >= 0.30
            ):
                candidates.append(
                    (
                        "PAID_ESCALATION_REVIEW",
                        ["paid_validation_count", "paid_failure_rate"],
                        ["PAID_VALIDATION_FAILURE_RATE_HIGH"],
                    )
                )
            if value("paid_pass_count") >= 5 and value("cost_per_paid_pass") >= 0.30:
                candidates.append(
                    (
                        "COST_POLICY_REVIEW",
                        ["paid_pass_count", "cost_per_paid_pass"],
                        ["COST_PER_PAID_PASS_HIGH"],
                    )
                )
            for candidate_class, trigger_names, reason_codes in candidates:
                self.repository.ensure_candidate(
                    project_key=snapshot.project_key,
                    evaluation_run_id=run.evaluation_run_id,
                    snapshot_id=snapshot.snapshot_id,
                    candidate_class=candidate_class,
                    cohort_dimension=dimension,
                    cohort_key=key,
                    cohort_digest=cohort_digest,
                    trigger=trigger_for(trigger_names),
                    reason_codes=reason_codes,
                )

    def evaluate(self, snapshot_id: str) -> QualityEvaluationRun:
        snapshot = self.repository.get_snapshot(snapshot_id)
        rows = self.repository.snapshot_learning_rows(snapshot_id)
        samples = self._samples(rows)
        metric_rows = self._build_metrics(snapshot, samples)
        report_digest = _digest(
            {
                "snapshot_digest": snapshot.snapshot_digest,
                "profile": EVALUATION_PROFILE_ID,
                "rule_version": RULE_VERSION,
                "metrics": metric_rows,
            }
        )
        # Recovery gate             Reuse an existing run but always complete deterministic derived facts.
        run = self.repository.get_run_for_snapshot(snapshot_id)
        if run is None:
            run = self.repository.create_completed_run(
                snapshot=snapshot,
                report_digest=report_digest,
            )
        self.repository.replace_metrics(run.evaluation_run_id, metric_rows)
        metrics = self.repository.list_metrics(run.evaluation_run_id)
        self._create_candidates(snapshot=snapshot, run=run, metrics=metrics)
        return run

    def reconcile(self, evaluation_run_id: str) -> QualityEvaluationRun:
        run = self.repository.get_run(evaluation_run_id)
        # Recovery gate             Reconcile replays only deterministic derivation under the same run identity.
        return self.evaluate(run.snapshot_id)

    def get_run(self, evaluation_run_id: str) -> QualityEvaluationRun:
        return self.repository.get_run(evaluation_run_id)

    def list_runs(self, *, limit: int = 100) -> list[QualityEvaluationRun]:
        return self.repository.list_runs(limit=limit)

    def list_metrics(self, evaluation_run_id: str) -> list[QualityEvaluationMetric]:
        return self.repository.list_metrics(evaluation_run_id)

    def get_candidate(self, candidate_id: str) -> QualityImprovementCandidate:
        return self.repository.get_candidate(candidate_id)

    def list_candidates(
        self,
        *,
        evaluation_run_id: str | None = None,
        limit: int = 200,
    ) -> list[QualityImprovementCandidate]:
        return self.repository.list_candidates(
            evaluation_run_id=evaluation_run_id,
            limit=limit,
        )

    def review_candidate(
        self,
        candidate_id: str,
        *,
        action: str,
        idempotency_key: str,
    ) -> QualityImprovementCandidateReview:
        # Zero-mutation gate          This path writes schema-16 review facts only.
        return self.repository.review_candidate(
            candidate_id,
            action=action,
            idempotency_key=idempotency_key,
        )
