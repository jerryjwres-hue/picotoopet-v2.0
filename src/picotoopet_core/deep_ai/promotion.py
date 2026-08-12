"""2.3.25.1 exact-approval Promotion registry with reversible governance rollback."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from picotoopet_core.db.database import Database

from .evaluation import QualityEvaluationRepository
from .shadow import QualityShadowRepository, QualityShadowRun

PROMOTION_PROFILE_ID = "quality.promotion.v1"
PROMOTION_DECISIONS = frozenset({"Approved", "Rejected", "Cancelled"})
ROLLBACK_REASON_CODES = frozenset(
    {"RegressionObserved", "UnexpectedImpact", "OperatorDecision"}
)
APPROVAL_TTL = timedelta(minutes=30)


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


class QualityPromotion(BaseModel):
    """Versioned governance fact; 25.1 runtime does not consume it as execution policy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    promotion_id: str
    shadow_run_id: str
    candidate_id: str
    project_key: str
    candidate_class: str
    candidate_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    shadow_report_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    evaluation_report_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    promotion_profile_id: Literal["quality.promotion.v1"] = PROMOTION_PROFILE_ID
    slot_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    version_no: int = Field(ge=1)
    proposal_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: str
    supersedes_promotion_id: str | None
    created_at: datetime
    activated_at: datetime | None
    rolled_back_at: datetime | None


class QualityPromotionApprovalRequest(BaseModel):
    """Exact digest-bound activation or rollback request with no executable payload."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    approval_request_id: str
    promotion_id: str
    approval_kind: Literal["PromotionActivation", "PromotionRollback"]
    request_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: str
    rollback_reason_code: str | None
    restore_promotion_id: str | None
    created_at: datetime
    expires_at: datetime
    resolved_at: datetime | None


class QualityPromotionDecision(BaseModel):
    """Append-only exact human decision fact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    decision_id: str
    approval_request_id: str
    promotion_id: str
    decision: str
    request_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    idempotency_key: str
    decision_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime


class QualityPromotionRollback(BaseModel):
    """Immutable rollback fact that records the direct predecessor restoration target."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rollback_id: str
    promotion_id: str
    restore_promotion_id: str | None
    approval_request_id: str
    rollback_reason_code: str
    request_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    rollback_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime


class QualityPromotionHistory(BaseModel):
    """Read-only decision and rollback history for one Promotion version."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    decisions: list[QualityPromotionDecision]
    rollbacks: list[QualityPromotionRollback]


class QualityPromotionRepository:
    """Schema-18 persistence for Promotion versions, approvals and rollback facts."""

    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _promotion_from_row(row: Any) -> QualityPromotion:
        return QualityPromotion(
            promotion_id=row["promotion_id"],
            shadow_run_id=row["shadow_run_id"],
            candidate_id=row["candidate_id"],
            project_key=row["project_key"],
            candidate_class=row["candidate_class"],
            candidate_digest=row["candidate_digest"],
            shadow_report_digest=row["shadow_report_digest"],
            evaluation_report_digest=row["evaluation_report_digest"],
            snapshot_digest=row["snapshot_digest"],
            promotion_profile_id=row["promotion_profile_id"],
            slot_key=row["slot_key"],
            version_no=row["version_no"],
            proposal_digest=row["proposal_digest"],
            status=row["status"],
            supersedes_promotion_id=row["supersedes_promotion_id"],
            created_at=datetime.fromisoformat(row["created_at"]),
            activated_at=_parse_datetime(row["activated_at"]),
            rolled_back_at=_parse_datetime(row["rolled_back_at"]),
        )

    @staticmethod
    def _approval_from_row(row: Any) -> QualityPromotionApprovalRequest:
        return QualityPromotionApprovalRequest(
            approval_request_id=row["approval_request_id"],
            promotion_id=row["promotion_id"],
            approval_kind=row["approval_kind"],
            request_digest=row["request_digest"],
            status=row["status"],
            rollback_reason_code=row["rollback_reason_code"],
            restore_promotion_id=row["restore_promotion_id"],
            created_at=datetime.fromisoformat(row["created_at"]),
            expires_at=datetime.fromisoformat(row["expires_at"]),
            resolved_at=_parse_datetime(row["resolved_at"]),
        )

    @staticmethod
    def _decision_from_row(row: Any) -> QualityPromotionDecision:
        return QualityPromotionDecision(
            decision_id=row["decision_id"],
            approval_request_id=row["approval_request_id"],
            promotion_id=row["promotion_id"],
            decision=row["decision"],
            request_digest=row["request_digest"],
            idempotency_key=row["idempotency_key"],
            decision_digest=row["decision_digest"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    @staticmethod
    def _rollback_from_row(row: Any) -> QualityPromotionRollback:
        return QualityPromotionRollback(
            rollback_id=row["rollback_id"],
            promotion_id=row["promotion_id"],
            restore_promotion_id=row["restore_promotion_id"],
            approval_request_id=row["approval_request_id"],
            rollback_reason_code=row["rollback_reason_code"],
            request_digest=row["request_digest"],
            rollback_digest=row["rollback_digest"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def get_for_shadow(self, shadow_run_id: str) -> QualityPromotion | None:
        row = self.database.fetchone(
            "SELECT * FROM quality_promotions WHERE shadow_run_id=?",
            (shadow_run_id,),
        )
        return None if row is None else self._promotion_from_row(row)

    def get_promotion(self, promotion_id: str) -> QualityPromotion:
        row = self.database.fetchone(
            "SELECT * FROM quality_promotions WHERE promotion_id=?",
            (promotion_id,),
        )
        if row is None:
            raise KeyError(promotion_id)
        return self._promotion_from_row(row)

    def list_promotions(
        self,
        *,
        project_key: str | None = None,
        candidate_class: str | None = None,
        limit: int = 200,
    ) -> list[QualityPromotion]:
        clauses: list[str] = []
        parameters: list[object] = []
        if project_key is not None:
            clauses.append("project_key=?")
            parameters.append(project_key)
        if candidate_class is not None:
            clauses.append("candidate_class=?")
            parameters.append(candidate_class)
        where = f"WHERE {' AND '.join(clauses)} " if clauses else ""
        parameters.append(min(max(limit, 1), 500))
        rows = self.database.fetchall(
            f"SELECT * FROM quality_promotions {where}"
            "ORDER BY created_at DESC,version_no DESC LIMIT ?",
            parameters,
        )
        return [self._promotion_from_row(row) for row in rows]

    @staticmethod
    def slot_key(project_key: str, candidate_class: str) -> str:
        # Slot identity             Closed governance scope; no caller-provided partition key exists.
        return hashlib.sha256(
            f"{project_key}{candidate_class}{PROMOTION_PROFILE_ID}".encode("utf-8")
        ).hexdigest()

    def get_active(self, project_key: str, candidate_class: str) -> QualityPromotion | None:
        slot_key = self.slot_key(project_key, candidate_class)
        row = self.database.fetchone(
            "SELECT * FROM quality_promotions WHERE slot_key=? AND status='Active'",
            (slot_key,),
        )
        return None if row is None else self._promotion_from_row(row)

    def create_proposal(
        self,
        *,
        shadow: QualityShadowRun,
    ) -> QualityPromotion:
        existing = self.get_for_shadow(shadow.shadow_run_id)
        if existing is not None:
            return existing

        promotion_id = str(uuid4())
        approval_request_id = str(uuid4())
        created_at = _now()
        expires_at = created_at + APPROVAL_TTL
        slot_key = self.slot_key(shadow.project_key, shadow.candidate_class)
        with self.database.transaction() as connection:
            existing_row = connection.execute(
                "SELECT * FROM quality_promotions WHERE shadow_run_id=?",
                (shadow.shadow_run_id,),
            ).fetchone()
            if existing_row is not None:
                return self._promotion_from_row(existing_row)
            version_no = int(
                connection.execute(
                    "SELECT COALESCE(MAX(version_no),0)+1 FROM quality_promotions WHERE slot_key=?",
                    (slot_key,),
                ).fetchone()[0]
            )
            proposal_payload = {
                "shadow_run_id": shadow.shadow_run_id,
                "candidate_id": shadow.candidate_id,
                "project_key": shadow.project_key,
                "candidate_class": shadow.candidate_class,
                "candidate_digest": shadow.candidate_digest,
                "shadow_report_digest": shadow.report_digest,
                "evaluation_report_digest": shadow.evaluation_report_digest,
                "snapshot_digest": shadow.snapshot_digest,
                "promotion_profile_id": PROMOTION_PROFILE_ID,
                "slot_key": slot_key,
                "version_no": version_no,
            }
            proposal_digest = _digest(proposal_payload)
            connection.execute(
                "INSERT INTO quality_promotions("
                "promotion_id,shadow_run_id,candidate_id,project_key,candidate_class,"
                "candidate_digest,shadow_report_digest,evaluation_report_digest,snapshot_digest,"
                "promotion_profile_id,slot_key,version_no,proposal_digest,status,"
                "supersedes_promotion_id,created_at,activated_at,rolled_back_at"
                ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    promotion_id,
                    shadow.shadow_run_id,
                    shadow.candidate_id,
                    shadow.project_key,
                    shadow.candidate_class,
                    shadow.candidate_digest,
                    shadow.report_digest,
                    shadow.evaluation_report_digest,
                    shadow.snapshot_digest,
                    PROMOTION_PROFILE_ID,
                    slot_key,
                    version_no,
                    proposal_digest,
                    "AwaitingApproval",
                    None,
                    created_at.isoformat(),
                    None,
                    None,
                ),
            )
            request_digest = _digest(
                {
                    "approval_kind": "PromotionActivation",
                    "promotion_id": promotion_id,
                    "proposal_digest": proposal_digest,
                    "slot_key": slot_key,
                    "version_no": version_no,
                    "created_at": created_at.isoformat(),
                    "expires_at": expires_at.isoformat(),
                }
            )
            connection.execute(
                "INSERT INTO quality_promotion_approval_requests("
                "approval_request_id,promotion_id,approval_kind,request_digest,status,"
                "rollback_reason_code,restore_promotion_id,created_at,expires_at,resolved_at"
                ") VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    approval_request_id,
                    promotion_id,
                    "PromotionActivation",
                    request_digest,
                    "Pending",
                    None,
                    None,
                    created_at.isoformat(),
                    expires_at.isoformat(),
                    None,
                ),
            )
        return self.get_promotion(promotion_id)

    def get_approval_request(
        self,
        promotion_id: str,
        approval_kind: str,
    ) -> QualityPromotionApprovalRequest:
        self.get_promotion(promotion_id)
        row = self.database.fetchone(
            "SELECT * FROM quality_promotion_approval_requests "
            "WHERE promotion_id=? AND approval_kind=?",
            (promotion_id, approval_kind),
        )
        if row is None:
            raise KeyError(f"{promotion_id}:{approval_kind}")
        return self._approval_from_row(row)

    def find_decision_by_idempotency(self, idempotency_key: str) -> QualityPromotionDecision | None:
        row = self.database.fetchone(
            "SELECT * FROM quality_promotion_decisions WHERE idempotency_key=?",
            (idempotency_key,),
        )
        return None if row is None else self._decision_from_row(row)

    def expire_request_if_needed(
        self,
        approval_request_id: str,
    ) -> QualityPromotionApprovalRequest:
        row = self.database.fetchone(
            "SELECT * FROM quality_promotion_approval_requests WHERE approval_request_id=?",
            (approval_request_id,),
        )
        if row is None:
            raise KeyError(approval_request_id)
        request = self._approval_from_row(row)
        if request.status != "Pending" or request.expires_at > _now():
            return request
        resolved_at = _now().isoformat()
        self.database.execute(
            "UPDATE quality_promotion_approval_requests SET status='Expired',resolved_at=? "
            "WHERE approval_request_id=? AND status='Pending'",
            (resolved_at, approval_request_id),
        )
        return self.get_approval_request(request.promotion_id, request.approval_kind)

    @staticmethod
    def _decision_values(
        *,
        request: QualityPromotionApprovalRequest,
        decision: str,
        idempotency_key: str,
        created_at: datetime,
    ) -> tuple[str, str, str]:
        decision_id = str(uuid4())
        decision_digest = _digest(
            {
                "approval_request_id": request.approval_request_id,
                "promotion_id": request.promotion_id,
                "decision": decision,
                "request_digest": request.request_digest,
                "idempotency_key": idempotency_key,
                "created_at": created_at.isoformat(),
            }
        )
        return decision_id, decision_digest, created_at.isoformat()

    def apply_activation_decision(
        self,
        *,
        promotion: QualityPromotion,
        request: QualityPromotionApprovalRequest,
        decision: str,
        idempotency_key: str,
    ) -> QualityPromotion:
        timestamp = _now()
        decision_id, decision_digest, created_at = self._decision_values(
            request=request,
            decision=decision,
            idempotency_key=idempotency_key,
            created_at=timestamp,
        )
        with self.database.transaction() as connection:
            request_row = connection.execute(
                "SELECT * FROM quality_promotion_approval_requests WHERE approval_request_id=?",
                (request.approval_request_id,),
            ).fetchone()
            if request_row is None:
                raise KeyError(request.approval_request_id)
            if request_row["status"] != "Pending":
                raise ValueError("QUALITY_PROMOTION_APPROVAL_TERMINAL")
            promotion_row = connection.execute(
                "SELECT * FROM quality_promotions WHERE promotion_id=?",
                (promotion.promotion_id,),
            ).fetchone()
            if promotion_row is None:
                raise KeyError(promotion.promotion_id)
            if promotion_row["status"] != "AwaitingApproval":
                raise ValueError("QUALITY_PROMOTION_APPROVAL_TERMINAL")

            if decision == "Approved":
                active_row = connection.execute(
                    "SELECT * FROM quality_promotions WHERE slot_key=? AND status='Active'",
                    (promotion.slot_key,),
                ).fetchone()
                supersedes_id = active_row["promotion_id"] if active_row is not None else None
                if active_row is not None:
                    # Unique-index gate         Remove the old Active marker before activating the new version.
                    connection.execute(
                        "UPDATE quality_promotions SET status='Superseded' WHERE promotion_id=?",
                        (supersedes_id,),
                    )
                connection.execute(
                    "UPDATE quality_promotions SET status='Active',supersedes_promotion_id=?,"
                    "activated_at=? WHERE promotion_id=?",
                    (supersedes_id, timestamp.isoformat(), promotion.promotion_id),
                )
            else:
                connection.execute(
                    "UPDATE quality_promotions SET status=? WHERE promotion_id=?",
                    (decision, promotion.promotion_id),
                )
            connection.execute(
                "UPDATE quality_promotion_approval_requests SET status=?,resolved_at=? "
                "WHERE approval_request_id=?",
                (decision, timestamp.isoformat(), request.approval_request_id),
            )
            connection.execute(
                "INSERT INTO quality_promotion_decisions("
                "decision_id,approval_request_id,promotion_id,decision,request_digest,"
                "idempotency_key,decision_digest,created_at) VALUES (?,?,?,?,?,?,?,?)",
                (
                    decision_id,
                    request.approval_request_id,
                    promotion.promotion_id,
                    decision,
                    request.request_digest,
                    idempotency_key,
                    decision_digest,
                    created_at,
                ),
            )
        return self.get_promotion(promotion.promotion_id)

    def create_rollback_request(
        self,
        promotion: QualityPromotion,
        rollback_reason_code: str,
    ) -> QualityPromotionApprovalRequest:
        existing_row = self.database.fetchone(
            "SELECT * FROM quality_promotion_approval_requests "
            "WHERE promotion_id=? AND approval_kind='PromotionRollback'",
            (promotion.promotion_id,),
        )
        if existing_row is not None:
            existing = self._approval_from_row(existing_row)
            if existing.rollback_reason_code != rollback_reason_code:
                raise ValueError("QUALITY_PROMOTION_ROLLBACK_REQUEST_IMMUTABLE")
            return existing

        created_at = _now()
        expires_at = created_at + APPROVAL_TTL
        approval_request_id = str(uuid4())
        request_digest = _digest(
            {
                "approval_kind": "PromotionRollback",
                "promotion_id": promotion.promotion_id,
                "proposal_digest": promotion.proposal_digest,
                "slot_key": promotion.slot_key,
                "version_no": promotion.version_no,
                "restore_promotion_id": promotion.supersedes_promotion_id,
                "rollback_reason_code": rollback_reason_code,
                "created_at": created_at.isoformat(),
                "expires_at": expires_at.isoformat(),
            }
        )
        try:
            self.database.execute(
                "INSERT INTO quality_promotion_approval_requests("
                "approval_request_id,promotion_id,approval_kind,request_digest,status,"
                "rollback_reason_code,restore_promotion_id,created_at,expires_at,resolved_at"
                ") VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    approval_request_id,
                    promotion.promotion_id,
                    "PromotionRollback",
                    request_digest,
                    "Pending",
                    rollback_reason_code,
                    promotion.supersedes_promotion_id,
                    created_at.isoformat(),
                    expires_at.isoformat(),
                    None,
                ),
            )
        except Exception:
            existing = self.get_approval_request(promotion.promotion_id, "PromotionRollback")
            if existing.rollback_reason_code != rollback_reason_code:
                raise ValueError("QUALITY_PROMOTION_ROLLBACK_REQUEST_IMMUTABLE")
            return existing
        return self.get_approval_request(promotion.promotion_id, "PromotionRollback")

    def apply_rollback_decision(
        self,
        *,
        promotion: QualityPromotion,
        request: QualityPromotionApprovalRequest,
        decision: str,
        idempotency_key: str,
    ) -> QualityPromotion:
        timestamp = _now()
        decision_id, decision_digest, created_at = self._decision_values(
            request=request,
            decision=decision,
            idempotency_key=idempotency_key,
            created_at=timestamp,
        )
        with self.database.transaction() as connection:
            request_row = connection.execute(
                "SELECT * FROM quality_promotion_approval_requests WHERE approval_request_id=?",
                (request.approval_request_id,),
            ).fetchone()
            if request_row is None:
                raise KeyError(request.approval_request_id)
            if request_row["status"] != "Pending":
                raise ValueError("QUALITY_PROMOTION_APPROVAL_TERMINAL")
            current_row = connection.execute(
                "SELECT * FROM quality_promotions WHERE promotion_id=?",
                (promotion.promotion_id,),
            ).fetchone()
            if current_row is None:
                raise KeyError(promotion.promotion_id)
            if current_row["status"] != "Active":
                raise ValueError("QUALITY_PROMOTION_ROLLBACK_NOT_ACTIVE")
            active_row = connection.execute(
                "SELECT promotion_id FROM quality_promotions WHERE slot_key=? AND status='Active'",
                (promotion.slot_key,),
            ).fetchone()
            if active_row is None or active_row["promotion_id"] != promotion.promotion_id:
                raise ValueError("QUALITY_PROMOTION_ROLLBACK_NOT_ACTIVE")

            if decision == "Approved":
                # Unique-index gate         Clear current Active before restoring the direct predecessor.
                connection.execute(
                    "UPDATE quality_promotions SET status='RolledBack',rolled_back_at=? "
                    "WHERE promotion_id=?",
                    (timestamp.isoformat(), promotion.promotion_id),
                )
                restore_id = request.restore_promotion_id
                if restore_id is not None:
                    restore_row = connection.execute(
                        "SELECT * FROM quality_promotions WHERE promotion_id=?",
                        (restore_id,),
                    ).fetchone()
                    if (
                        restore_row is None
                        or restore_row["slot_key"] != promotion.slot_key
                        or restore_row["status"] != "Superseded"
                    ):
                        raise ValueError("QUALITY_PROMOTION_ROLLBACK_RESTORE_INVALID")
                    connection.execute(
                        "UPDATE quality_promotions SET status='Active' WHERE promotion_id=?",
                        (restore_id,),
                    )
                rollback_id = str(uuid4())
                rollback_digest = _digest(
                    {
                        "promotion_id": promotion.promotion_id,
                        "restore_promotion_id": restore_id,
                        "approval_request_id": request.approval_request_id,
                        "rollback_reason_code": request.rollback_reason_code,
                        "request_digest": request.request_digest,
                    }
                )
                connection.execute(
                    "INSERT INTO quality_promotion_rollbacks("
                    "rollback_id,promotion_id,restore_promotion_id,approval_request_id,"
                    "rollback_reason_code,request_digest,rollback_digest,created_at"
                    ") VALUES (?,?,?,?,?,?,?,?)",
                    (
                        rollback_id,
                        promotion.promotion_id,
                        restore_id,
                        request.approval_request_id,
                        request.rollback_reason_code,
                        request.request_digest,
                        rollback_digest,
                        timestamp.isoformat(),
                    ),
                )
            connection.execute(
                "UPDATE quality_promotion_approval_requests SET status=?,resolved_at=? "
                "WHERE approval_request_id=?",
                (decision, timestamp.isoformat(), request.approval_request_id),
            )
            connection.execute(
                "INSERT INTO quality_promotion_decisions("
                "decision_id,approval_request_id,promotion_id,decision,request_digest,"
                "idempotency_key,decision_digest,created_at) VALUES (?,?,?,?,?,?,?,?)",
                (
                    decision_id,
                    request.approval_request_id,
                    promotion.promotion_id,
                    decision,
                    request.request_digest,
                    idempotency_key,
                    decision_digest,
                    created_at,
                ),
            )
        return self.get_promotion(promotion.promotion_id)

    def history(self, promotion_id: str) -> QualityPromotionHistory:
        self.get_promotion(promotion_id)
        decisions = self.database.fetchall(
            "SELECT * FROM quality_promotion_decisions WHERE promotion_id=? ORDER BY created_at ASC",
            (promotion_id,),
        )
        rollbacks = self.database.fetchall(
            "SELECT * FROM quality_promotion_rollbacks WHERE promotion_id=? ORDER BY created_at ASC",
            (promotion_id,),
        )
        return QualityPromotionHistory(
            decisions=[self._decision_from_row(row) for row in decisions],
            rollbacks=[self._rollback_from_row(row) for row in rollbacks],
        )


class QualityPromotionService:
    """Closed Promotion governance service; no runtime policy or model execution authority exists."""

    def __init__(
        self,
        *,
        repository: QualityPromotionRepository,
        shadow_repository: QualityShadowRepository,
        evaluation_repository: QualityEvaluationRepository,
    ) -> None:
        self.repository = repository
        self.shadow_repository = shadow_repository
        self.evaluation_repository = evaluation_repository

    def _eligible_shadow(self, shadow_run_id: str) -> QualityShadowRun:
        shadow = self.shadow_repository.get_run(shadow_run_id)
        if shadow.status != "Completed" or shadow.verdict != "Supported":
            raise ValueError("QUALITY_PROMOTION_SHADOW_NOT_SUPPORTED")
        accepted = self.repository.database.fetchone(
            "SELECT 1 FROM quality_shadow_reviews WHERE shadow_run_id=? "
            "AND action='AcceptedForPromotionReview' LIMIT 1",
            (shadow_run_id,),
        )
        if accepted is None:
            raise ValueError("QUALITY_PROMOTION_SHADOW_NOT_ACCEPTED")

        candidate = self.evaluation_repository.get_candidate(shadow.candidate_id)
        evaluation_run = self.evaluation_repository.get_run(shadow.evaluation_run_id)
        snapshot = self.evaluation_repository.get_snapshot(shadow.snapshot_id)
        if (
            candidate.candidate_id != shadow.candidate_id
            or candidate.project_key != shadow.project_key
            or candidate.candidate_class != shadow.candidate_class
            or candidate.candidate_digest != shadow.candidate_digest
            or candidate.evaluation_run_id != shadow.evaluation_run_id
            or candidate.snapshot_id != shadow.snapshot_id
            or evaluation_run.status != "Completed"
            or evaluation_run.report_digest != shadow.evaluation_report_digest
            or snapshot.snapshot_digest != shadow.snapshot_digest
        ):
            raise ValueError("QUALITY_PROMOTION_SOURCE_IDENTITY_CHANGED")
        return shadow

    def create(self, shadow_run_id: str) -> QualityPromotion:
        existing = self.repository.get_for_shadow(shadow_run_id)
        if existing is not None:
            self._eligible_shadow(shadow_run_id)
            return existing
        shadow = self._eligible_shadow(shadow_run_id)
        return self.repository.create_proposal(shadow=shadow)

    def get_promotion(self, promotion_id: str) -> QualityPromotion:
        return self.repository.get_promotion(promotion_id)

    def list_promotions(
        self,
        *,
        project_key: str | None = None,
        candidate_class: str | None = None,
        limit: int = 200,
    ) -> list[QualityPromotion]:
        return self.repository.list_promotions(
            project_key=project_key,
            candidate_class=candidate_class,
            limit=limit,
        )

    def get_active(self, project_key: str, candidate_class: str) -> QualityPromotion | None:
        return self.repository.get_active(project_key, candidate_class)

    def get_activation_request(self, promotion_id: str) -> QualityPromotionApprovalRequest:
        request = self.repository.get_approval_request(promotion_id, "PromotionActivation")
        return self.repository.expire_request_if_needed(request.approval_request_id)

    def _decide(
        self,
        *,
        promotion_id: str,
        approval_kind: str,
        decision: str,
        request_digest: str,
        idempotency_key: str,
    ) -> QualityPromotion:
        if decision not in PROMOTION_DECISIONS:
            raise ValueError("QUALITY_PROMOTION_DECISION_FORBIDDEN")
        if not idempotency_key.strip():
            raise ValueError("QUALITY_PROMOTION_IDEMPOTENCY_KEY_REQUIRED")

        promotion = self.repository.get_promotion(promotion_id)
        request = self.repository.get_approval_request(promotion_id, approval_kind)
        if not hmac.compare_digest(request.request_digest, request_digest):
            raise ValueError("QUALITY_PROMOTION_APPROVAL_DIGEST_CHANGED")

        existing = self.repository.find_decision_by_idempotency(idempotency_key)
        if existing is not None:
            if (
                existing.promotion_id != promotion_id
                or existing.approval_request_id != request.approval_request_id
                or existing.decision != decision
                or not hmac.compare_digest(existing.request_digest, request_digest)
            ):
                raise ValueError("QUALITY_PROMOTION_DECISION_IMMUTABLE")
            return self.repository.get_promotion(promotion_id)

        request = self.repository.expire_request_if_needed(request.approval_request_id)
        if request.status == "Expired":
            raise ValueError("QUALITY_PROMOTION_APPROVAL_EXPIRED")
        if request.status != "Pending":
            raise ValueError("QUALITY_PROMOTION_APPROVAL_TERMINAL")

        if approval_kind == "PromotionActivation":
            if decision == "Approved":
                self._eligible_shadow(promotion.shadow_run_id)
                current = self.repository.get_promotion(promotion_id)
                if current.proposal_digest != promotion.proposal_digest:
                    raise ValueError("QUALITY_PROMOTION_SOURCE_IDENTITY_CHANGED")
            return self.repository.apply_activation_decision(
                promotion=promotion,
                request=request,
                decision=decision,
                idempotency_key=idempotency_key,
            )
        return self.repository.apply_rollback_decision(
            promotion=promotion,
            request=request,
            decision=decision,
            idempotency_key=idempotency_key,
        )

    def decide_activation(
        self,
        promotion_id: str,
        *,
        decision: str,
        request_digest: str,
        idempotency_key: str,
    ) -> QualityPromotion:
        return self._decide(
            promotion_id=promotion_id,
            approval_kind="PromotionActivation",
            decision=decision,
            request_digest=request_digest,
            idempotency_key=idempotency_key,
        )

    def request_rollback(
        self,
        promotion_id: str,
        rollback_reason_code: str,
    ) -> QualityPromotionApprovalRequest:
        promotion = self.repository.get_promotion(promotion_id)
        active = self.repository.get_active(promotion.project_key, promotion.candidate_class)
        if promotion.status != "Active" or active is None or active.promotion_id != promotion_id:
            raise ValueError("QUALITY_PROMOTION_ROLLBACK_NOT_ACTIVE")
        if rollback_reason_code not in ROLLBACK_REASON_CODES:
            raise ValueError("QUALITY_PROMOTION_ROLLBACK_REASON_FORBIDDEN")
        return self.repository.create_rollback_request(promotion, rollback_reason_code)

    def get_rollback_request(self, promotion_id: str) -> QualityPromotionApprovalRequest:
        request = self.repository.get_approval_request(promotion_id, "PromotionRollback")
        return self.repository.expire_request_if_needed(request.approval_request_id)

    def decide_rollback(
        self,
        promotion_id: str,
        *,
        decision: str,
        request_digest: str,
        idempotency_key: str,
    ) -> QualityPromotion:
        return self._decide(
            promotion_id=promotion_id,
            approval_kind="PromotionRollback",
            decision=decision,
            request_digest=request_digest,
            idempotency_key=idempotency_key,
        )

    def reconcile(self, promotion_id: str) -> QualityPromotion:
        promotion = self.repository.get_promotion(promotion_id)
        active_count = self.repository.database.scalar(
            "SELECT COUNT(*) FROM quality_promotions WHERE slot_key=? AND status='Active'",
            (promotion.slot_key,),
        )
        if active_count not in (0, 1):
            raise ValueError("QUALITY_PROMOTION_ACTIVE_SLOT_CONFLICT")
        return promotion

    def history(self, promotion_id: str) -> QualityPromotionHistory:
        return self.repository.history(promotion_id)
