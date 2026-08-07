"""Phase 10D-C 已批准 Adoption Candidate 的本地 Git Commit 创建。"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import subprocess
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from pydantic import BaseModel, ConfigDict, Field

from picotoopet_core.db.database import Database
from picotoopet_core.domain.enums import ApprovalStatus
from picotoopet_core.domain.models import TaskCreate, TaskRecord
from picotoopet_core.queue.diagnostic_repository import DiagnosticQueueRepository
from picotoopet_core.worker.handlers import HandlerResult

from .artifact_store import ProviderArtifactError, ProviderReturnArtifactStore
from .change_set import NormalizedChange
from .commit_models import ProviderCommitStatus
from .commit_service import ProviderCommitService


class CommitExecutionError(RuntimeError):
    """固定、安全的本地 Commit Candidate 执行失败。"""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class LocalCommitBuildResult:
    """成功创建 namespaced local ref 后的安全摘要。"""

    commit_sha: str
    tree_sha: str
    parent_sha: str
    local_ref: str
    author_time_utc: datetime
    validation_checks: list[str]


class CommitTaskPayload(BaseModel):
    """只由 Mac Core 生成的固定 Commit Worker payload。"""

    model_config = ConfigDict(extra="forbid")

    commit_candidate_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    adoption_candidate_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    session_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    return_id: str = Field(min_length=1, max_length=80)
    base_commit: str = Field(pattern=r"^[0-9a-f]{40,64}$")
    change_set_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class ProviderLocalCommitBuilder:
    """用 no-checkout worktree + Git plumbing 创建无 hook/filter 的本地提交。"""

    _ALLOWED_WRITE = ("src", "tests", "windows", "docs", "scripts", ".github")
    _FIXED_NAME = "PicotooPet Local Adoption"
    _FIXED_EMAIL = "picotoopet@localhost"

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

    def create(
        self,
        *,
        commit_candidate_id: str,
        adoption_candidate_id: str,
        session_id: str,
        return_id: str,
        base_commit: str,
        change_set_digest: str,
    ) -> LocalCommitBuildResult:
        """重新验签、重放、验证并创建固定 namespaced local ref。"""

        try:
            stored = self.artifact_store.load(
                return_id,
                expected_change_set_digest=change_set_digest,
            )
        except ProviderArtifactError as error:
            raise CommitExecutionError("COMMIT_ARTIFACT_INVALID") from error

        self._validate_repository_boundary()
        local_ref = ProviderCommitService.local_ref(commit_candidate_id)
        existing = self._existing_ref_result(
            local_ref=local_ref,
            commit_candidate_id=commit_candidate_id,
            adoption_candidate_id=adoption_candidate_id,
            session_id=session_id,
            return_id=return_id,
            base_commit=base_commit,
            change_set_digest=change_set_digest,
            changes=stored.changes,
        )
        if existing is not None:
            return existing

        self.worktree_root.mkdir(parents=True, exist_ok=True)
        staging = (self.worktree_root / commit_candidate_id).resolve()
        if staging.parent != self.worktree_root or staging.exists():
            raise CommitExecutionError("COMMIT_PATH_POLICY")

        index_path = Path(
            tempfile.mktemp(prefix=f"commit-index-{commit_candidate_id}-", dir=self.worktree_root)
        )
        worktree_added = False
        try:
            self._git_text(
                "worktree",
                "add",
                "--detach",
                "--no-checkout",
                str(staging),
                base_commit,
                timeout=60,
            )
            worktree_added = True
            modes: dict[str, str] = {}
            for change in stored.changes:
                self._validate_change_path(base_commit, change)
                modes[change.path] = self._replay_one(staging, return_id, base_commit, change)

            validation_checks = [
                "artifact_digest",
                "base_hashes",
                "result_hashes",
                "utf8",
                "no_checkout_filters",
            ]
            if any(change.path.endswith(".py") for change in stored.changes):
                validation_checks.append("python_ast")

            tree_sha = self._build_tree(
                index_path=index_path,
                base_commit=base_commit,
                return_id=return_id,
                changes=stored.changes,
                modes=modes,
            )
            self._validate_tree(base_commit, tree_sha, stored.changes)
            validation_checks.extend(["tree_diff_exact", "git_diff_check"])

            author_time = datetime.now(UTC)
            commit_sha = self._create_commit_object(
                tree_sha=tree_sha,
                base_commit=base_commit,
                commit_candidate_id=commit_candidate_id,
                adoption_candidate_id=adoption_candidate_id,
                session_id=session_id,
                return_id=return_id,
                change_set_digest=change_set_digest,
                author_time=author_time,
            )
            self._create_ref_cas(local_ref, commit_sha, base_commit)
            self._validate_commit(
                commit_sha=commit_sha,
                tree_sha=tree_sha,
                base_commit=base_commit,
                local_ref=local_ref,
                commit_candidate_id=commit_candidate_id,
                adoption_candidate_id=adoption_candidate_id,
                session_id=session_id,
                return_id=return_id,
                change_set_digest=change_set_digest,
            )
            validation_checks.extend(["commit_parent_exact", "local_ref_cas", "provenance"])
            return LocalCommitBuildResult(
                commit_sha=commit_sha,
                tree_sha=tree_sha,
                parent_sha=base_commit,
                local_ref=local_ref,
                author_time_utc=author_time,
                validation_checks=validation_checks,
            )
        except CommitExecutionError:
            raise
        except (OSError, UnicodeError, ValueError, subprocess.SubprocessError) as error:
            raise CommitExecutionError("COMMIT_OBJECT_FAILED") from error
        finally:
            with suppress(OSError):
                index_path.unlink(missing_ok=True)
            if worktree_added:
                try:
                    self._git_text(
                        "worktree",
                        "remove",
                        "--force",
                        str(staging),
                        timeout=60,
                    )
                except CommitExecutionError as error:
                    raise CommitExecutionError("COMMIT_WORKTREE_CLEANUP_FAILED") from error

    def _validate_repository_boundary(self) -> None:
        """不运行 clean/smudge filter 地验证主仓库边界与 raw-byte clean 状态。"""

        branch = self._git_text("symbolic-ref", "--short", "HEAD").strip()
        if branch.lower() in {"main", "master"}:
            raise CommitExecutionError("COMMIT_PATH_POLICY")

        head_tree = self._git_text("rev-parse", "HEAD^{tree}").strip()
        index_tree = self._git_text("write-tree").strip()
        if index_tree != head_tree:
            raise CommitExecutionError("COMMIT_PATH_POLICY")
        if self._git_bytes("ls-files", "--others", "--exclude-standard", "-z"):
            raise CommitExecutionError("COMMIT_PATH_POLICY")

        entries = self._git_bytes("ls-files", "-s", "-z")
        for raw_entry in entries.split(b"\0"):
            if not raw_entry:
                continue
            metadata, separator, raw_path = raw_entry.partition(b"\t")
            if not separator:
                raise CommitExecutionError("COMMIT_PATH_POLICY")
            try:
                mode, expected_blob, stage = metadata.decode("ascii").split()
                relative = Path(os.fsdecode(raw_path))
            except (UnicodeDecodeError, ValueError) as error:
                raise CommitExecutionError("COMMIT_PATH_POLICY") from error
            if stage != "0" or relative.is_absolute() or ".." in relative.parts:
                raise CommitExecutionError("COMMIT_PATH_POLICY")

            target = self.repository / relative
            if mode in {"100644", "100755"}:
                if not target.is_file() or target.is_symlink():
                    raise CommitExecutionError("COMMIT_PATH_POLICY")
                executable = bool(target.stat().st_mode & 0o111)
                if executable != (mode == "100755"):
                    raise CommitExecutionError("COMMIT_PATH_POLICY")
                raw_bytes = target.read_bytes()
            elif mode == "120000":
                if not target.is_symlink():
                    raise CommitExecutionError("COMMIT_PATH_POLICY")
                raw_bytes = os.fsencode(os.readlink(target))
            else:
                raise CommitExecutionError("COMMIT_PATH_POLICY")

            actual_blob = self._git_text(
                "hash-object",
                "--no-filters",
                "--stdin",
                input_bytes=raw_bytes,
            ).strip()
            if actual_blob != expected_blob:
                raise CommitExecutionError("COMMIT_PATH_POLICY")

    def _validate_change_path(self, base_commit: str, change: NormalizedChange) -> None:
        relative = PurePosixPath(change.path)
        if relative.is_absolute() or not relative.parts or ".." in relative.parts:
            raise CommitExecutionError("COMMIT_PATH_POLICY")
        if relative.parts[0] not in self._ALLOWED_WRITE:
            raise CommitExecutionError("COMMIT_PATH_POLICY")
        for count in range(1, len(relative.parts)):
            prefix = "/".join(relative.parts[:count])
            entry = self._ls_tree_entry(base_commit, prefix)
            if entry is not None and entry[0] != "040000":
                raise CommitExecutionError("COMMIT_PATH_POLICY")

    def _replay_one(
        self,
        staging: Path,
        return_id: str,
        base_commit: str,
        change: NormalizedChange,
    ) -> str:
        relative = PurePosixPath(change.path)
        target = staging / Path(*relative.parts)
        entry = self._ls_tree_entry(base_commit, change.path)
        if change.operation in {"modify", "delete"}:
            if entry is None or entry[0] not in {"100644", "100755"} or entry[1] != "blob":
                raise CommitExecutionError("COMMIT_BASE_MISMATCH")
            base_bytes = self._git_bytes("cat-file", "blob", f"{base_commit}:{change.path}")
            if hashlib.sha256(base_bytes).hexdigest() != change.base_sha256:
                raise CommitExecutionError("COMMIT_BASE_MISMATCH")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(base_bytes)
            if entry[0] == "100755":
                target.chmod(0o755)
        elif change.operation == "add":
            if entry is not None:
                raise CommitExecutionError("COMMIT_BASE_MISMATCH")
        else:
            raise CommitExecutionError("COMMIT_ARTIFACT_INVALID")

        if change.operation == "delete":
            target.unlink()
            return entry[0] if entry is not None else "100644"

        if not change.payload_name or not change.result_sha256:
            raise CommitExecutionError("COMMIT_ARTIFACT_INVALID")
        payload_path = self.artifact_store.root / return_id / change.payload_name
        try:
            payload = payload_path.read_bytes()
        except OSError as error:
            raise CommitExecutionError("COMMIT_ARTIFACT_INVALID") from error
        if len(payload) != change.size_bytes:
            raise CommitExecutionError("COMMIT_ARTIFACT_INVALID")
        if hashlib.sha256(payload).hexdigest() != change.result_sha256:
            raise CommitExecutionError("COMMIT_ARTIFACT_INVALID")
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as error:
            raise CommitExecutionError("COMMIT_ARTIFACT_INVALID") from error
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        if change.path.endswith(".py"):
            try:
                ast.parse(text, filename=change.path)
            except SyntaxError as error:
                raise CommitExecutionError("COMMIT_VALIDATION_FAILED") from error
        return (
            "100644"
            if change.operation == "add"
            else (entry[0] if entry is not None else "100644")
        )

    def _build_tree(
        self,
        *,
        index_path: Path,
        base_commit: str,
        return_id: str,
        changes: tuple[NormalizedChange, ...],
        modes: dict[str, str],
    ) -> str:
        env = {"GIT_INDEX_FILE": str(index_path)}
        self._git_text("read-tree", base_commit, env=env)
        for change in changes:
            if change.operation == "delete":
                self._git_text("update-index", "--force-remove", "--", change.path, env=env)
                continue
            assert change.payload_name is not None
            payload = (self.artifact_store.root / return_id / change.payload_name).read_bytes()
            blob_sha = self._git_text(
                "hash-object",
                "--no-filters",
                "-w",
                "--stdin",
                input_bytes=payload,
            ).strip()
            cacheinfo = f"{modes[change.path]},{blob_sha},{change.path}"
            self._git_text("update-index", "--add", "--cacheinfo", cacheinfo, env=env)
        return self._git_text("write-tree", env=env).strip()

    def _validate_tree(
        self,
        base_commit: str,
        tree_sha: str,
        changes: tuple[NormalizedChange, ...],
    ) -> None:
        self._git_text(
            "diff-tree",
            "--no-ext-diff",
            "--no-textconv",
            "--check",
            base_commit,
            tree_sha,
        )
        status_output = self._git_text(
            "diff-tree",
            "--no-commit-id",
            "--name-status",
            "-r",
            "--no-ext-diff",
            "--no-textconv",
            base_commit,
            tree_sha,
        )
        actual: dict[str, str] = {}
        for line in status_output.splitlines():
            parts = line.split("\t")
            if len(parts) != 2:
                raise CommitExecutionError("COMMIT_TREE_MISMATCH")
            actual[parts[1]] = parts[0][:1]
        expected_status = {"add": "A", "modify": "M", "delete": "D"}
        if actual != {change.path: expected_status[change.operation] for change in changes}:
            raise CommitExecutionError("COMMIT_TREE_MISMATCH")
        for change in changes:
            if change.operation == "delete":
                if self._ls_tree_entry(tree_sha, change.path) is not None:
                    raise CommitExecutionError("COMMIT_TREE_MISMATCH")
                continue
            result = self._git_bytes("cat-file", "blob", f"{tree_sha}:{change.path}")
            if hashlib.sha256(result).hexdigest() != change.result_sha256:
                raise CommitExecutionError("COMMIT_TREE_MISMATCH")

    def _create_commit_object(
        self,
        *,
        tree_sha: str,
        base_commit: str,
        commit_candidate_id: str,
        adoption_candidate_id: str,
        session_id: str,
        return_id: str,
        change_set_digest: str,
        author_time: datetime,
    ) -> str:
        message = self._message(
            commit_candidate_id,
            adoption_candidate_id,
            session_id,
            return_id,
            base_commit,
            change_set_digest,
        )
        timestamp = author_time.isoformat()
        env = {
            "GIT_AUTHOR_NAME": self._FIXED_NAME,
            "GIT_AUTHOR_EMAIL": self._FIXED_EMAIL,
            "GIT_AUTHOR_DATE": timestamp,
            "GIT_COMMITTER_NAME": self._FIXED_NAME,
            "GIT_COMMITTER_EMAIL": self._FIXED_EMAIL,
            "GIT_COMMITTER_DATE": timestamp,
        }
        return self._git_text(
            "commit-tree",
            tree_sha,
            "-p",
            base_commit,
            input_bytes=message.encode("utf-8"),
            env=env,
        ).strip()

    def _create_ref_cas(self, local_ref: str, commit_sha: str, base_commit: str) -> None:
        existing = self._git_optional_text("rev-parse", "--verify", local_ref)
        if existing is not None:
            if existing.strip() == commit_sha:
                return
            raise CommitExecutionError("COMMIT_REF_CONFLICT")
        zero = "0" * len(base_commit)
        try:
            self._git_text("update-ref", local_ref, commit_sha, zero)
        except CommitExecutionError as error:
            raise CommitExecutionError("COMMIT_REF_CONFLICT") from error

    def _existing_ref_result(
        self,
        *,
        local_ref: str,
        commit_candidate_id: str,
        adoption_candidate_id: str,
        session_id: str,
        return_id: str,
        base_commit: str,
        change_set_digest: str,
        changes: tuple[NormalizedChange, ...],
    ) -> LocalCommitBuildResult | None:
        existing = self._git_optional_text("rev-parse", "--verify", local_ref)
        if existing is None:
            return None
        commit_sha = existing.strip()
        body = self._git_text("cat-file", "-p", commit_sha)
        tree_sha, parent_sha = self._parse_commit_header(body)
        if parent_sha != base_commit:
            raise CommitExecutionError("COMMIT_REF_CONFLICT")
        expected_message = self._message(
            commit_candidate_id,
            adoption_candidate_id,
            session_id,
            return_id,
            base_commit,
            change_set_digest,
        ).strip()
        if body.split("\n\n", 1)[1].strip() != expected_message:
            raise CommitExecutionError("COMMIT_REF_CONFLICT")
        self._validate_tree(base_commit, tree_sha, changes)
        author_iso = self._git_text("show", "-s", "--format=%aI", commit_sha).strip()
        return LocalCommitBuildResult(
            commit_sha=commit_sha,
            tree_sha=tree_sha,
            parent_sha=parent_sha,
            local_ref=local_ref,
            author_time_utc=datetime.fromisoformat(author_iso),
            validation_checks=[
                "artifact_digest",
                "tree_diff_exact",
                "git_diff_check",
                "commit_parent_exact",
                "local_ref_cas",
                "provenance",
                "idempotent_ref_reuse",
            ],
        )

    def _validate_commit(
        self,
        *,
        commit_sha: str,
        tree_sha: str,
        base_commit: str,
        local_ref: str,
        commit_candidate_id: str,
        adoption_candidate_id: str,
        session_id: str,
        return_id: str,
        change_set_digest: str,
    ) -> None:
        if self._git_text("rev-parse", "--verify", local_ref).strip() != commit_sha:
            raise CommitExecutionError("COMMIT_REF_CONFLICT")
        body = self._git_text("cat-file", "-p", commit_sha)
        actual_tree, actual_parent = self._parse_commit_header(body)
        if actual_tree != tree_sha or actual_parent != base_commit:
            raise CommitExecutionError("COMMIT_TREE_MISMATCH")
        expected = self._message(
            commit_candidate_id,
            adoption_candidate_id,
            session_id,
            return_id,
            base_commit,
            change_set_digest,
        ).strip()
        if body.split("\n\n", 1)[1].strip() != expected:
            raise CommitExecutionError("COMMIT_TREE_MISMATCH")

    @staticmethod
    def _parse_commit_header(body: str) -> tuple[str, str]:
        header = body.split("\n\n", 1)[0].splitlines()
        tree = [line.split(" ", 1)[1] for line in header if line.startswith("tree ")]
        parents = [line.split(" ", 1)[1] for line in header if line.startswith("parent ")]
        if len(tree) != 1 or len(parents) != 1:
            raise CommitExecutionError("COMMIT_TREE_MISMATCH")
        return tree[0], parents[0]

    @staticmethod
    def _message(
        commit_candidate_id: str,
        adoption_candidate_id: str,
        session_id: str,
        return_id: str,
        base_commit: str,
        change_set_digest: str,
    ) -> str:
        return (
            f"PicotooPet adoption candidate {commit_candidate_id}\n\n"
            f"PicotooPet-Adoption-Candidate: {adoption_candidate_id}\n"
            f"PicotooPet-Return: {return_id}\n"
            f"PicotooPet-Session: {session_id}\n"
            f"PicotooPet-Base-Commit: {base_commit}\n"
            f"PicotooPet-Change-Set-SHA256: {change_set_digest}\n"
        )

    def _ls_tree_entry(self, object_sha: str, path: str) -> tuple[str, str, str] | None:
        output = self._git_text("ls-tree", object_sha, "--", path).strip()
        if not output:
            return None
        first = output.splitlines()[0]
        metadata, _separator, _name = first.partition("\t")
        parts = metadata.split()
        if len(parts) != 3:
            raise CommitExecutionError("COMMIT_TREE_MISMATCH")
        return parts[0], parts[1], parts[2]

    def _git_text(
        self,
        *arguments: str,
        timeout: int = 30,
        input_bytes: bytes | None = None,
        env: dict[str, str] | None = None,
    ) -> str:
        result = self._run_git(*arguments, timeout=timeout, input_bytes=input_bytes, env=env)
        try:
            return result.stdout.decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise CommitExecutionError("COMMIT_OBJECT_FAILED") from error

    def _git_bytes(self, *arguments: str, timeout: int = 30) -> bytes:
        return self._run_git(*arguments, timeout=timeout).stdout

    def _git_optional_text(self, *arguments: str) -> str | None:
        result = self._run_git(*arguments, timeout=30, allow_failure=True)
        if result.returncode != 0:
            return None
        return result.stdout.decode("utf-8", errors="strict")

    def _run_git(
        self,
        *arguments: str,
        timeout: int,
        input_bytes: bytes | None = None,
        env: dict[str, str] | None = None,
        allow_failure: bool = False,
    ) -> subprocess.CompletedProcess[bytes]:
        command = ["git", "-C", str(self.repository), *arguments]
        safe_env = {
            key: value
            for key in ("HOME", "PATH", "TMPDIR", "LANG", "LC_ALL")
            if (value := os.environ.get(key)) is not None
        }
        safe_env["GIT_TERMINAL_PROMPT"] = "0"
        if env:
            allowed = {
                "GIT_INDEX_FILE",
                "GIT_AUTHOR_NAME",
                "GIT_AUTHOR_EMAIL",
                "GIT_AUTHOR_DATE",
                "GIT_COMMITTER_NAME",
                "GIT_COMMITTER_EMAIL",
                "GIT_COMMITTER_DATE",
            }
            if not set(env).issubset(allowed):
                raise CommitExecutionError("COMMIT_PATH_POLICY")
            safe_env.update(env)
        result = subprocess.run(
            command,
            input=input_bytes,
            capture_output=True,
            env=safe_env,
            timeout=timeout,
            check=False,
            shell=False,
        )
        if result.returncode != 0 and not allow_failure:
            raise CommitExecutionError("COMMIT_OBJECT_FAILED")
        return result


class ProviderCommitExecutionCoordinator:
    """把批准后的 Commit Candidate 映射到固定 Worker 任务。"""

    TASK_TYPE = "provider.commit.create-v1"

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
        self.builder = ProviderLocalCommitBuilder(
            repository=repository,
            worktree_root=worktree_root,
            artifact_store=artifact_store,
        )

    def enqueue_pending(self) -> None:
        """只为已明确批准的 Commit Candidate 幂等排入一个固定任务。"""

        rows = self.database.fetchall(
            "SELECT c.*, a.status AS approval_status FROM provider_commit_candidates c "
            "JOIN approvals a ON a.approval_id = c.approval_id "
            "WHERE c.status IN (?, ?) ORDER BY c.created_at LIMIT 20",
            (ProviderCommitStatus.WAITING_APPROVAL.value, ProviderCommitStatus.QUEUED.value),
        )
        now = datetime.now(UTC)
        for row in rows:
            if row["approval_status"] == ApprovalStatus.REJECTED.value:
                self._finish_without_execution(
                    row["commit_candidate_id"],
                    ProviderCommitStatus.REJECTED,
                    "COMMIT_APPROVAL_REJECTED",
                )
                continue
            if row["approval_status"] == ApprovalStatus.EXPIRED.value:
                self._finish_without_execution(
                    row["commit_candidate_id"],
                    ProviderCommitStatus.CANCELLED,
                    "COMMIT_APPROVAL_EXPIRED",
                )
                continue
            if row["approval_status"] != ApprovalStatus.APPROVED.value:
                continue
            payload = CommitTaskPayload(
                commit_candidate_id=row["commit_candidate_id"],
                adoption_candidate_id=row["adoption_candidate_id"],
                session_id=row["session_id"],
                return_id=row["return_id"],
                base_commit=row["base_commit"],
                change_set_digest=row["change_set_digest"],
            )
            self.queue.create(
                TaskCreate(
                    task_type=self.TASK_TYPE,
                    payload=payload.model_dump(mode="json"),
                    priority=44,
                    resource_tag="provider-commit",
                    idempotency_key=f"commit-task:{row['commit_candidate_id']}",
                    dedupe_key=f"provider-commit:{row['adoption_candidate_id']}",
                    max_attempts=1,
                    timeout_seconds=300,
                )
            )
            if row["status"] != ProviderCommitStatus.QUEUED.value:
                self.database.execute(
                    "UPDATE provider_commit_candidates SET status = ?, updated_at = ? "
                    "WHERE commit_candidate_id = ?",
                    (
                        ProviderCommitStatus.QUEUED.value,
                        now.isoformat(),
                        row["commit_candidate_id"],
                    ),
                )

    def handler(self, task: TaskRecord) -> HandlerResult:
        """执行固定 Commit Candidate；成功只产生本机 object + namespaced ref。"""

        payload = CommitTaskPayload.model_validate(task.payload)
        row = self.database.fetchone(
            "SELECT * FROM provider_commit_candidates WHERE commit_candidate_id = ?",
            (payload.commit_candidate_id,),
        )
        if row is None:
            raise KeyError(payload.commit_candidate_id)
        approval = self.database.fetchone(
            "SELECT status, scope_json FROM approvals WHERE approval_id = ?",
            (row["approval_id"],),
        )
        if approval is None or approval["status"] != ApprovalStatus.APPROVED.value:
            raise CommitExecutionError("COMMIT_APPROVAL_REJECTED")
        self._validate_payload(row, payload, approval["scope_json"])
        if row["status"] == ProviderCommitStatus.COMMIT_READY.value:
            return HandlerResult(
                summary={
                    "commit_candidate_id": payload.commit_candidate_id,
                    "status": ProviderCommitStatus.COMMIT_READY.value,
                    "commit_sha": row["commit_sha"],
                }
            )
        if row["status"] not in {
            ProviderCommitStatus.QUEUED.value,
            ProviderCommitStatus.STAGING.value,
            ProviderCommitStatus.REPLAYING.value,
            ProviderCommitStatus.VALIDATING.value,
            ProviderCommitStatus.COMMITTING.value,
        }:
            raise CommitExecutionError("COMMIT_ADOPTION_NOT_READY")

        try:
            self._set_status(payload.commit_candidate_id, ProviderCommitStatus.STAGING)
            self._set_status(payload.commit_candidate_id, ProviderCommitStatus.REPLAYING)
            self._set_status(payload.commit_candidate_id, ProviderCommitStatus.VALIDATING)
            self._set_status(payload.commit_candidate_id, ProviderCommitStatus.COMMITTING)
            result = self.builder.create(**payload.model_dump())
            self._finish_ready(payload.commit_candidate_id, result)
            return HandlerResult(
                summary={
                    "commit_candidate_id": payload.commit_candidate_id,
                    "status": ProviderCommitStatus.COMMIT_READY.value,
                    "commit_sha": result.commit_sha,
                    "tree_sha": result.tree_sha,
                    "local_ref": result.local_ref,
                }
            )
        except CommitExecutionError as error:
            self._finish_failure(payload.commit_candidate_id, error.code)
            raise

    def _validate_payload(self, row: object, payload: CommitTaskPayload, scope_json: str) -> None:
        fields = (
            "adoption_candidate_id",
            "session_id",
            "return_id",
            "base_commit",
            "change_set_digest",
        )
        if any(str(row[field]) != str(getattr(payload, field)) for field in fields):
            raise CommitExecutionError("COMMIT_ARTIFACT_INVALID")
        scope = json.loads(scope_json)
        expected = {
            "action": ProviderCommitService.APPROVAL_TYPE,
            "commit_candidate_id": payload.commit_candidate_id,
            "adoption_candidate_id": payload.adoption_candidate_id,
            "session_id": payload.session_id,
            "return_id": payload.return_id,
            "base_commit": payload.base_commit,
            "change_set_digest": payload.change_set_digest,
            "local_ref": row["local_ref"],
            "message_digest": ProviderCommitService.message_digest(payload.commit_candidate_id),
        }
        if scope != expected:
            raise CommitExecutionError("COMMIT_APPROVAL_SCOPE_MISMATCH")

    def _set_status(self, commit_candidate_id: str, status: ProviderCommitStatus) -> None:
        self.database.execute(
            "UPDATE provider_commit_candidates SET status = ?, updated_at = ? "
            "WHERE commit_candidate_id = ?",
            (status.value, datetime.now(UTC).isoformat(), commit_candidate_id),
        )

    def _finish_ready(self, commit_candidate_id: str, result: LocalCommitBuildResult) -> None:
        now = datetime.now(UTC).isoformat()
        validation_json = json.dumps(
            result.validation_checks,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        preview = {
            "commit_candidate_id": commit_candidate_id,
            "status": ProviderCommitStatus.COMMIT_READY.value,
            "tree_sha": result.tree_sha,
            "commit_sha": result.commit_sha,
            "local_ref": result.local_ref,
            "validation_checks": result.validation_checks,
            "failure_code": None,
            "author_time_utc": result.author_time_utc.isoformat(),
            "updated_at": now,
            "finished_at": now,
        }
        self.database.execute(
            "UPDATE provider_commit_candidates SET status = ?, tree_sha = ?, commit_sha = ?, "
            "validation_json = ?, failure_code = NULL, author_time_utc = ?, updated_at = ?, "
            "finished_at = ?, preview_json = ? WHERE commit_candidate_id = ?",
            (
                ProviderCommitStatus.COMMIT_READY.value,
                result.tree_sha,
                result.commit_sha,
                validation_json,
                result.author_time_utc.isoformat(),
                now,
                now,
                json.dumps(preview, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                commit_candidate_id,
            ),
        )

    def _finish_without_execution(
        self,
        commit_candidate_id: str,
        status: ProviderCommitStatus,
        failure_code: str,
    ) -> None:
        now = datetime.now(UTC).isoformat()
        self.database.execute(
            "UPDATE provider_commit_candidates SET status = ?, failure_code = ?, updated_at = ?, "
            "finished_at = ? WHERE commit_candidate_id = ?",
            (status.value, failure_code, now, now, commit_candidate_id),
        )

    def _finish_failure(self, commit_candidate_id: str, code: str) -> None:
        status = {
            "COMMIT_ARTIFACT_INVALID": ProviderCommitStatus.ARTIFACT_INVALID,
            "COMMIT_BASE_MISMATCH": ProviderCommitStatus.BASE_MISMATCH,
            "COMMIT_PATH_POLICY": ProviderCommitStatus.POLICY_BLOCKED,
            "COMMIT_TREE_MISMATCH": ProviderCommitStatus.VALIDATION_FAILED,
            "COMMIT_VALIDATION_FAILED": ProviderCommitStatus.VALIDATION_FAILED,
            "COMMIT_REF_CONFLICT": ProviderCommitStatus.REF_CONFLICT,
            "COMMIT_WORKTREE_CLEANUP_FAILED": ProviderCommitStatus.FAILED,
        }.get(code, ProviderCommitStatus.COMMIT_FAILED)
        self._finish_without_execution(commit_candidate_id, status, code)
