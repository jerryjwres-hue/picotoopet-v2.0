"""Phase 10D-B 已接受 Return 的确定性本地重放与静态验证。"""

from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from picotoopet_core.worker.codex_worktree import (
    CodexWorktree,
    CodexWorktreeError,
    CodexWorktreeManager,
)

from .artifact_store import ProviderArtifactError, ProviderReturnArtifactStore


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

    def _apply_one(self, worktree: CodexWorktree, return_id: str, change: object) -> None:
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
        expected_changes: tuple[object, ...],
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
