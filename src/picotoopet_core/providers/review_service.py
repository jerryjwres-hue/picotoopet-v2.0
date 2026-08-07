"""Phase 10D-B Provider Return 人工审阅与落地候选服务。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

from picotoopet_core.db.database import Database

from .artifact_store import ProviderArtifactError, ProviderReturnArtifactStore
from .review_models import (
    ProviderAdoptionCandidateRecord,
    ProviderAdoptionStatus,
    ProviderReviewDecision,
    ProviderReviewFilePreview,
    ProviderReviewRecord,
    ProviderReviewStatus,
)


class ProviderReviewError(RuntimeError):
    """固定 Review 错误码。"""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class ProviderReviewConflict(ProviderReviewError):
    """不可反转审阅事实发生冲突。"""


class ProviderReviewService:
    """Mac Core 唯一 Review/Adoption 事实源。"""

    def __init__(
        self,
        database: Database,
        artifact_store: ProviderReturnArtifactStore,
    ) -> None:
        self.database = database
        self.artifact_store = artifact_store

    def get_review(self, session_id: str) -> ProviderReviewRecord:
        """返回安全、只读、重新验签后的 Review 投影。"""

        session = self.database.fetchone(
            "SELECT session_id, status, return_id FROM provider_sessions WHERE session_id = ?",
            (session_id,),
        )
        if session is None:
            raise KeyError(session_id)
        if session["status"] != "ready_for_review" or not session["return_id"]:
            return ProviderReviewRecord(
                session_id=session_id,
                return_id=session["return_id"],
                review_status=ProviderReviewStatus.UNAVAILABLE,
            )

        return_id = str(session["return_id"])
        artifact_row = self.database.fetchone(
            "SELECT * FROM provider_return_artifacts WHERE session_id = ? AND return_id = ?",
            (session_id, return_id),
        )
        decision_row = self.database.fetchone(
            "SELECT decision FROM provider_review_decisions WHERE session_id = ?",
            (session_id,),
        )
        candidate_row = self.database.fetchone(
            "SELECT candidate_id FROM provider_adoption_candidates WHERE session_id = ?",
            (session_id,),
        )
        if artifact_row is None:
            return ProviderReviewRecord(
                session_id=session_id,
                return_id=return_id,
                review_status=ProviderReviewStatus.LEGACY_NO_ARTIFACT,
                decision=(
                    ProviderReviewDecision(decision_row["decision"])
                    if decision_row is not None
                    else None
                ),
                candidate_id=(
                    str(candidate_row["candidate_id"]) if candidate_row is not None else None
                ),
            )

        try:
            stored = self.artifact_store.load(
                return_id,
                expected_change_set_digest=str(artifact_row["change_set_digest"]),
            )
        except ProviderArtifactError as error:
            raise ProviderReviewError("ADOPTION_ARTIFACT_INVALID") from error
        if stored.review_diff_digest != artifact_row["review_diff_digest"]:
            raise ProviderReviewError("ADOPTION_ARTIFACT_INVALID")
        if stored.changed_file_count != artifact_row["changed_file_count"]:
            raise ProviderReviewError("ADOPTION_ARTIFACT_INVALID")
        if stored.payload_bytes != artifact_row["payload_bytes"]:
            raise ProviderReviewError("ADOPTION_ARTIFACT_INVALID")

        decision = (
            ProviderReviewDecision(decision_row["decision"])
            if decision_row is not None
            else None
        )
        if decision is ProviderReviewDecision.ACCEPTED:
            review_status = ProviderReviewStatus.ACCEPTED
        elif decision is ProviderReviewDecision.REJECTED:
            review_status = ProviderReviewStatus.REJECTED
        else:
            review_status = ProviderReviewStatus.REVIEWABLE
        files = [
            ProviderReviewFilePreview(
                operation=change.operation,
                path=change.path,
                size_bytes=change.size_bytes,
                base_sha256=change.base_sha256,
                result_sha256=change.result_sha256,
            )
            for change in stored.changes
        ]
        return ProviderReviewRecord(
            session_id=session_id,
            return_id=return_id,
            review_status=review_status,
            change_set_digest=stored.change_set_digest,
            review_diff_digest=stored.review_diff_digest,
            changed_file_count=stored.changed_file_count,
            payload_bytes=stored.payload_bytes,
            files=files,
            review_diff=stored.review_diff,
            decision=decision,
            candidate_id=(
                str(candidate_row["candidate_id"]) if candidate_row is not None else None
            ),
        )

    def accept(self, session_id: str, *, idempotency_key: str) -> ProviderReviewRecord:
        """幂等接受一次 Review，并创建唯一 queued Adoption Candidate。"""

        return self._decide(
            session_id,
            ProviderReviewDecision.ACCEPTED,
            idempotency_key=idempotency_key,
        )

    def reject(self, session_id: str, *, idempotency_key: str) -> ProviderReviewRecord:
        """幂等拒绝一次 Review；拒绝后不会创建候选。"""

        return self._decide(
            session_id,
            ProviderReviewDecision.REJECTED,
            idempotency_key=idempotency_key,
        )

    def list_candidates(self, *, limit: int = 100) -> list[ProviderAdoptionCandidateRecord]:
        """返回最近的落地候选安全事实。"""

        rows = self.database.fetchall(
            "SELECT * FROM provider_adoption_candidates ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        return [self._candidate_from_row(row) for row in rows]

    def get_candidate(self, candidate_id: str) -> ProviderAdoptionCandidateRecord:
        """按 ID 返回一个落地候选。"""

        row = self.database.fetchone(
            "SELECT * FROM provider_adoption_candidates WHERE candidate_id = ?",
            (candidate_id,),
        )
        if row is None:
            raise KeyError(candidate_id)
        return self._candidate_from_row(row)

    def _decide(
        self,
        session_id: str,
        decision: ProviderReviewDecision,
        *,
        idempotency_key: str,
    ) -> ProviderReviewRecord:
        replay = self.database.fetchone(
            "SELECT session_id, decision FROM provider_review_decisions "
            "WHERE idempotency_key = ?",
            (idempotency_key,),
        )
        if replay is not None:
            if replay["session_id"] != session_id or replay["decision"] != decision.value:
                raise ProviderReviewConflict("ADOPTION_IDEMPOTENCY_CONFLICT")
            return self.get_review(session_id)

        review = self.get_review(session_id)
        if review.review_status is ProviderReviewStatus.LEGACY_NO_ARTIFACT:
            raise ProviderReviewError("ADOPTION_ARTIFACT_MISSING")
        if review.review_status is ProviderReviewStatus.UNAVAILABLE:
            raise ProviderReviewError("ADOPTION_SESSION_NOT_REVIEWABLE")
        if review.decision is not None:
            raise ProviderReviewConflict("ADOPTION_ALREADY_DECIDED")
        if review.return_id is None or review.change_set_digest is None:
            raise ProviderReviewError("ADOPTION_ARTIFACT_MISSING")

        artifact_row = self.database.fetchone(
            "SELECT base_commit, changed_file_count, preview_json FROM provider_return_artifacts "
            "WHERE session_id = ? AND return_id = ?",
            (session_id, review.return_id),
        )
        if artifact_row is None:
            raise ProviderReviewError("ADOPTION_ARTIFACT_MISSING")
        now = datetime.now(UTC)
        decision_id = str(uuid4())
        candidate_id = str(uuid4()) if decision is ProviderReviewDecision.ACCEPTED else None
        decision_preview = json.dumps(
            {
                "decision_id": decision_id,
                "session_id": session_id,
                "return_id": review.return_id,
                "decision": decision.value,
                "change_set_digest": review.change_set_digest,
                "created_at": now.isoformat(),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        try:
            with self.database.transaction() as connection:
                existing = connection.execute(
                    "SELECT decision FROM provider_review_decisions WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
                if existing is not None:
                    raise ProviderReviewConflict("ADOPTION_ALREADY_DECIDED")
                connection.execute(
                    "INSERT INTO provider_review_decisions ("
                    "decision_id, session_id, return_id, decision, change_set_digest, "
                    "idempotency_key, created_at, preview_json"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        decision_id,
                        session_id,
                        review.return_id,
                        decision.value,
                        review.change_set_digest,
                        idempotency_key,
                        now.isoformat(),
                        decision_preview,
                    ),
                )
                if candidate_id is not None:
                    candidate_preview = json.dumps(
                        {
                            "candidate_id": candidate_id,
                            "session_id": session_id,
                            "return_id": review.return_id,
                            "status": ProviderAdoptionStatus.QUEUED.value,
                            "base_commit": artifact_row["base_commit"],
                            "change_set_digest": review.change_set_digest,
                            "changed_file_count": artifact_row["changed_file_count"],
                            "validation_checks": [],
                            "failure_code": None,
                            "created_at": now.isoformat(),
                            "updated_at": now.isoformat(),
                            "finished_at": None,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    connection.execute(
                        "INSERT INTO provider_adoption_candidates ("
                        "candidate_id, session_id, return_id, status, base_commit, "
                        "change_set_digest, changed_file_count, validation_json, failure_code, "
                        "idempotency_key, created_at, updated_at, finished_at, preview_json"
                        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, NULL, ?)",
                        (
                            candidate_id,
                            session_id,
                            review.return_id,
                            ProviderAdoptionStatus.QUEUED.value,
                            artifact_row["base_commit"],
                            review.change_set_digest,
                            artifact_row["changed_file_count"],
                            "[]",
                            f"adoption-candidate:{session_id}",
                            now.isoformat(),
                            now.isoformat(),
                            candidate_preview,
                        ),
                    )
        except ProviderReviewError:
            raise
        return self.get_review(session_id)

    @staticmethod
    def _candidate_from_row(row: object) -> ProviderAdoptionCandidateRecord:
        validation = json.loads(row["validation_json"])
        return ProviderAdoptionCandidateRecord(
            candidate_id=row["candidate_id"],
            session_id=row["session_id"],
            return_id=row["return_id"],
            status=ProviderAdoptionStatus(row["status"]),
            base_commit=row["base_commit"],
            change_set_digest=row["change_set_digest"],
            changed_file_count=row["changed_file_count"],
            validation_checks=validation,
            failure_code=row["failure_code"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            finished_at=(
                datetime.fromisoformat(row["finished_at"]) if row["finished_at"] else None
            ),
        )
