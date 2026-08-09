"""Phase 10E Publication Candidate 准备、审批绑定和安全读取服务。"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit
from uuid import uuid4

from picotoopet_core.db.database import Database
from picotoopet_core.handoffs.approvals import HandoffApprovalService

from .publication_models import (
    ProviderPublicationCandidateRecord,
    ProviderPublicationStatus,
)


class ProviderPublicationError(RuntimeError):
    """固定、安全的 Publication Candidate 领域错误。"""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class ProviderPublicationConflict(ProviderPublicationError):
    """幂等键或唯一 Publication Candidate 发生冲突。"""


class ProviderPublicationService:
    """Mac Core 中 Publication Candidate 的唯一事实服务。"""

    APPROVAL_TYPE = "provider.publish.pr-create-v1"
    APPROVAL_LIFETIME = timedelta(minutes=30)
    _REPOSITORY_SLUG = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")

    def __init__(self, database: Database, approvals: HandoffApprovalService) -> None:
        self.database = database
        self.approvals = approvals

    @staticmethod
    def remote_ref(publication_candidate_id: str) -> str:
        """Publication 只允许写固定 namespaced remote ref。"""

        return f"refs/heads/picotoopet/commit-candidates/{publication_candidate_id}"

    @staticmethod
    def remote_branch(publication_candidate_id: str) -> str:
        """返回对应 Draft PR 的固定 head branch 名。"""

        return f"picotoopet/commit-candidates/{publication_candidate_id}"

    @staticmethod
    def pr_title(publication_candidate_id: str, commit_sha: str) -> str:
        """生成不可由客户端编辑的确定性 Draft PR 标题。"""

        return f"PicotooPet publication candidate {publication_candidate_id} ({commit_sha[:12]})"

    @staticmethod
    def pr_body(
        *,
        publication_candidate_id: str,
        commit_candidate_id: str,
        session_id: str,
        handoff_id: str,
        base_ref: str,
        base_commit: str,
        commit_sha: str,
        change_set_digest: str,
    ) -> str:
        """生成只含安全 provenance 的确定性 Draft PR 正文。"""

        return (
            "Automated PicotooPet publication candidate. Draft only.\n\n"
            f"PicotooPet-Publication-Candidate: {publication_candidate_id}\n"
            f"PicotooPet-Commit-Candidate: {commit_candidate_id}\n"
            f"PicotooPet-Session: {session_id}\n"
            f"PicotooPet-Handoff: {handoff_id}\n"
            f"PicotooPet-Base-Ref: {base_ref}\n"
            f"PicotooPet-Base-Commit: {base_commit}\n"
            f"PicotooPet-Commit: {commit_sha}\n"
            f"PicotooPet-Change-Set-SHA256: {change_set_digest}\n\n"
            "This Draft PR is not CI-green, merge-ready, tag-ready, or release-ready.\n"
        )

    @classmethod
    def pr_title_digest(cls, publication_candidate_id: str, commit_sha: str) -> str:
        return hashlib.sha256(
            cls.pr_title(publication_candidate_id, commit_sha).encode("utf-8")
        ).hexdigest()

    @classmethod
    def pr_body_digest(cls, **facts: str) -> str:
        return hashlib.sha256(cls.pr_body(**facts).encode("utf-8")).hexdigest()

    def prepare(
        self,
        commit_candidate_id: str,
        *,
        idempotency_key: str,
    ) -> ProviderPublicationCandidateRecord:
        """从 `commit_ready` provenance 创建一个组合外部写审批。"""

        key = idempotency_key.strip()
        if not key:
            raise ProviderPublicationError("PUBLICATION_IDEMPOTENCY_REQUIRED")

        replay = self.database.fetchone(
            "SELECT * FROM provider_publication_candidates WHERE idempotency_key = ?",
            (key,),
        )
        if replay is not None:
            if replay["commit_candidate_id"] != commit_candidate_id:
                raise ProviderPublicationConflict("PUBLICATION_IDEMPOTENCY_CONFLICT")
            return self._record_from_row(replay)

        source = self.database.fetchone(
            "SELECT c.*, s.handoff_id, h.preview_json AS handoff_preview "
            "FROM provider_commit_candidates c "
            "JOIN provider_sessions s ON s.session_id = c.session_id "
            "JOIN handoffs h ON h.handoff_id = s.handoff_id "
            "WHERE c.commit_candidate_id = ?",
            (commit_candidate_id,),
        )
        if source is None:
            raise KeyError(commit_candidate_id)
        if source["status"] != "commit_ready" or not source["commit_sha"]:
            raise ProviderPublicationError("PUBLICATION_COMMIT_NOT_READY")

        existing = self.database.fetchone(
            "SELECT * FROM provider_publication_candidates WHERE commit_candidate_id = ?",
            (commit_candidate_id,),
        )
        if existing is not None:
            raise ProviderPublicationConflict("PUBLICATION_ALREADY_REQUESTED")

        try:
            handoff = json.loads(source["handoff_preview"])
            repo_url = str(handoff["repo_url"])
            base_ref = str(handoff["base_ref"])
            handoff_base_commit = str(handoff["base_commit"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ProviderPublicationError("PUBLICATION_PROVENANCE_INVALID") from error
        if handoff_base_commit != source["base_commit"]:
            raise ProviderPublicationError("PUBLICATION_PROVENANCE_INVALID")

        repository_slug = self._canonical_repository_slug(repo_url)
        self._validate_base_ref(base_ref)
        now = datetime.now(UTC)
        publication_id = str(uuid4())
        remote_ref = self.remote_ref(publication_id)
        remote_branch = self.remote_branch(publication_id)
        commit_sha = str(source["commit_sha"])
        body_facts = {
            "publication_candidate_id": publication_id,
            "commit_candidate_id": commit_candidate_id,
            "session_id": str(source["session_id"]),
            "handoff_id": str(source["handoff_id"]),
            "base_ref": base_ref,
            "base_commit": str(source["base_commit"]),
            "commit_sha": commit_sha,
            "change_set_digest": str(source["change_set_digest"]),
        }
        title_digest = self.pr_title_digest(publication_id, commit_sha)
        body_digest = self.pr_body_digest(**body_facts)
        approval_scope = {
            "action": self.APPROVAL_TYPE,
            "publication_candidate_id": publication_id,
            "commit_candidate_id": commit_candidate_id,
            "session_id": source["session_id"],
            "handoff_id": source["handoff_id"],
            "commit_sha": commit_sha,
            "base_commit": source["base_commit"],
            "change_set_digest": source["change_set_digest"],
            "repo_url": repo_url,
            "repository_slug": repository_slug,
            "base_ref": base_ref,
            "remote_ref": remote_ref,
            "pr_title_digest": title_digest,
            "pr_body_digest": body_digest,
            "draft": True,
        }
        preview = {
            "publication_candidate_id": publication_id,
            "commit_candidate_id": commit_candidate_id,
            "session_id": source["session_id"],
            "handoff_id": source["handoff_id"],
            "status": ProviderPublicationStatus.WAITING_APPROVAL.value,
            "repo_url": repo_url,
            "repository_slug": repository_slug,
            "base_ref": base_ref,
            "base_commit": source["base_commit"],
            "commit_sha": commit_sha,
            "change_set_digest": source["change_set_digest"],
            "remote_ref": remote_ref,
            "remote_branch": remote_branch,
            "approval_id": None,
            "pr_title_digest": title_digest,
            "pr_body_digest": body_digest,
            "pr_number": None,
            "pr_url": None,
            "pr_head_sha": None,
            "validation_checks": [],
            "failure_code": None,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "finished_at": None,
        }
        try:
            with self.database.transaction() as connection:
                if connection.execute(
                    "SELECT 1 FROM provider_publication_candidates WHERE commit_candidate_id = ?",
                    (commit_candidate_id,),
                ).fetchone() is not None:
                    raise ProviderPublicationConflict("PUBLICATION_ALREADY_REQUESTED")
                grant = self.approvals.request_resource_in_transaction(
                    connection,
                    approval_type=self.APPROVAL_TYPE,
                    scope=approval_scope,
                    requested_by="provider-publication",
                    expires_at=now + self.APPROVAL_LIFETIME,
                    requested_at=now,
                )
                preview["approval_id"] = grant.approval_id
                connection.execute(
                    "INSERT INTO provider_publication_candidates ("
                    "publication_candidate_id, commit_candidate_id, session_id, handoff_id, status, "
                    "repo_url, repository_slug, base_ref, base_commit, commit_sha, change_set_digest, "
                    "remote_ref, remote_branch, approval_id, idempotency_key, pr_title_digest, "
                    "pr_body_digest, pr_number, pr_url, pr_head_sha, validation_json, failure_code, "
                    "created_at, updated_at, finished_at, preview_json"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, "
                    "NULL, '[]', NULL, ?, ?, NULL, ?)",
                    (
                        publication_id,
                        commit_candidate_id,
                        source["session_id"],
                        source["handoff_id"],
                        ProviderPublicationStatus.WAITING_APPROVAL.value,
                        repo_url,
                        repository_slug,
                        base_ref,
                        source["base_commit"],
                        commit_sha,
                        source["change_set_digest"],
                        remote_ref,
                        remote_branch,
                        grant.approval_id,
                        key,
                        title_digest,
                        body_digest,
                        now.isoformat(),
                        now.isoformat(),
                        self._json(preview),
                    ),
                )
        except ProviderPublicationError:
            raise
        return self.get_candidate(publication_id)

    def list_candidates(self, *, limit: int = 100) -> list[ProviderPublicationCandidateRecord]:
        bounded = max(1, min(limit, 100))
        rows = self.database.fetchall(
            "SELECT * FROM provider_publication_candidates ORDER BY created_at DESC LIMIT ?",
            (bounded,),
        )
        return [self._record_from_row(row) for row in rows]

    def get_candidate(self, publication_candidate_id: str) -> ProviderPublicationCandidateRecord:
        row = self.database.fetchone(
            "SELECT * FROM provider_publication_candidates WHERE publication_candidate_id = ?",
            (publication_candidate_id,),
        )
        if row is None:
            raise KeyError(publication_candidate_id)
        return self._record_from_row(row)

    @classmethod
    def _canonical_repository_slug(cls, repo_url: str) -> str:
        split = urlsplit(repo_url)
        if (
            split.scheme != "https"
            or split.hostname != "github.com"
            or split.username is not None
            or split.password is not None
            or split.port is not None
            or split.query
            or split.fragment
        ):
            raise ProviderPublicationError("PUBLICATION_REPOSITORY_POLICY")
        path = split.path
        if path.endswith(".git"):
            path = path[:-4]
        if not path.startswith("/") or path.endswith("/"):
            raise ProviderPublicationError("PUBLICATION_REPOSITORY_POLICY")
        slug = path[1:]
        if not cls._REPOSITORY_SLUG.fullmatch(slug) or ".." in slug:
            raise ProviderPublicationError("PUBLICATION_REPOSITORY_POLICY")
        return slug

    @staticmethod
    def _validate_base_ref(base_ref: str) -> None:
        if (
            not base_ref
            or len(base_ref) > 200
            or base_ref.lower() in {"main", "master"}
            or base_ref.startswith("/")
            or base_ref.endswith("/")
            or ".." in base_ref
            or "//" in base_ref
            or any(ord(character) < 33 for character in base_ref)
        ):
            raise ProviderPublicationError("PUBLICATION_BASE_POLICY")

    @staticmethod
    def _json(value: object) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _record_from_row(row: object) -> ProviderPublicationCandidateRecord:
        return ProviderPublicationCandidateRecord(
            publication_candidate_id=row["publication_candidate_id"],
            commit_candidate_id=row["commit_candidate_id"],
            session_id=row["session_id"],
            handoff_id=row["handoff_id"],
            status=ProviderPublicationStatus(row["status"]),
            repo_url=row["repo_url"],
            repository_slug=row["repository_slug"],
            base_ref=row["base_ref"],
            base_commit=row["base_commit"],
            commit_sha=row["commit_sha"],
            change_set_digest=row["change_set_digest"],
            remote_ref=row["remote_ref"],
            remote_branch=row["remote_branch"],
            approval_id=row["approval_id"],
            pr_title_digest=row["pr_title_digest"],
            pr_body_digest=row["pr_body_digest"],
            pr_number=row["pr_number"],
            pr_url=row["pr_url"],
            pr_head_sha=row["pr_head_sha"],
            validation_checks=json.loads(row["validation_json"]),
            failure_code=row["failure_code"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            finished_at=(
                datetime.fromisoformat(row["finished_at"])
                if row["finished_at"]
                else None
            ),
        )
