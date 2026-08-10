"""Phase 10D-C Commit Candidate 准备、审批绑定与安全读取服务。"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from picotoopet_core.db.database import Database
from picotoopet_core.domain.enums import ApprovalStatus
from picotoopet_core.handoffs.approvals import HandoffApprovalService

from .commit_models import ProviderCommitCandidateRecord, ProviderCommitStatus


class ProviderCommitError(RuntimeError):
    """固定、安全的 Commit Candidate 领域错误。"""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class ProviderCommitConflict(ProviderCommitError):
    """幂等键或唯一候选发生冲突。"""


class ProviderCommitService:
    """Mac Core 中 Commit Candidate 的唯一事实服务。"""

    APPROVAL_TYPE = "provider.commit.create-v1"
    APPROVAL_LIFETIME = timedelta(minutes=30)

    def __init__(self, database: Database, approvals: HandoffApprovalService) -> None:
        self.database = database
        self.approvals = approvals

    @staticmethod
    def message_preview(commit_candidate_id: str) -> str:
        """返回固定、无用户自由输入的 commit message。"""

        return f"PicotooPet adoption candidate {commit_candidate_id}"

    @classmethod
    def message_digest(cls, commit_candidate_id: str) -> str:
        """审批绑定固定 message，避免批准后漂移。"""

        return hashlib.sha256(cls.message_preview(commit_candidate_id).encode("utf-8")).hexdigest()

    @staticmethod
    def local_ref(commit_candidate_id: str) -> str:
        """Commit Candidate 只允许写 PicotooPet namespaced ref。"""

        return f"refs/picotoopet/commit-candidates/{commit_candidate_id}"

    def prepare(
        self,
        adoption_candidate_id: str,
        *,
        idempotency_key: str,
    ) -> ProviderCommitCandidateRecord:
        """为 adoption_ready 候选创建唯一、digest-bound 的人工审批。"""

        key = idempotency_key.strip()
        if not key:
            raise ProviderCommitError("COMMIT_IDEMPOTENCY_REQUIRED")

        replay = self.database.fetchone(
            "SELECT * FROM provider_commit_candidates WHERE idempotency_key = ?",
            (key,),
        )
        if replay is not None:
            if replay["adoption_candidate_id"] != adoption_candidate_id:
                raise ProviderCommitConflict("COMMIT_IDEMPOTENCY_CONFLICT")
            return self._record_from_row(replay)

        adoption = self.database.fetchone(
            "SELECT * FROM provider_adoption_candidates WHERE candidate_id = ?",
            (adoption_candidate_id,),
        )
        if adoption is None:
            raise KeyError(adoption_candidate_id)
        if adoption["status"] != "adoption_ready":
            raise ProviderCommitError("COMMIT_ADOPTION_NOT_READY")

        existing = self.database.fetchone(
            "SELECT * FROM provider_commit_candidates WHERE adoption_candidate_id = ?",
            (adoption_candidate_id,),
        )
        if existing is not None:
            raise ProviderCommitConflict("COMMIT_ALREADY_REQUESTED")

        now = datetime.now(UTC)
        commit_candidate_id = str(uuid4())
        local_ref = self.local_ref(commit_candidate_id)
        message_preview = self.message_preview(commit_candidate_id)
        message_digest = self.message_digest(commit_candidate_id)
        approval_scope = {
            "action": self.APPROVAL_TYPE,
            "commit_candidate_id": commit_candidate_id,
            "adoption_candidate_id": adoption_candidate_id,
            "session_id": adoption["session_id"],
            "return_id": adoption["return_id"],
            "base_commit": adoption["base_commit"],
            "change_set_digest": adoption["change_set_digest"],
            "local_ref": local_ref,
            "message_digest": message_digest,
        }
        preview = {
            "commit_candidate_id": commit_candidate_id,
            "adoption_candidate_id": adoption_candidate_id,
            "session_id": adoption["session_id"],
            "return_id": adoption["return_id"],
            "status": ProviderCommitStatus.WAITING_APPROVAL.value,
            "base_commit": adoption["base_commit"],
            "change_set_digest": adoption["change_set_digest"],
            "message_preview": message_preview,
            "message_digest": message_digest,
            "local_ref": local_ref,
            "tree_sha": None,
            "commit_sha": None,
            "validation_checks": [],
            "failure_code": None,
            "author_time_utc": None,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "finished_at": None,
        }
        try:
            with self.database.transaction() as connection:
                conflict = connection.execute(
                    "SELECT 1 FROM provider_commit_candidates WHERE adoption_candidate_id = ?",
                    (adoption_candidate_id,),
                ).fetchone()
                if conflict is not None:
                    raise ProviderCommitConflict("COMMIT_ALREADY_REQUESTED")
                grant = self.approvals.request_resource_in_transaction(
                    connection,
                    approval_type=self.APPROVAL_TYPE,
                    scope=approval_scope,
                    requested_by="provider-commit",
                    expires_at=now + self.APPROVAL_LIFETIME,
                    requested_at=now,
                )
                preview["approval_id"] = grant.approval_id
                connection.execute(
                    "INSERT INTO provider_commit_candidates ("
                    "commit_candidate_id, adoption_candidate_id, session_id, return_id, status, "
                    "base_commit, change_set_digest, tree_sha, commit_sha, local_ref, approval_id, "
                    "idempotency_key, validation_json, failure_code, author_time_utc, created_at, "
                    "updated_at, finished_at, preview_json"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?, ?, "
                    "NULL, NULL, ?, ?, NULL, ?)",
                    (
                        commit_candidate_id,
                        adoption_candidate_id,
                        adoption["session_id"],
                        adoption["return_id"],
                        ProviderCommitStatus.WAITING_APPROVAL.value,
                        adoption["base_commit"],
                        adoption["change_set_digest"],
                        local_ref,
                        grant.approval_id,
                        key,
                        "[]",
                        now.isoformat(),
                        now.isoformat(),
                        json.dumps(
                            preview,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                    ),
                )
        except ProviderCommitError:
            raise
        return self.get_candidate(commit_candidate_id)

    def list_candidates(self, *, limit: int = 100) -> list[ProviderCommitCandidateRecord]:
        """返回最近的 Commit Candidate 安全事实，并收敛审批终态。"""

        self._reconcile_terminal_approvals()
        bounded = max(1, min(limit, 100))
        rows = self.database.fetchall(
            "SELECT * FROM provider_commit_candidates ORDER BY created_at DESC LIMIT ?",
            (bounded,),
        )
        return [self._record_from_row(row) for row in rows]

    def get_candidate(self, commit_candidate_id: str) -> ProviderCommitCandidateRecord:
        """按 ID 返回 Commit Candidate 安全投影，并收敛审批终态。"""

        self._reconcile_terminal_approvals(commit_candidate_id=commit_candidate_id)
        row = self.database.fetchone(
            "SELECT * FROM provider_commit_candidates WHERE commit_candidate_id = ?",
            (commit_candidate_id,),
        )
        if row is None:
            raise KeyError(commit_candidate_id)
        return self._record_from_row(row)

    def _reconcile_terminal_approvals(self, *, commit_candidate_id: str | None = None) -> None:
        """拒绝/过期属于 Core 事实收敛，不依赖 Worker、Codex 或 Git 配置。"""

        query = (
            "SELECT c.commit_candidate_id, a.status AS approval_status "
            "FROM provider_commit_candidates c "
            "JOIN approvals a ON a.approval_id = c.approval_id "
            "WHERE c.status IN (?, ?)"
        )
        parameters: list[object] = [
            ProviderCommitStatus.WAITING_APPROVAL.value,
            ProviderCommitStatus.QUEUED.value,
        ]
        if commit_candidate_id is not None:
            query += " AND c.commit_candidate_id = ?"
            parameters.append(commit_candidate_id)
        rows = self.database.fetchall(query, tuple(parameters))
        for row in rows:
            if row["approval_status"] == ApprovalStatus.REJECTED.value:
                status = ProviderCommitStatus.REJECTED
                failure_code = "COMMIT_APPROVAL_REJECTED"
            elif row["approval_status"] == ApprovalStatus.EXPIRED.value:
                status = ProviderCommitStatus.CANCELLED
                failure_code = "COMMIT_APPROVAL_EXPIRED"
            else:
                continue
            now = datetime.now(UTC).isoformat()
            self.database.execute(
                "UPDATE provider_commit_candidates SET status = ?, failure_code = ?, "
                "updated_at = ?, finished_at = ? WHERE commit_candidate_id = ? "
                "AND status IN (?, ?)",
                (
                    status.value,
                    failure_code,
                    now,
                    now,
                    row["commit_candidate_id"],
                    ProviderCommitStatus.WAITING_APPROVAL.value,
                    ProviderCommitStatus.QUEUED.value,
                ),
            )

    def _record_from_row(self, row: object) -> ProviderCommitCandidateRecord:
        checks = json.loads(row["validation_json"])
        commit_candidate_id = str(row["commit_candidate_id"])
        return ProviderCommitCandidateRecord(
            commit_candidate_id=commit_candidate_id,
            adoption_candidate_id=row["adoption_candidate_id"],
            session_id=row["session_id"],
            return_id=row["return_id"],
            status=ProviderCommitStatus(row["status"]),
            base_commit=row["base_commit"],
            change_set_digest=row["change_set_digest"],
            approval_id=row["approval_id"],
            message_preview=self.message_preview(commit_candidate_id),
            message_digest=self.message_digest(commit_candidate_id),
            tree_sha=row["tree_sha"],
            commit_sha=row["commit_sha"],
            local_ref=row["local_ref"],
            validation_checks=checks,
            failure_code=row["failure_code"],
            author_time_utc=(
                datetime.fromisoformat(row["author_time_utc"])
                if row["author_time_utc"]
                else None
            ),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            finished_at=(
                datetime.fromisoformat(row["finished_at"])
                if row["finished_at"]
                else None
            ),
        )
