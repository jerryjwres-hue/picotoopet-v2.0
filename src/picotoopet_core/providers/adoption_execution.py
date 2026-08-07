"""Phase 10D-B 已接受 Return 的确定性本地重放与静态验证。"""

from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from pydantic import BaseModel, ConfigDict, Field

from picotoopet_core.db.database import Database
from picotoopet_core.domain.models import TaskCreate, TaskRecord
from picotoopet_core.queue.diagnostic_repository import DiagnosticQueueRepository
from picotoopet_core.worker.codex_worktree import (
    CodexWorktree,
    CodexWorktreeError,
    CodexWorktreeManager,
)
from picotoopet_core.worker.handlers import HandlerResult

from .artifact_store import ProviderArtifactError, ProviderReturnArtifactStore
from .change_set import NormalizedChange
from .review_models import ProviderAdoptionStatus


class AdoptionExecutionError(RuntimeError):
    """固定、安全的 Adoption 重放失败。"""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class AdoptionApplyResult:
    """重放成功后的安全验证摘要。"""

    changed_file_count: int
    validation_checks: list[str]
    candidate_digest: str


class AdoptionTaskPayload(BaseModel):
    """只由 Mac Core 生成的固定 Adoption Worker payload。"""

    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    session_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    return_id: str = Field(min_length=1, max_length=80)
    base_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    change_set_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    allowed_write: tuple[str, ...] = (
        "src",
        "tests",
        "windows",
        "docs",
        "scripts",
        ".github",
    )


class AdoptionArtifactApplier:
    """从 exact base 在临时 worktree 中重放已验签的文本 Artifact。"""

    def __init__(
        self,
        *,
        repository: Path,
        worktree_root: Path,
        artifact_store: ProviderReturnArtifactStore,
    ) -> None:
        self.repository = repository.expanduser().resolve(strict=True)
        self.worktree_root = worktree_root.expanduser().resolve()
        self.artifact_store = artifact_store

    def apply(
        self,
        *,
        candidate_id: str,
        return_id: str,
        base_commit: str,
        change_set_digest: str,
        allowed_write: tuple[str, ...],
    ) -> AdoptionApplyResult:
        """验证 Artifact、重放、静态检查并始终清理 adoption worktree。"""

        try:
            stored = self.artifact_store.load(
                return_id,
                expected_change_set_digest=change_set_digest,
            )
        except ProviderArtifactError as error:
            raise AdoptionExecutionError(error.code) from error

        manager = CodexWorktreeManager(
            repository=self.repository,
            worktree_root=self.worktree_root,
        )
        worktree: CodexWorktree | None = None
        try:
            worktree = manager.create(
                session_id=candidate_id,
                base_commit=base_commit,
                allowed_write=allowed_write,
            )
            changed_paths = tuple(item.path for item in stored.changes)
            manager.validate_changed_paths(worktree, changed_paths)
            for change in stored.changes:
                self._apply_one(worktree, return_id, change)

            manager.validate_changed_paths(worktree, changed_paths)
            manager.git.diff_check(worktree.path)
            self._validate_result(manager, worktree, stored.changes)
            validation_checks = ["base_hashes", "result_hashes", "git_diff_check", "utf8"]
            if any(change.path.endswith(".py") for change in stored.changes):
                validation_checks.append("python_ast")
            digest = self._candidate_digest(
                base_commit=base_commit,
                change_set_digest=stored.change_set_digest,
                changed_paths=changed_paths,
                validation_checks=validation_checks,
            )
            return AdoptionApplyResult(
                changed_file_count=stored.changed_file_count,
                validation_checks=validation_checks,
                candidate_digest=digest,
            )
        except AdoptionExecutionError:
            raise
        except (CodexWorktreeError, OSError, UnicodeError, ValueError) as error:
            raise AdoptionExecutionError("ADOPTION_VALIDATION_FAILED") from error
        finally:
            if worktree is not None:
                try:
                    manager.cleanup(worktree)
                except CodexWorktreeError as error:
                    raise AdoptionExecutionError("ADOPTION_WORKTREE_CLEANUP_FAILED") from error

    def _apply_one(
        self,
        worktree: CodexWorktree,
        return_id: str,
        change: NormalizedChange,
    ) -> None:
        relative = PurePosixPath(change.path)
        target = worktree.path / Path(*relative.parts)
        if change.operation in {"modify", "delete"}:
            if not target.is_file() or target.is_symlink():
                raise AdoptionExecutionError("ADOPTION_BASE_MISMATCH")
            base_bytes = target.read_bytes()
            if hashlib.sha256(base_bytes).hexdigest() != change.base_sha256:
                raise AdoptionExecutionError("ADOPTION_BASE_MISMATCH")
        elif change.operation == "add" and target.exists():
            raise AdoptionExecutionError("ADOPTION_BASE_MISMATCH")

        if change.operation == "delete":
            target.unlink()
            return

        if not change.payload_name or not change.result_sha256:
            raise AdoptionExecutionError("ADOPTION_ARTIFACT_INVALID")
        payload_path = self.artifact_store.root / return_id / change.payload_name
        try:
            payload = payload_path.read_bytes()
        except OSError as error:
            raise AdoptionExecutionError("ADOPTION_ARTIFACT_INVALID") from error
        if len(payload) != change.size_bytes:
            raise AdoptionExecutionError("ADOPTION_ARTIFACT_INVALID")
        if hashlib.sha256(payload).hexdigest() != change.result_sha256:
            raise AdoptionExecutionError("ADOPTION_ARTIFACT_INVALID")
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as error:
            raise AdoptionExecutionError("ADOPTION_ARTIFACT_INVALID") from error
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.parent.is_symlink():
            raise AdoptionExecutionError("ADOPTION_PATH_POLICY")
        target.write_text(text, encoding="utf-8", newline="")
        if target.read_bytes() != payload:
            raise AdoptionExecutionError("ADOPTION_ARTIFACT_INVALID")
        if change.path.endswith(".py"):
            try:
                ast.parse(text, filename=change.path)
            except SyntaxError as error:
                raise AdoptionExecutionError("ADOPTION_VALIDATION_FAILED") from error

    @staticmethod
    def _validate_result(
        manager: CodexWorktreeManager,
        worktree: CodexWorktree,
        expected_changes: tuple[NormalizedChange, ...],
    ) -> None:
        captured = manager.capture_changes(worktree)
        by_path = {change.path: change for change in captured.changes}
        expected_paths = {change.path for change in expected_changes}
        if set(by_path) != expected_paths:
            raise AdoptionExecutionError("ADOPTION_ARTIFACT_INVALID")
        for expected in expected_changes:
            actual = by_path[expected.path]
            if actual.operation != expected.operation:
                raise AdoptionExecutionError("ADOPTION_ARTIFACT_INVALID")
            if actual.base_sha256 != expected.base_sha256:
                raise AdoptionExecutionError("ADOPTION_BASE_MISMATCH")
            if expected.operation == "delete":
                if actual.result_text is not None:
                    raise AdoptionExecutionError("ADOPTION_ARTIFACT_INVALID")
                continue
            result_bytes = (actual.result_text or "").encode("utf-8")
            if hashlib.sha256(result_bytes).hexdigest() != expected.result_sha256:
                raise AdoptionExecutionError("ADOPTION_ARTIFACT_INVALID")

    @staticmethod
    def _candidate_digest(
        *,
        base_commit: str,
        change_set_digest: str,
        changed_paths: tuple[str, ...],
        validation_checks: list[str],
    ) -> str:
        payload = json.dumps(
            {
                "base_commit": base_commit,
                "change_set_digest": change_set_digest,
                "changed_paths": list(changed_paths),
                "validation_checks": validation_checks,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


class AdoptionExecutionCoordinator:
    """把 accepted Review 的 queued Candidate 映射到固定 Worker 任务。"""

    TASK_TYPE = "provider.adoption.apply-v1"

    def __init__(
        self,
        *,
        database: Database,
        queue: DiagnosticQueueRepository,
        repository: Path,
        worktree_root: Path,
        artifact_store: ProviderReturnArtifactStore,
    ) -> None:
        self.database = database
        self.queue = queue
        self.applier = AdoptionArtifactApplier(
            repository=repository,
            worktree_root=worktree_root,
            artifact_store=artifact_store,
        )

    def enqueue_pending(self) -> None:
        """幂等为 queued Candidate 创建唯一 Worker 任务。"""

        rows = self.database.fetchall(
            "SELECT candidate_id, session_id, return_id, base_commit, change_set_digest "
            "FROM provider_adoption_candidates WHERE status = ? ORDER BY created_at LIMIT 20",
            (ProviderAdoptionStatus.QUEUED.value,),
        )
        for row in rows:
            payload = AdoptionTaskPayload(
                candidate_id=row["candidate_id"],
                session_id=row["session_id"],
                return_id=row["return_id"],
                base_commit=row["base_commit"],
                change_set_digest=row["change_set_digest"],
            )
            self.queue.create(
                TaskCreate(
                    task_type=self.TASK_TYPE,
                    payload=payload.model_dump(mode="json"),
                    priority=45,
                    resource_tag="provider-adoption",
                    idempotency_key=f"adoption-task:{row['candidate_id']}",
                    dedupe_key=f"provider-adoption:{row['session_id']}",
                    max_attempts=1,
                    timeout_seconds=300,
                )
            )

    def handler(self, task: TaskRecord) -> HandlerResult:
        """执行一个固定 Adoption Candidate，绝不产生 Git commit 或远端写入。"""

        payload = AdoptionTaskPayload.model_validate(task.payload)
        row = self.database.fetchone(
            "SELECT * FROM provider_adoption_candidates WHERE candidate_id = ?",
            (payload.candidate_id,),
        )
        if row is None:
            raise KeyError(payload.candidate_id)
        if row["session_id"] != payload.session_id or row["return_id"] != payload.return_id:
            raise AdoptionExecutionError("ADOPTION_ARTIFACT_INVALID")
        if row["base_commit"] != payload.base_commit:
            raise AdoptionExecutionError("ADOPTION_BASE_MISMATCH")
        if row["change_set_digest"] != payload.change_set_digest:
            raise AdoptionExecutionError("ADOPTION_ARTIFACT_INVALID")
        if row["status"] not in {
            ProviderAdoptionStatus.QUEUED.value,
            ProviderAdoptionStatus.STAGING.value,
            ProviderAdoptionStatus.APPLYING.value,
        }:
            raise AdoptionExecutionError("ADOPTION_ALREADY_CREATED")

        self._set_status(payload.candidate_id, ProviderAdoptionStatus.STAGING)
        self._set_status(payload.candidate_id, ProviderAdoptionStatus.APPLYING)
        try:
            result = self.applier.apply(
                candidate_id=payload.candidate_id,
                return_id=payload.return_id,
                base_commit=payload.base_commit,
                change_set_digest=payload.change_set_digest,
                allowed_write=payload.allowed_write,
            )
            self._set_status(payload.candidate_id, ProviderAdoptionStatus.VALIDATING)
            self._finish_ready(payload.candidate_id, result)
            return HandlerResult(
                summary={
                    "candidate_id": payload.candidate_id,
                    "status": ProviderAdoptionStatus.ADOPTION_READY.value,
                    "changed_file_count": result.changed_file_count,
                    "candidate_digest": result.candidate_digest,
                }
            )
        except AdoptionExecutionError as error:
            self._finish_failure(payload.candidate_id, error.code)
            raise

    def _set_status(self, candidate_id: str, status: ProviderAdoptionStatus) -> None:
        now = datetime.now(UTC).isoformat()
        self.database.execute(
            "UPDATE provider_adoption_candidates SET status = ?, updated_at = ? "
            "WHERE candidate_id = ?",
            (status.value, now, candidate_id),
        )

    def _finish_ready(self, candidate_id: str, result: AdoptionApplyResult) -> None:
        now = datetime.now(UTC).isoformat()
        validation_json = json.dumps(
            result.validation_checks,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        preview_json = json.dumps(
            {
                "candidate_id": candidate_id,
                "status": ProviderAdoptionStatus.ADOPTION_READY.value,
                "changed_file_count": result.changed_file_count,
                "validation_checks": result.validation_checks,
                "candidate_digest": result.candidate_digest,
                "updated_at": now,
                "finished_at": now,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        self.database.execute(
            "UPDATE provider_adoption_candidates SET status = ?, validation_json = ?, "
            "failure_code = NULL, updated_at = ?, finished_at = ?, preview_json = ? "
            "WHERE candidate_id = ?",
            (
                ProviderAdoptionStatus.ADOPTION_READY.value,
                validation_json,
                now,
                now,
                preview_json,
                candidate_id,
            ),
        )

    def _finish_failure(self, candidate_id: str, code: str) -> None:
        status = {
            "ADOPTION_ARTIFACT_INVALID": ProviderAdoptionStatus.ARTIFACT_INVALID,
            "ADOPTION_BASE_MISMATCH": ProviderAdoptionStatus.BASE_MISMATCH,
            "ADOPTION_PATH_POLICY": ProviderAdoptionStatus.POLICY_BLOCKED,
            "ADOPTION_WORKTREE_CLEANUP_FAILED": ProviderAdoptionStatus.FAILED,
        }.get(code, ProviderAdoptionStatus.VALIDATION_FAILED)
        now = datetime.now(UTC).isoformat()
        self.database.execute(
            "UPDATE provider_adoption_candidates SET status = ?, failure_code = ?, "
            "updated_at = ?, finished_at = ? WHERE candidate_id = ?",
            (status.value, code, now, now, candidate_id),
        )
