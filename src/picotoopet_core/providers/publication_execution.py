"""Phase 10E 已批准 Publication Candidate 的固定 Worker 执行。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from picotoopet_core.db.database import Database
from picotoopet_core.domain.enums import ApprovalStatus
from picotoopet_core.domain.models import TaskCreate, TaskRecord
from picotoopet_core.queue.diagnostic_repository import DiagnosticQueueRepository
from picotoopet_core.worker.handlers import HandlerResult

from .github_readiness import GitHubReadinessProbe
from .publication_git import PublicationGitError, PublicationGitPublisher
from .publication_github import PublicationGitHubClient, PublicationGitHubError
from .publication_models import ProviderPublicationStatus
from .publication_service import ProviderPublicationService


class PublicationExecutionError(RuntimeError):
    """固定、安全的 Publication Worker 失败。"""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class PublicationTaskPayload(BaseModel):
    """只由 Mac Core 生成的严格 publication payload。"""

    model_config = ConfigDict(extra="forbid")

    publication_candidate_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    commit_candidate_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    session_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    handoff_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    repo_url: str
    repository_slug: str
    base_ref: str
    base_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    change_set_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    remote_ref: str
    remote_branch: str
    pr_title_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    pr_body_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class ProviderPublicationExecutionCoordinator:
    """把批准后的 Publication Candidate 映射到固定外部发布任务。"""

    TASK_TYPE = "provider.publish.pr-create-v1"

    def __init__(
        self,
        *,
        database: Database,
        queue: DiagnosticQueueRepository,
        repository: Path,
        github_cli_executable: Path,
    ) -> None:
        self.database = database
        self.queue = queue
        self.publisher = PublicationGitPublisher(repository)
        self.github_readiness = GitHubReadinessProbe(github_cli_executable)
        self.github = PublicationGitHubClient(github_cli_executable)

    def enqueue_pending(self) -> None:
        """只为已明确批准的 Publication Candidate 幂等排入一个固定任务。"""

        rows = self.database.fetchall(
            "SELECT p.*, a.status AS approval_status FROM provider_publication_candidates p "
            "JOIN approvals a ON a.approval_id = p.approval_id "
            "WHERE p.status IN (?, ?) ORDER BY p.created_at LIMIT 20",
            (
                ProviderPublicationStatus.WAITING_APPROVAL.value,
                ProviderPublicationStatus.QUEUED.value,
            ),
        )
        for row in rows:
            approval_status = row["approval_status"]
            if approval_status == ApprovalStatus.REJECTED.value:
                self._finish_without_execution(
                    row["publication_candidate_id"],
                    ProviderPublicationStatus.REJECTED,
                    "PUBLICATION_APPROVAL_REJECTED",
                )
                continue
            if approval_status == ApprovalStatus.EXPIRED.value:
                self._finish_without_execution(
                    row["publication_candidate_id"],
                    ProviderPublicationStatus.CANCELLED,
                    "PUBLICATION_APPROVAL_EXPIRED",
                )
                continue
            if approval_status != ApprovalStatus.APPROVED.value:
                continue
            payload = self._payload_from_row(row)
            self.queue.create(
                TaskCreate(
                    task_type=self.TASK_TYPE,
                    payload=payload.model_dump(mode="json"),
                    priority=42,
                    resource_tag="provider-publication",
                    idempotency_key=f"publication-task:{row['publication_candidate_id']}",
                    dedupe_key=f"provider-publication:{row['commit_candidate_id']}",
                    max_attempts=1,
                    timeout_seconds=300,
                )
            )
            if row["status"] != ProviderPublicationStatus.QUEUED.value:
                self._set_status(
                    row["publication_candidate_id"],
                    ProviderPublicationStatus.QUEUED,
                )

    def handler(self, task: TaskRecord) -> HandlerResult:
        """执行固定 publication 并只在独立核验后进入 `pr_ready`。"""

        payload = PublicationTaskPayload.model_validate(task.payload)
        row = self.database.fetchone(
            "SELECT * FROM provider_publication_candidates WHERE publication_candidate_id = ?",
            (payload.publication_candidate_id,),
        )
        if row is None:
            raise KeyError(payload.publication_candidate_id)
        approval = self.database.fetchone(
            "SELECT status, scope_json FROM approvals WHERE approval_id = ?",
            (row["approval_id"],),
        )
        if approval is None or approval["status"] != ApprovalStatus.APPROVED.value:
            raise PublicationExecutionError("PUBLICATION_APPROVAL_REJECTED")
        self._validate_payload_and_scope(row, payload, approval["scope_json"])
        if row["status"] == ProviderPublicationStatus.PR_READY.value:
            return HandlerResult(
                summary={
                    "publication_candidate_id": payload.publication_candidate_id,
                    "status": ProviderPublicationStatus.PR_READY.value,
                    "pr_number": row["pr_number"],
                }
            )

        try:
            self._set_status(payload.publication_candidate_id, ProviderPublicationStatus.PREFLIGHT)
            if not self.github_readiness.ready():
                raise PublicationExecutionError("PUBLICATION_AUTH_UNAVAILABLE")
            self.publisher.verify_base(payload.repo_url, payload.base_ref, payload.base_commit)

            self._set_status(payload.publication_candidate_id, ProviderPublicationStatus.PUSHING)
            git_checks = self.publisher.ensure_remote_ref(
                payload.repo_url,
                payload.remote_ref,
                payload.commit_sha,
            )
            self._set_status(
                payload.publication_candidate_id,
                ProviderPublicationStatus.VERIFYING_REMOTE,
            )
            if self.publisher.read_remote_ref(payload.repo_url, payload.remote_ref) != payload.commit_sha:
                raise PublicationExecutionError("PUBLICATION_REMOTE_VERIFY_FAILED")
            self._set_status(payload.publication_candidate_id, ProviderPublicationStatus.REMOTE_READY)

            title = ProviderPublicationService.pr_title(
                payload.publication_candidate_id,
                payload.commit_sha,
            )
            body_facts = {
                "publication_candidate_id": payload.publication_candidate_id,
                "commit_candidate_id": payload.commit_candidate_id,
                "session_id": payload.session_id,
                "handoff_id": payload.handoff_id,
                "base_ref": payload.base_ref,
                "base_commit": payload.base_commit,
                "commit_sha": payload.commit_sha,
                "change_set_digest": payload.change_set_digest,
            }
            body = ProviderPublicationService.pr_body(**body_facts)
            self._validate_text_digests(payload, title, body, body_facts)

            self._set_status(payload.publication_candidate_id, ProviderPublicationStatus.CREATING_PR)
            pr = self.github.ensure_draft_pr(
                repository_slug=payload.repository_slug,
                base_ref=payload.base_ref,
                head_branch=payload.remote_branch,
                commit_sha=payload.commit_sha,
                title=title,
                body=body,
            )
            self._set_status(payload.publication_candidate_id, ProviderPublicationStatus.VERIFYING_PR)
            checks = ["approval_scope", "base_exact", *git_checks, *pr.validation_checks]
            self._finish_ready(
                payload.publication_candidate_id,
                pr_number=pr.number,
                pr_url=pr.url,
                pr_head_sha=pr.head_sha,
                validation_checks=checks,
            )
            return HandlerResult(
                summary={
                    "publication_candidate_id": payload.publication_candidate_id,
                    "status": ProviderPublicationStatus.PR_READY.value,
                    "pr_number": pr.number,
                    "pr_url": pr.url,
                    "commit_sha": pr.head_sha,
                }
            )
        except PublicationExecutionError as error:
            self._finish_failure(payload.publication_candidate_id, error.code)
            raise
        except PublicationGitError as error:
            self._finish_failure(payload.publication_candidate_id, error.code)
            raise PublicationExecutionError(error.code) from error
        except PublicationGitHubError as error:
            self._finish_failure(payload.publication_candidate_id, error.code)
            raise PublicationExecutionError(error.code) from error

    @staticmethod
    def _payload_from_row(row: object) -> PublicationTaskPayload:
        return PublicationTaskPayload(
            publication_candidate_id=row["publication_candidate_id"],
            commit_candidate_id=row["commit_candidate_id"],
            session_id=row["session_id"],
            handoff_id=row["handoff_id"],
            repo_url=row["repo_url"],
            repository_slug=row["repository_slug"],
            base_ref=row["base_ref"],
            base_commit=row["base_commit"],
            commit_sha=row["commit_sha"],
            change_set_digest=row["change_set_digest"],
            remote_ref=row["remote_ref"],
            remote_branch=row["remote_branch"],
            pr_title_digest=row["pr_title_digest"],
            pr_body_digest=row["pr_body_digest"],
        )

    def _validate_payload_and_scope(
        self,
        row: object,
        payload: PublicationTaskPayload,
        scope_json: str,
    ) -> None:
        fields = (
            "commit_candidate_id",
            "session_id",
            "handoff_id",
            "repo_url",
            "repository_slug",
            "base_ref",
            "base_commit",
            "commit_sha",
            "change_set_digest",
            "remote_ref",
            "remote_branch",
            "pr_title_digest",
            "pr_body_digest",
        )
        if any(str(row[field]) != str(getattr(payload, field)) for field in fields):
            raise PublicationExecutionError("PUBLICATION_PROVENANCE_INVALID")
        expected = {
            "action": ProviderPublicationService.APPROVAL_TYPE,
            "publication_candidate_id": payload.publication_candidate_id,
            "commit_candidate_id": payload.commit_candidate_id,
            "session_id": payload.session_id,
            "handoff_id": payload.handoff_id,
            "commit_sha": payload.commit_sha,
            "base_commit": payload.base_commit,
            "change_set_digest": payload.change_set_digest,
            "repo_url": payload.repo_url,
            "repository_slug": payload.repository_slug,
            "base_ref": payload.base_ref,
            "remote_ref": payload.remote_ref,
            "pr_title_digest": payload.pr_title_digest,
            "pr_body_digest": payload.pr_body_digest,
            "draft": True,
        }
        try:
            scope = json.loads(scope_json)
        except json.JSONDecodeError as error:
            raise PublicationExecutionError("PUBLICATION_APPROVAL_SCOPE_MISMATCH") from error
        if scope != expected:
            raise PublicationExecutionError("PUBLICATION_APPROVAL_SCOPE_MISMATCH")

    @staticmethod
    def _validate_text_digests(
        payload: PublicationTaskPayload,
        title: str,
        body: str,
        body_facts: dict[str, str],
    ) -> None:
        if (
            ProviderPublicationService.pr_title_digest(
                payload.publication_candidate_id,
                payload.commit_sha,
            )
            != payload.pr_title_digest
            or ProviderPublicationService.pr_body_digest(**body_facts) != payload.pr_body_digest
        ):
            raise PublicationExecutionError("PUBLICATION_APPROVAL_SCOPE_MISMATCH")
        if not title or not body:
            raise PublicationExecutionError("PUBLICATION_APPROVAL_SCOPE_MISMATCH")

    def _set_status(self, publication_candidate_id: str, status: ProviderPublicationStatus) -> None:
        self.database.execute(
            "UPDATE provider_publication_candidates SET status = ?, updated_at = ? "
            "WHERE publication_candidate_id = ?",
            (status.value, datetime.now(UTC).isoformat(), publication_candidate_id),
        )

    def _finish_ready(
        self,
        publication_candidate_id: str,
        *,
        pr_number: int,
        pr_url: str,
        pr_head_sha: str,
        validation_checks: list[str],
    ) -> None:
        now = datetime.now(UTC).isoformat()
        self.database.execute(
            "UPDATE provider_publication_candidates SET status = ?, pr_number = ?, pr_url = ?, "
            "pr_head_sha = ?, validation_json = ?, failure_code = NULL, updated_at = ?, "
            "finished_at = ? WHERE publication_candidate_id = ?",
            (
                ProviderPublicationStatus.PR_READY.value,
                pr_number,
                pr_url,
                pr_head_sha,
                json.dumps(validation_checks, ensure_ascii=False, separators=(",", ":")),
                now,
                now,
                publication_candidate_id,
            ),
        )

    def _finish_without_execution(
        self,
        publication_candidate_id: str,
        status: ProviderPublicationStatus,
        failure_code: str,
    ) -> None:
        now = datetime.now(UTC).isoformat()
        self.database.execute(
            "UPDATE provider_publication_candidates SET status = ?, failure_code = ?, updated_at = ?, "
            "finished_at = ? WHERE publication_candidate_id = ?",
            (status.value, failure_code, now, now, publication_candidate_id),
        )

    def _finish_failure(self, publication_candidate_id: str, code: str) -> None:
        status = {
            "PUBLICATION_BASE_MOVED": ProviderPublicationStatus.BASE_MOVED,
            "PUBLICATION_REMOTE_REF_CONFLICT": ProviderPublicationStatus.REMOTE_REF_CONFLICT,
            "PUBLICATION_AUTH_UNAVAILABLE": ProviderPublicationStatus.AUTH_UNAVAILABLE,
            "PUBLICATION_GIT_CONFIG_POLICY": ProviderPublicationStatus.POLICY_BLOCKED,
            "PUBLICATION_REMOTE_REF_POLICY": ProviderPublicationStatus.POLICY_BLOCKED,
            "PUBLICATION_PR_POLICY": ProviderPublicationStatus.POLICY_BLOCKED,
            "PUBLICATION_GIT_FAILED": ProviderPublicationStatus.PUSH_FAILED,
            "PUBLICATION_REMOTE_VERIFY_FAILED": ProviderPublicationStatus.PUSH_FAILED,
            "PUBLICATION_PR_CONFLICT": ProviderPublicationStatus.PR_CONFLICT,
            "PUBLICATION_PR_FAILED": ProviderPublicationStatus.PR_FAILED,
            "PUBLICATION_PR_RESPONSE_INVALID": ProviderPublicationStatus.PR_FAILED,
        }.get(code, ProviderPublicationStatus.FAILED)
        self._finish_without_execution(publication_candidate_id, status, code)
