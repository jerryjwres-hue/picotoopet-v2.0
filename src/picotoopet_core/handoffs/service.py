"""Deterministic Handoff preparation, persistence, idempotency and approval sync."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from picotoopet_core.approvals.service import ApprovalRecord
from picotoopet_core.db.database import Database

from .approvals import HandoffApprovalService
from .models import HandoffPrepareRequest, HandoffRecord, HandoffStatus, HandoffTemplate


class HandoffError(RuntimeError):
    """Handoff preparation or state operation failed."""


class HandoffConflict(HandoffError):
    """Idempotency key, state or digest conflict."""


class HandoffPolicyError(HandoffError):
    """Input violates fixed safety boundaries."""


class HandoffService:
    """Mac Core source of truth for bounded Handoffs."""

    _TEMPLATE = HandoffTemplate(
        template_id="picotoopet-repo-maintenance-v1",
        display_name="PicotooPet 仓库维护",
        provider="manual",
        provider_configured=False,
        repo_url="https://github.com/jerryjwres-hue/picotoopet-v2.0",
        base_ref="feature/phase23-slice-d-diagnostic-snapshot-release",
        base_commit="5db6b1f9340ff5abe0d38bbb7b6e3ee9b48c34bb",
    )
    _CODEX_TEMPLATE = HandoffTemplate(
        template_id="picotoopet-repo-maintenance-codex-v1",
        display_name="PicotooPet 受控 Codex 仓库维护",
        provider="codex",
        provider_configured=False,
        repo_url="https://github.com/jerryjwres-hue/picotoopet-v2.0",
        base_ref="feature/autonomous-intelligence-e2e-goal-center-2.3.27.1",
        base_commit="423f14ea549a3303137f4ab5ad99d2afb60dbded",
    )
    _CLAUDE_CODE_TEMPLATE = HandoffTemplate(
        template_id="picotoopet-repo-maintenance-claude-code-v1",
        display_name="PicotooPet 受控 Claude Code 仓库维护",
        provider="claude_code",
        provider_configured=False,
        repo_url="https://github.com/jerryjwres-hue/picotoopet-v2.0",
        base_ref="feature/autonomous-intelligence-e2e-goal-center-2.3.27.1",
        base_commit="423f14ea549a3303137f4ab5ad99d2afb60dbded",
    )
    _CODING_PROVIDERS = frozenset({"codex", "claude_code"})
    _REQUIRED_TESTS = [
        "python-regression",
        "windows-wpf-behavior",
        "windows-formal-release",
        "mac-core-arm64",
    ]
    _PROVIDER_REQUIRED_TESTS = [
        "python-regression",
        "windows-wpf-behavior",
        "windows-formal-release",
        "mac-core-arm64",
        "mac-worker-arm64",
    ]
    _CODEX_REQUIRED_TESTS = _PROVIDER_REQUIRED_TESTS
    _MANUAL_BUDGET = {
        "max_turns": 20,
        "timeout_seconds": 1800,
        "concurrency": 1,
        "network_tools": False,
    }
    _PROVIDER_BUDGET = {
        "max_turns": 8,
        "timeout_seconds": 900,
        "concurrency": 1,
        "max_changed_files": 5,
        "max_file_bytes": 65536,
        "max_return_bytes": 262144,
        "automatic_retries": 0,
        "network_tools": False,
        "automatic_top_up": False,
        "automatic_publish": False,
    }
    _CODEX_BUDGET = _PROVIDER_BUDGET
    _SECURITY_BOUNDARIES = [
        "Protected source is excluded from every package.",
        "Provider execution is disabled in Phase 10A.",
        "Only an isolated future worktree may be writable.",
        "Local validation and human review remain mandatory.",
        "Push, merge, tag and release remain independently prohibited.",
    ]
    _PROVIDER_SECURITY_BOUNDARIES = [
        "Protected source and Raw Evidence are excluded from every package.",
        "Windows controls the Session but never receives coding-provider credentials.",
        "Mac Worker may write only inside one Session-exclusive Git worktree.",
        "One manual Usage confirmation permits one low-budget Session only.",
        "Local validation and human review remain mandatory.",
        "Automatic commit, push, PR, merge, tag, release and top-up are prohibited.",
    ]
    _CODEX_SECURITY_BOUNDARIES = _PROVIDER_SECURITY_BOUNDARIES
    _UNSAFE_TEXT_PATTERNS = (
        re.compile(r"(?:^|[\s/\\])\.\.(?:[/\\\s]|$)", re.IGNORECASE),
        re.compile(r"\b(?:main|master)\b", re.IGNORECASE),
        re.compile(r"protected\s*(?:原件|source|original)", re.IGNORECASE),
        re.compile(r"raw\s+evidence", re.IGNORECASE),
        re.compile(r"authorization\s*:\s*bearer", re.IGNORECASE),
        re.compile(
            r"\b(?:token|secret|credential|password)\s*[=:]",
            re.IGNORECASE,
        ),
        re.compile(r"(?:~[/\\]\.ssh|id_ed25519|id_rsa)", re.IGNORECASE),
        re.compile(r"powershell|executionpolicy|\bbypass\b", re.IGNORECASE),
        re.compile(r"\b(?:push|merge|tag|release)\b", re.IGNORECASE),
    )

    def __init__(
        self,
        database: Database,
        approvals: HandoffApprovalService,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.database = database
        self.approvals = approvals
        self._clock = clock or (lambda: datetime.now(UTC))

    def templates(self) -> list[HandoffTemplate]:
        """Return fixed templates; callers cannot construct provider authority."""

        return [
            self._TEMPLATE.model_copy(deep=True),
            self._CODEX_TEMPLATE.model_copy(deep=True),
            self._CLAUDE_CODE_TEMPLATE.model_copy(deep=True),
        ]

    def prepare(
        self,
        request: HandoffPrepareRequest,
        *,
        idempotency_key: str,
    ) -> HandoffRecord:
        """Normalize input and create a deterministic bounded Handoff draft."""

        key = self._require_idempotency_key(idempotency_key)
        self._enforce_safe_text(request.title, request.objective)
        template = self._template(request.template_id)
        coding_provider = template.provider in self._CODING_PROVIDERS
        required_tests = self._PROVIDER_REQUIRED_TESTS if coding_provider else self._REQUIRED_TESTS
        budget = self._PROVIDER_BUDGET if coding_provider else self._MANUAL_BUDGET
        boundaries = (
            self._PROVIDER_SECURITY_BOUNDARIES if coding_provider else self._SECURITY_BOUNDARIES
        )
        normalized_input = {
            "template_id": request.template_id,
            "title": request.title,
            "objective": request.objective,
            "expires_seconds": request.expires_seconds,
        }
        existing = self.database.fetchone(
            "SELECT * FROM handoffs WHERE prepare_idempotency_key = ?",
            (key,),
        )
        if existing is not None:
            stored_input = json.loads(existing["manifest_json"])["prepare_input"]
            if stored_input != normalized_input:
                raise HandoffConflict("Idempotency-Key 已绑定不同的 Handoff 请求。")
            return self._record_from_row(self._expire_if_needed(existing))

        created_at = self._now()
        expires_at = created_at + timedelta(seconds=request.expires_seconds)
        handoff_id = str(uuid4())
        if coding_provider:
            read_root = "workspace/source"
            write_root = "workspace/changes"
        else:
            read_root = f"D:/PicotooPet/DevSandbox/worktrees/{handoff_id}/source"
            write_root = f"D:/PicotooPet/DevSandbox/worktrees/{handoff_id}/workspace"
        request_payload = {
            "schema_version": "1.0.0-draft",
            "template_id": template.template_id,
            "title": request.title,
            "objective_summary": request.objective,
            "provider": template.provider,
            "sensitivity": "internal",
            "repo_url": template.repo_url,
            "base_ref": template.base_ref,
            "base_commit": template.base_commit,
            "planned_read": [read_root],
            "planned_write": [write_root],
            "required_tests": required_tests,
            "budget": budget,
            "expires_at": expires_at.isoformat(),
        }
        request_digest = self._digest(request_payload)
        package_files = self._build_package_files(
            handoff_id=handoff_id,
            title=request.title,
            objective=request.objective,
            read_root=read_root,
            write_root=write_root,
            request_digest=request_digest,
            required_tests=required_tests,
            budget=budget,
        )
        package_digest = self._digest(package_files)
        preview = {
            "handoff_id": handoff_id,
            "template_id": template.template_id,
            "template_name": template.display_name,
            "title": request.title,
            "objective_summary": request.objective,
            "status": HandoffStatus.PREPARED.value,
            "provider": template.provider,
            "provider_configured": template.provider_configured,
            "repo_url": template.repo_url,
            "base_ref": template.base_ref,
            "base_commit": template.base_commit,
            "sensitivity": "internal",
            "planned_read_count": 1,
            "planned_write_count": 1,
            "required_tests": required_tests,
            "budget_summary": self._budget_summary(template.provider),
            "request_digest": request_digest,
            "package_digest": package_digest,
            "approval_id": None,
            "created_at": created_at.isoformat(),
            "updated_at": created_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "security_boundaries": boundaries,
        }
        manifest = {
            "prepare_input": normalized_input,
            "request": request_payload,
            "package_files": package_files,
        }
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO handoffs (
                    handoff_id, template_id, title, objective_summary, status,
                    request_digest, package_digest, manifest_json, preview_json,
                    approval_id, prepare_idempotency_key, approval_idempotency_key,
                    created_at, updated_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, NULL, ?, ?, ?)
                """,
                (
                    handoff_id,
                    template.template_id,
                    request.title,
                    request.objective,
                    HandoffStatus.PREPARED.value,
                    request_digest,
                    package_digest,
                    self._canonical_json(manifest),
                    self._canonical_json(preview),
                    key,
                    created_at.isoformat(),
                    created_at.isoformat(),
                    expires_at.isoformat(),
                ),
            )
        return self.get(handoff_id)

    def list(self, *, limit: int = 100) -> list[HandoffRecord]:
        """Read bounded safe projections ordered by creation time."""

        bounded = max(1, min(limit, 100))
        rows = self.database.fetchall(
            "SELECT * FROM handoffs ORDER BY created_at DESC LIMIT ?",
            (bounded,),
        )
        return [self._record_from_row(self._expire_if_needed(row)) for row in rows]

    def get(self, handoff_id: str) -> HandoffRecord:
        """Read one Handoff safe projection."""

        row = self.database.fetchone(
            "SELECT * FROM handoffs WHERE handoff_id = ?",
            (handoff_id,),
        )
        if row is None:
            raise KeyError(f"Handoff 不存在：{handoff_id}")
        return self._record_from_row(self._expire_if_needed(row))

    def submit_for_approval(
        self,
        handoff_id: str,
        *,
        idempotency_key: str,
    ) -> HandoffRecord:
        """Create the resource approval and advance the Handoff in one transaction."""

        key = self._require_idempotency_key(idempotency_key)
        current = self.get(handoff_id)
        row = self.database.fetchone(
            "SELECT * FROM handoffs WHERE handoff_id = ?",
            (handoff_id,),
        )
        assert row is not None
        previous_key = row["approval_idempotency_key"]
        if previous_key is not None:
            if previous_key != key:
                raise HandoffConflict("Handoff 已使用不同 Idempotency-Key 提交审批。")
            return current
        if current.status is not HandoffStatus.PREPARED:
            raise HandoffConflict("只有 prepared Handoff 可以提交审批。")

        occurred_at = self._now()
        scope = {
            "action": "handoff.prepare",
            "handoff_id": current.handoff_id,
            "template_id": current.template_id,
            "provider": current.provider,
            "file_count": 6,
            "test_count": len(current.required_tests),
            "budget": current.budget_summary,
            "target": current.repo_url,
            "request_digest": current.request_digest,
            "package_digest": current.package_digest,
        }
        with self.database.transaction() as connection:
            grant = self.approvals.request_resource_in_transaction(
                connection,
                approval_type="handoff.prepare",
                scope=scope,
                requested_by="api-device",
                expires_at=current.expires_at,
                requested_at=occurred_at,
            )
            preview = json.loads(row["preview_json"])
            preview.update(
                {
                    "status": HandoffStatus.WAITING_APPROVAL.value,
                    "approval_id": grant.approval_id,
                    "updated_at": occurred_at.isoformat(),
                }
            )
            connection.execute(
                """
                UPDATE handoffs
                SET status = ?, approval_id = ?, approval_idempotency_key = ?,
                    preview_json = ?, updated_at = ?
                WHERE handoff_id = ?
                """,
                (
                    HandoffStatus.WAITING_APPROVAL.value,
                    grant.approval_id,
                    key,
                    self._canonical_json(preview),
                    occurred_at.isoformat(),
                    handoff_id,
                ),
            )
        return self.get(handoff_id)

    def reconcile_approval(self, approval: ApprovalRecord) -> None:
        """Sync terminal approval state without triggering the task queue."""

        if approval.approval_type != "handoff.prepare":
            return
        handoff_id = approval.scope.get("handoff_id")
        if not isinstance(handoff_id, str) or not handoff_id:
            return
        mapping = {
            "Approved": HandoffStatus.APPROVED,
            "Rejected": HandoffStatus.REJECTED,
            "Expired": HandoffStatus.EXPIRED,
        }
        target = mapping.get(approval.status)
        if target is None:
            return
        row = self.database.fetchone(
            "SELECT * FROM handoffs WHERE handoff_id = ? AND approval_id = ?",
            (handoff_id, approval.approval_id),
        )
        if row is None:
            return
        updated_at = self._as_utc(approval.resolved_at or self._now())
        preview = json.loads(row["preview_json"])
        preview.update(
            {
                "status": target.value,
                "updated_at": updated_at.isoformat(),
            }
        )
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE handoffs SET status = ?, preview_json = ?, updated_at = ? "
                "WHERE handoff_id = ?",
                (
                    target.value,
                    self._canonical_json(preview),
                    updated_at.isoformat(),
                    handoff_id,
                ),
            )

    def _expire_if_needed(self, row: Any) -> Any:
        status = HandoffStatus(row["status"])
        expires_at = self._as_utc(datetime.fromisoformat(row["expires_at"]))
        now = self._now()
        if status is HandoffStatus.APPROVED and expires_at <= now:
            target_status = HandoffStatus.EXPIRED
        elif (
            status in {HandoffStatus.PREPARED, HandoffStatus.WAITING_APPROVAL}
            and expires_at <= now
        ):
            target_status = HandoffStatus.EXPIRED
        else:
            return row
        preview = json.loads(row["preview_json"])
        preview.update(
            {
                "status": target_status.value,
                "updated_at": now.isoformat(),
            }
        )
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE handoffs SET status = ?, preview_json = ?, updated_at = ? "
                "WHERE handoff_id = ?",
                (
                    target_status.value,
                    self._canonical_json(preview),
                    now.isoformat(),
                    row["handoff_id"],
                ),
            )
        refreshed = self.database.fetchone(
            "SELECT * FROM handoffs WHERE handoff_id = ?",
            (row["handoff_id"],),
        )
        assert refreshed is not None
        return refreshed

    @classmethod
    def _build_package_files(
        cls,
        *,
        handoff_id: str,
        title: str,
        objective: str,
        read_root: str,
        write_root: str,
        request_digest: str,
        required_tests: list[str],
        budget: dict[str, object],
    ) -> list[dict[str, str]]:
        contents = {
            "handoff.json": cls._canonical_json(
                {
                    "schema_version": "1.0.0-draft",
                    "handoff_id": handoff_id,
                    "request_digest": request_digest,
                }
            ),
            "TASK_SPEC.md": f"# {title}\n\n{objective}\n",
            "ACCEPTANCE.json": cls._canonical_json(
                {
                    "required_tests": required_tests,
                    "local_validation": True,
                }
            ),
            "ALLOWED_PATHS.json": cls._canonical_json(
                {
                    "read_count": 1,
                    "write_count": 1,
                    "read_root": read_root,
                    "write_root": write_root,
                }
            ),
            "DENIED_ACTIONS.json": cls._canonical_json(
                {
                    "actions": [
                        "protected_source",
                        "branch_main",
                        "push",
                        "merge",
                        "tag",
                        "release",
                        "automatic_top_up",
                    ]
                }
            ),
            "COST_BUDGET.json": cls._canonical_json(budget),
        }
        return [
            {
                "path": path,
                "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            }
            for path, content in sorted(contents.items())
        ]

    @classmethod
    def _enforce_safe_text(cls, title: str, objective: str) -> None:
        combined = f"{title}\n{objective}"
        for pattern in cls._UNSAFE_TEXT_PATTERNS:
            if pattern.search(combined):
                raise HandoffPolicyError("Handoff 文本触发固定安全策略。")

    @staticmethod
    def _require_idempotency_key(value: str) -> str:
        normalized = value.strip()
        if not normalized or len(normalized) > 200:
            raise HandoffPolicyError("Handoff 操作缺少有效 Idempotency-Key。")
        return normalized

    @classmethod
    def _digest(cls, payload: object) -> str:
        return hashlib.sha256(cls._canonical_json(payload).encode("utf-8")).hexdigest()

    @staticmethod
    def _canonical_json(payload: object) -> str:
        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @classmethod
    def _template(cls, template_id: str) -> HandoffTemplate:
        if template_id == cls._TEMPLATE.template_id:
            return cls._TEMPLATE
        if template_id == cls._CODEX_TEMPLATE.template_id:
            return cls._CODEX_TEMPLATE
        if template_id == cls._CLAUDE_CODE_TEMPLATE.template_id:
            return cls._CLAUDE_CODE_TEMPLATE
        raise HandoffPolicyError("未知 Handoff 模板。")

    @classmethod
    def _budget_summary(cls, provider: str) -> str:
        if provider in cls._CODING_PROVIDERS:
            return "8 turns · 900 秒 · 1 并发 · 5 文件 · 0 自动重试 · 无网络工具"
        return "20 turns · 1800 秒 · 1 并发 · 无网络工具"

    def _now(self) -> datetime:
        return self._as_utc(self._clock())

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @staticmethod
    def _record_from_row(row: Any) -> HandoffRecord:
        preview = json.loads(row["preview_json"])
        return HandoffRecord.model_validate(preview)