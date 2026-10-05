"""Bounded coding-provider task queueing, isolated execution and immutable Return capture."""

from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Thread
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from picotoopet_core.domain.models import TaskCreate, TaskRecord
from picotoopet_core.queue.diagnostic_repository import DiagnosticQueueRepository
from picotoopet_core.returns.models import (
    ReturnEventSummary,
    ReturnRecord,
    ReturnStatus,
    ReturnValidationCheck,
)
from picotoopet_core.worker.claude_code_adapter import (
    ClaudeCodeAdapter,
    ClaudeCodeAdapterCancelled,
    ClaudeCodeAdapterError,
    ClaudeCodeAdapterProtocolError,
    ClaudeCodeAdapterTimeout,
)
from picotoopet_core.worker.codex_adapter import (
    CodexAdapter,
    CodexAdapterCancelled,
    CodexAdapterError,
    CodexAdapterProtocolError,
    CodexAdapterTimeout,
)
from picotoopet_core.worker.codex_worktree import (
    CapturedProviderChanges,
    CodexWorktreeError,
    CodexWorktreeManager,
)
from picotoopet_core.worker.handlers import HandlerResult

from .artifact_store import ProviderArtifactError, ProviderReturnArtifactStore
from .models import (
    ProviderName,
    ProviderReadinessStatus,
    ProviderSessionRecord,
    ProviderSessionStatus,
)
from .service import ProviderSessionService


class ProviderTaskPayload(BaseModel):
    """Fixed Worker payload generated only from Mac Core provider-session facts."""

    model_config = ConfigDict(extra="forbid")

    provider: ProviderName = "codex"
    session_id: str
    handoff_id: str
    request_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    package_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    base_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    objective: str = Field(min_length=1, max_length=1000)
    allowed_write: tuple[str, ...] = (
        "src",
        "tests",
        "windows",
        "docs",
        "scripts",
        ".github",
    )


@dataclass(frozen=True, slots=True)
class _ProviderRunSummary:
    """Adapter-neutral safe execution summary; it never contains model text."""

    turns_used: int
    elapsed_seconds: int
    provider_usage_unknown: bool
    events: tuple[dict[str, object], ...]


class ProviderExecutionCoordinator:
    """Map bounded provider Sessions onto one shared worktree/Return execution lane."""

    CODEX_TASK_TYPE = "provider.codex.handoff-v1"
    CLAUDE_CODE_TASK_TYPE = "provider.claude-code.handoff-v1"
    TASK_TYPE = CODEX_TASK_TYPE  # Backward-compatible constant used by existing installers/tests.
    TASK_TYPES = (CODEX_TASK_TYPE, CLAUDE_CODE_TASK_TYPE)

    def __init__(
        self,
        *,
        queue: DiagnosticQueueRepository,
        sessions: ProviderSessionService,
        repository: Path,
        worktree_root: Path,
        codex_executable: Path | None,
        claude_code_executable: Path | None = None,
        worker_id: str,
        artifact_store: ProviderReturnArtifactStore,
        readiness_by_provider: Callable[[ProviderName], ProviderReadinessStatus] | None = None,
    ) -> None:
        self.queue = queue
        self.sessions = sessions
        self.repository = repository
        self.worktree_root = worktree_root
        self.codex_executable = codex_executable
        self.claude_code_executable = claude_code_executable
        self.worker_id = worker_id
        self.artifact_store = artifact_store
        self._readiness_by_provider = readiness_by_provider or (
            lambda _provider: ProviderReadinessStatus.UNAVAILABLE
        )

    @property
    def configured_task_types(self) -> tuple[str, ...]:
        """Expose only task types backed by explicitly configured provider executables."""

        task_types: list[str] = []
        if self.codex_executable is not None:
            task_types.append(self.CODEX_TASK_TYPE)
        if self.claude_code_executable is not None:
            task_types.append(self.CLAUDE_CODE_TASK_TYPE)
        return tuple(task_types)

    @classmethod
    def task_type_for(cls, provider: ProviderName) -> str:
        if provider == "codex":
            return cls.CODEX_TASK_TYPE
        if provider == "claude_code":
            return cls.CLAUDE_CODE_TASK_TYPE
        raise ValueError("Unknown coding provider.")

    def enqueue_pending(self) -> None:
        """Create tasks only for explicitly configured and currently ready providers."""

        configured = frozenset(self.configured_task_types)
        if not configured:
            return
        rows = self.sessions.database.fetchall(
            "SELECT preview_json FROM provider_sessions WHERE status = ? "
            "ORDER BY created_at LIMIT 20",
            (ProviderSessionStatus.WAITING_PROVIDER_READY.value,),
        )
        for row in rows:
            session = ProviderSessionRecord.model_validate(json.loads(row["preview_json"]))
            task_type = self.task_type_for(session.provider)
            if task_type not in configured:
                continue
            if self._readiness_by_provider(session.provider) is not ProviderReadinessStatus.READY:
                continue
            handoff = self.sessions.handoffs.get(session.handoff_id)
            if handoff.provider != session.provider:
                self._fail(
                    session.session_id,
                    ProviderSessionStatus.STOPPED_BY_POLICY,
                    "PROVIDER_BINDING_MISMATCH",
                )
                continue
            payload = ProviderTaskPayload(
                provider=session.provider,
                session_id=session.session_id,
                handoff_id=handoff.handoff_id,
                request_digest=handoff.request_digest,
                package_digest=handoff.package_digest,
                base_commit=handoff.base_commit,
                objective=handoff.objective_summary,
            )
            self.queue.create(
                TaskCreate(
                    task_type=task_type,
                    payload=payload.model_dump(mode="json"),
                    priority=40,
                    resource_tag="provider",
                    idempotency_key=f"provider-task:{session.session_id}",
                    dedupe_key=f"provider-{session.provider}:{handoff.handoff_id}",
                    max_attempts=1,
                    timeout_seconds=900,
                )
            )

    def handler(self, task: TaskRecord) -> HandlerResult:
        """Execute one provider-bound Session and always clean its isolated worktree."""

        payload = ProviderTaskPayload.model_validate(task.payload)
        current = self.sessions.get_session(payload.session_id)
        expected_task_type = self.task_type_for(current.provider)
        handoff = self.sessions.handoffs.get(payload.handoff_id)
        if (
            payload.provider != current.provider
            or handoff.provider != current.provider
            or task.task_type != expected_task_type
            or expected_task_type not in self.configured_task_types
            or self._readiness_by_provider(current.provider) is not ProviderReadinessStatus.READY
        ):
            self._fail(
                payload.session_id,
                ProviderSessionStatus.STOPPED_BY_POLICY,
                "PROVIDER_BINDING_MISMATCH",
            )
            raise RuntimeError("Provider task/session/handoff/readiness binding mismatch.")
        if current.request_digest != payload.request_digest:
            raise RuntimeError("Provider request digest 不匹配。")
        if current.package_digest != payload.package_digest:
            raise RuntimeError("Provider package digest 不匹配。")

        manager = CodexWorktreeManager(
            repository=self.repository,
            worktree_root=self.worktree_root,
        )
        worktree = None
        cancel_event = Event()
        watcher_stop = Event()

        def watch_cancel() -> None:
            while not watcher_stop.wait(0.25):
                if self.queue.is_cancel_requested(task.task_id, worker_id=self.worker_id):
                    cancel_event.set()
                    return

        watcher = Thread(target=watch_cancel, daemon=True)
        watcher.start()
        try:
            self.sessions.transition(payload.session_id, ProviderSessionStatus.STAGING)
            worktree = manager.create(
                session_id=payload.session_id,
                base_commit=payload.base_commit,
                allowed_write=payload.allowed_write,
            )
            self.sessions.transition(payload.session_id, ProviderSessionStatus.RUNNING)
            prompt = self._build_prompt(payload)
            run = self._run_provider(
                payload.provider,
                prompt=prompt,
                worktree=worktree.path,
                cancel_event=cancel_event,
            )
            self.sessions.transition(
                payload.session_id,
                ProviderSessionStatus.RETURNING,
                turns_used=run.turns_used,
                elapsed_seconds=run.elapsed_seconds,
                provider_usage_unknown=run.provider_usage_unknown,
            )
            captured = manager.capture_changes(worktree)
            record = self._persist_return(payload, captured, run.events)
            self.sessions.transition(
                payload.session_id,
                ProviderSessionStatus.READY_FOR_REVIEW,
                turns_used=run.turns_used,
                elapsed_seconds=run.elapsed_seconds,
                changed_file_count=len(captured.changes),
                return_id=record.return_id,
                provider_usage_unknown=run.provider_usage_unknown,
                finished=True,
            )
            return HandlerResult(
                summary={
                    "session_id": payload.session_id,
                    "provider": payload.provider,
                    "return_id": record.return_id,
                    "changed_file_count": len(captured.changes),
                }
            )
        except (CodexAdapterCancelled, ClaudeCodeAdapterCancelled):
            self._fail(payload.session_id, ProviderSessionStatus.CANCELLED, "PROVIDER_CANCELLED")
            raise
        except (CodexAdapterTimeout, ClaudeCodeAdapterTimeout):
            self._fail(payload.session_id, ProviderSessionStatus.TIMED_OUT, "PROVIDER_TIMED_OUT")
            raise
        except (
            CodexWorktreeError,
            CodexAdapterProtocolError,
            ClaudeCodeAdapterProtocolError,
        ):
            self._fail(
                payload.session_id,
                ProviderSessionStatus.STOPPED_BY_POLICY,
                "PROVIDER_POLICY_STOP",
            )
            raise
        except (CodexAdapterError, ClaudeCodeAdapterError):
            self._fail(
                payload.session_id,
                ProviderSessionStatus.PROVIDER_FAILED,
                "PROVIDER_EXECUTION_FAILED",
            )
            raise
        finally:
            watcher_stop.set()
            watcher.join(timeout=2)
            if worktree is not None:
                manager.cleanup(worktree)

    def _run_provider(
        self,
        provider: ProviderName,
        *,
        prompt: str,
        worktree: Path,
        cancel_event: Event,
    ) -> _ProviderRunSummary:
        if provider == "codex":
            if self.codex_executable is None:
                raise CodexAdapterError("Codex executable is not configured.")
            run = CodexAdapter(self.codex_executable).run(
                prompt=prompt,
                worktree=worktree,
                cancel_event=cancel_event,
            )
            return _ProviderRunSummary(
                turns_used=run.turns_used,
                elapsed_seconds=run.elapsed_seconds,
                provider_usage_unknown=run.provider_usage_unknown,
                events=run.events,
            )
        if self.claude_code_executable is None:
            raise ClaudeCodeAdapterError("Claude Code executable is not configured.")
        run = ClaudeCodeAdapter(self.claude_code_executable).run(
            prompt=prompt,
            worktree=worktree,
            cancel_event=cancel_event,
        )
        return _ProviderRunSummary(
            turns_used=run.turns_used,
            elapsed_seconds=run.elapsed_seconds,
            provider_usage_unknown=run.provider_usage_unknown,
            events=({"type": f"claude_code.{run.subtype}"},),
        )

    def _persist_return(
        self,
        payload: ProviderTaskPayload,
        captured: CapturedProviderChanges,
        events: tuple[dict[str, object], ...],
    ) -> ReturnRecord:
        """Write immutable artifact first, then atomically register Return/review facts."""

        if len(captured.changes) > 5 or len(events) > 100:
            raise CodexWorktreeError("Provider Return 超过固定预算。")
        allowed = payload.allowed_write
        for change in captured.changes:
            path = change.path
            if not any(path == root or path.startswith(f"{root}/") for root in allowed):
                raise CodexWorktreeError("Provider Return 路径不在批准范围。")

        now = datetime.now(UTC)
        return_id = str(uuid4())
        try:
            stored = self.artifact_store.write(
                return_id=return_id,
                base_commit=payload.base_commit,
                changes=list(captured.changes),
                review_diff=captured.review_diff,
            )
        except ProviderArtifactError as exc:
            raise CodexWorktreeError(exc.code) from exc

        label = "Codex" if payload.provider == "codex" else "Claude Code"
        summaries = [
            ReturnEventSummary(
                sequence=index,
                event_type=str(event["type"]),
                summary=f"{label} 安全阶段事件。",
            )
            for index, event in enumerate(events, start=1)
        ]
        record = ReturnRecord(
            return_id=return_id,
            handoff_id=payload.handoff_id,
            status=ReturnStatus.CONTRACT_VALIDATED,
            provider=payload.provider,
            request_digest=payload.request_digest,
            package_digest=payload.package_digest,
            manifest_digest=stored.change_set_digest,
            changed_file_count=stored.changed_file_count,
            event_count=len(events),
            validation_checks=[
                ReturnValidationCheck(name="session_binding", passed=True),
                ReturnValidationCheck(name="digest_binding", passed=True),
                ReturnValidationCheck(name="allowed_paths", passed=True),
                ReturnValidationCheck(name="size_budget", passed=True),
                ReturnValidationCheck(name="hash_coverage", passed=True),
                ReturnValidationCheck(name="event_bounds", passed=True),
                ReturnValidationCheck(name="immutable_artifact", passed=True),
            ],
            event_summaries=summaries,
            created_at=now,
            updated_at=now,
            execution_notice=(
                f"{label} Return 已通过本地合同校验并生成只读落地 Artifact；未自动提交、"
                "推送、创建 PR、合并、标签或发布。"
            ),
        )
        preview = json.dumps(
            record.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        artifact_preview = json.dumps(
            {
                "return_id": return_id,
                "session_id": payload.session_id,
                "handoff_id": payload.handoff_id,
                "provider": payload.provider,
                "base_commit": payload.base_commit,
                "change_set_digest": stored.change_set_digest,
                "review_diff_digest": stored.review_diff_digest,
                "changed_file_count": stored.changed_file_count,
                "payload_bytes": stored.payload_bytes,
                "artifact_status": "reviewable",
                "files": [
                    {
                        "operation": item.operation,
                        "path": item.path,
                        "size_bytes": item.size_bytes,
                        "base_sha256": item.base_sha256,
                        "result_sha256": item.result_sha256,
                    }
                    for item in stored.changes
                ],
                "created_at": now.isoformat(),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        try:
            with self.sessions.database.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO returns (
                        return_id, handoff_id, status, provider, request_digest,
                        package_digest, manifest_digest, changed_file_count, event_count,
                        validation_checks_json, preview_json, quarantine_code,
                        idempotency_key, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?)
                    """,
                    (
                        return_id,
                        payload.handoff_id,
                        record.status.value,
                        payload.provider,
                        payload.request_digest,
                        payload.package_digest,
                        stored.change_set_digest,
                        stored.changed_file_count,
                        len(events),
                        json.dumps(
                            [item.model_dump(mode="json") for item in record.validation_checks],
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                        preview,
                        f"provider-return:{payload.session_id}",
                        now.isoformat(),
                        now.isoformat(),
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO provider_return_artifacts (
                        return_id, session_id, handoff_id, base_commit,
                        change_set_digest, review_diff_digest, changed_file_count,
                        payload_bytes, artifact_status, created_at, preview_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        return_id,
                        payload.session_id,
                        payload.handoff_id,
                        payload.base_commit,
                        stored.change_set_digest,
                        stored.review_diff_digest,
                        stored.changed_file_count,
                        stored.payload_bytes,
                        "reviewable",
                        now.isoformat(),
                        artifact_preview,
                    ),
                )
        except Exception:
            self.artifact_store.discard(return_id)
            raise
        return record

    def _fail(
        self,
        session_id: str,
        status: ProviderSessionStatus,
        failure_code: str,
    ) -> None:
        with suppress(Exception):
            self.sessions.transition(
                session_id,
                status,
                failure_code=failure_code,
                finished=True,
            )

    @staticmethod
    def _build_prompt(payload: ProviderTaskPayload) -> str:
        roots = ", ".join(payload.allowed_write)
        return (
            "Perform only this approved PicotooPet maintenance task:\n"
            f"{payload.objective}\n\n"
            f"Writable roots: {roots}. Maximum 5 changed files. Do not commit, push, "
            "create a pull request, merge, tag, release, install dependencies, use network "
            "tools, read credentials, or modify files outside the writable roots."
        )
