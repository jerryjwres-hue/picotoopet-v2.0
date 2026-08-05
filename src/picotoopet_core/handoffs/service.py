"""确定性 Handoff 准备、持久化、幂等和审批状态同步。"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from picotoopet_core.approvals.service import ApprovalRecord, ApprovalService
from picotoopet_core.db.database import Database

from .models import HandoffPrepareRequest, HandoffRecord, HandoffStatus, HandoffTemplate


class HandoffError(RuntimeError):
    """Handoff 准备或状态操作失败。"""


class HandoffConflict(HandoffError):
    """幂等键、状态或摘要发生冲突。"""


class HandoffPolicyError(HandoffError):
    """输入违反固定安全边界。"""


class HandoffService:
    """Mac Core 中 Phase 10A Handoff 的唯一事实服务。"""

    _TEMPLATE = HandoffTemplate(
        template_id="picotoopet-repo-maintenance-v1",
        display_name="PicotooPet 仓库维护",
        provider="manual",
        provider_configured=False,
        repo_url="https://github.com/jerryjwres-hue/picotoopet-v2.0",
        base_ref="feature/phase23-slice-d-diagnostic-snapshot-release",
        base_commit="5db6b1f9340ff5abe0d38bbb7b6e3ee9b48c34bb",
    )
    _REQUIRED_TESTS = [
        "python-regression",
        "windows-wpf-behavior",
        "windows-formal-release",
        "mac-core-arm64",
    ]
    _SECURITY_BOUNDARIES = [
        "Protected source is excluded from every package.",
        "Provider execution is disabled in Phase 10A.",
        "Only an isolated future worktree may be writable.",
        "Local validation and human review remain mandatory.",
        "Push, merge, tag and release remain independently prohibited.",
    ]
    _UNSAFE_TEXT_PATTERNS = (
        re.compile(r"(?:^|[\s/\\])\.\.(?:[/\\\s]|$)", re.IGNORECASE),
        re.compile(r"\b(?:main|master)\b", re.IGNORECASE),
        re.compile(r"protected\s*(?:原件|source|original)", re.IGNORECASE),
        re.compile(r"raw\s+evidence", re.IGNORECASE),
        re.compile(r"authorization\s*:\s*bearer", re.IGNORECASE),
        re.compile(r"\b(?:token|secret|credential|password)\s*[=:]", re.IGNORECASE),
        re.compile(r"(?:~[/\\]\.ssh|id_ed25519|id_rsa)", re.IGNORECASE),
        re.compile(r"powershell|executionpolicy|\bbypass\b", re.IGNORECASE),
        re.compile(r"\b(?:push|merge|tag|release)\b", re.IGNORECASE),
    )

    def __init__(self, database: Database, approvals: ApprovalService) -> None:
        self.database  = database
        self.approvals = approvals

    def templates(self) -> list[HandoffTemplate]:
        """返回固定模板，禁止客户端自行构造权限事实。"""

        return [self._TEMPLATE.model_copy(deep=True)]

    def prepare(
        self,
        request: HandoffPrepareRequest,
        *,
        idempotency_key: str,
        now: datetime | None = None,
    ) -> HandoffRecord:
        """规范化输入并生成不执行 Provider 的确定性 Handoff 草稿。"""

        key = self._require_idempotency_key(idempotency_key)
        self._enforce_safe_text(request.title, request.objective)
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
            return self._record_from_row(existing)

        created_at = self._as_utc(now or datetime.now(UTC))
        expires_at = created_at + timedelta(seconds=request.expires_seconds)
        handoff_id = str(uuid4())
        read_root  = f"D:/PicotooPet/DevSandbox/worktrees/{handoff_id}/source"
        write_root = f"D:/PicotooPet/DevSandbox/worktrees/{handoff_id}/workspace"
        request_payload = {
            "schema_version": "1.0.0-draft",
            "template_id": self._TEMPLATE.template_id,
            "title": request.title,
            "objective_summary": request.objective,
            "provider": self._TEMPLATE.provider,
            "sensitivity": "internal",
            "repo_url": self._TEMPLATE.repo_url,
            "base_ref": self._TEMPLATE.base_ref,
            "base_commit": self._TEMPLATE.base_commit,
            "planned_read": [read_root],
            "planned_write": [write_root],
            "required_tests": self._REQUIRED_TESTS,
            "budget": {
                "max_turns": 20,
                "timeout_seconds": 1800,
                "concurrency": 1,
                "network_tools": False,
            },
            "expires_at": expires_at.isoformat(),
        }
        request_digest = self._digest(request_payload)
        package_files  = self._build_package_files(
            handoff_id=handoff_id,
            title=request.title,
            objective=request.objective,
            read_root=read_root,
            write_root=write_root,
            request_digest=request_digest,
        )
        package_digest = self._digest(package_files)
        preview = {
            "handoff_id": handoff_id,
            "template_id": self._TEMPLATE.template_id,
            "template_name": self._TEMPLATE.display_name,
            "title": request.title,
            "objective_summary": request.objective,
            "status": HandoffStatus.PREPARED.value,
            "provider": self._TEMPLATE.provider,
            "provider_configured": False,
            "repo_url": self._TEMPLATE.repo_url,
            "base_ref": self._TEMPLATE.base_ref,
            "base_commit": self._TEMPLATE.base_commit,
            "sensitivity": "internal",
            "planned_read_count": 1,
            "planned_write_count": 1,
            "required_tests": self._REQUIRED_TESTS,
            "budget_summary": "20 turns · 1800 秒 · 1 并发 · 无网络工具",
            "request_digest": request_digest,
            "package_digest": package_digest,
            "approval_id": None,
            "created_at": created_at.isoformat(),
            "updated_at": created_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "security_boundaries": self._SECURITY_BOUNDARIES,
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
                    self._TEMPLATE.template_id,
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
        """按创建时间倒序读取有界安全投影。"""

        bounded = max(1, min(limit, 100))
        rows = self.database.fetchall(
            "SELECT * FROM handoffs ORDER BY created_at DESC LIMIT ?",
            (bounded,),
        )
        return [self._record_from_row(self._expire_if_needed(row)) for row in rows]

    def get(self, handoff_id: str) -> HandoffRecord:
        """读取单个 Handoff 的安全投影。"""

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
        now: datetime | None = None,
    ) -> HandoffRecord:
        """在一个事务中创建资源审批并把 Handoff 推进到等待状态。"""

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

        occurred_at = self._as_utc(now or datetime.now(UTC))
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
        """把 Handoff 审批终态同步回事实表，不触发任务队列。"""

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
        updated_at = approval.resolved_at or datetime.now(UTC)
        preview = json.loads(row["preview_json"])
        preview.update({"status": target.value, "updated_at": updated_at.isoformat()})
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
        expires_at = datetime.fromisoformat(row["expires_at"])
        if status in {HandoffStatus.PREPARED, HandoffStatus.WAITING_APPROVAL} and expires_at <= datetime.now(UTC):
            preview = json.loads(row["preview_json"])
            preview.update(
                {
                    "status": HandoffStatus.EXPIRED.value,
                    "updated_at": datetime.now(UTC).isoformat(),
                }
            )
            with self.database.transaction() as connection:
                connection.execute(
                    "UPDATE handoffs SET status = ?, preview_json = ?, updated_at = ? "
                    "WHERE handoff_id = ?",
                    (
                        HandoffStatus.EXPIRED.value,
                        self._canonical_json(preview),
                        preview["updated_at"],
                        row["handoff_id"],
                    ),
                )
            refreshed = self.database.fetchone(
                "SELECT * FROM handoffs WHERE handoff_id = ?",
                (row["handoff_id"],),
            )
            assert refreshed is not None
            return refreshed
        return row

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
                {"required_tests": cls._REQUIRED_TESTS, "local_validation": True}
            ),
            "ALLOWED_PATHS.json": cls._canonical_json(
                {"read_count": 1, "write_count": 1, "read_root": read_root, "write_root": write_root}
            ),
            "DENIED_ACTIONS.json": cls._canonical_json(
                {"actions": ["protected_source", "branch_main", "push", "merge", "tag", "release"]}
            ),
            "COST_BUDGET.json": cls._canonical_json(
                {"max_turns": 20, "timeout_seconds": 1800, "concurrency": 1, "network_tools": False}
            ),
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

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @staticmethod
    def _record_from_row(row: Any) -> HandoffRecord:
        preview = json.loads(row["preview_json"])
        return HandoffRecord.model_validate(preview)
