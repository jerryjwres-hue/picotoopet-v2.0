"""限时、限范围、一次性人工审批与 Control Center 安全决策。"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel

from picotoopet_core.db.database import Database
from picotoopet_core.domain.enums import ApprovalStatus, TaskStatus
from picotoopet_core.queue.repository import QueueRepository


class ApprovalError(RuntimeError):
    """审批请求无效、过期、摘要变化或已被相反决策处理。"""


class ApprovalGrant(BaseModel):
    """仅在创建时返回一次的明文授权。"""

    approval_id: str
    token: str
    expires_at: datetime


class ApprovalRecord(BaseModel):
    """不含明文令牌、令牌哈希或任意原始路径的审批记录。"""

    approval_id: str
    task_id: str | None
    approval_type: str
    scope: dict[str, object]
    scope_summary: str
    request_digest: str
    status: str
    requested_by: str
    resolved_by: str | None
    expires_at: datetime
    requested_at: datetime
    resolved_at: datetime | None
    decision_reason: str | None


class ApprovalService:
    """创建与消费审批令牌，并提供 Windows 审批中心的安全摘要决策。"""

    _SUMMARY_KEYS = frozenset(
        {
            "action",
            "artifact_count",
            "budget",
            "file_count",
            "project_id",
            "provider",
            "target",
        }
    )

    def __init__(self, database: Database, queue: QueueRepository) -> None:
        self.database = database
        self.queue = queue

    def request(
        self,
        *,
        task_id: str,
        approval_type: str,
        scope: dict[str, object],
        requested_by: str,
        expires_at: datetime,
    ) -> ApprovalGrant:
        """创建一次性审批，仅把令牌哈希写入数据库。"""

        task = self.queue.get(task_id)
        if task.status is not TaskStatus.WAITING_FOR_APPROVAL:
            raise ApprovalError("任务不在 WaitingForApproval 状态。")

        now = datetime.now(UTC)
        approval_id = str(uuid4())
        token = secrets.token_urlsafe(32)
        token_hash = self._hash_token(token)
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO approvals (
                    approval_id, task_id, approval_type, scope_json, status, token_hash,
                    requested_by, expires_at, requested_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    approval_id,
                    task_id,
                    approval_type,
                    self._canonical_scope(scope),
                    ApprovalStatus.PENDING.value,
                    token_hash,
                    requested_by,
                    expires_at.isoformat(),
                    now.isoformat(),
                ),
            )
            connection.execute(
                "UPDATE tasks SET approval_id = ?, updated_at = ? WHERE task_id = ?",
                (approval_id, now.isoformat(), task_id),
            )
        return ApprovalGrant(approval_id=approval_id, token=token, expires_at=expires_at)

    def approve(
        self,
        *,
        approval_id: str,
        token: str,
        resolved_by: str,
        reason: str,
    ) -> ApprovalRecord:
        """一次性批准并把对应任务恢复到队列。"""

        return self._decide_with_token(
            approval_id=approval_id,
            token=token,
            decision="approve",
            resolved_by=resolved_by,
            reason=reason,
        )

    def reject(
        self,
        *,
        approval_id: str,
        token: str,
        resolved_by: str,
        reason: str,
    ) -> ApprovalRecord:
        """一次性拒绝审批，并取消对应等待任务。"""

        return self._decide_with_token(
            approval_id=approval_id,
            token=token,
            decision="reject",
            resolved_by=resolved_by,
            reason=reason,
        )

    def list_for_control_center(self, *, limit: int = 200) -> list[ApprovalRecord]:
        """按申请时间倒序返回有界、安全、无令牌的审批中心快照。"""

        bounded = max(1, min(limit, 200))
        rows = self.database.fetchall(
            "SELECT * FROM approvals ORDER BY requested_at DESC LIMIT ?",
            (bounded,),
        )
        now = datetime.now(UTC)
        return [self._record_from_row(row, now=now) for row in rows]

    def decide_for_control_center(
        self,
        *,
        approval_id: str,
        decision: Literal["approve", "reject"],
        request_digest: str,
        idempotency_key: str,
        resolved_by: str,
        reason: str,
    ) -> ApprovalRecord:
        """校验当前摘要后执行终态决策；同方向重复点击安全返回原结果。"""

        if not idempotency_key.strip():
            raise ApprovalError("审批决策缺少 Idempotency-Key。")
        if not reason.strip():
            raise ApprovalError("审批原因不能为空。")

        now = datetime.now(UTC)
        expired = False
        target_status = (
            ApprovalStatus.APPROVED.value
            if decision == "approve"
            else ApprovalStatus.REJECTED.value
        )
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM approvals WHERE approval_id = ?",
                (approval_id,),
            ).fetchone()
            if row is None:
                raise ApprovalError("审批不存在。")

            current_digest = self._request_digest(row)
            if not hmac.compare_digest(current_digest, request_digest):
                raise ApprovalError("审批请求摘要已变化，请刷新后重新确认。")

            if row["status"] == target_status:
                # 终态本身就是幂等边界；重复网络提交不得再次转换任务或追加副作用。
                return self._record_from_row(row, now=now)
            if row["status"] != ApprovalStatus.PENDING.value:
                raise ApprovalError("审批已被其他决策处理，禁止冲突重放。")

            if datetime.fromisoformat(row["expires_at"]) <= now:
                connection.execute(
                    "UPDATE approvals SET status = ?, resolved_at = ?, decision_reason = ? "
                    "WHERE approval_id = ?",
                    (
                        ApprovalStatus.EXPIRED.value,
                        now.isoformat(),
                        "expired",
                        approval_id,
                    ),
                )
                expired = True
            else:
                task_id = row["task_id"]
                if task_id is not None:
                    self.queue.transition_in_transaction(
                        connection,
                        task_id=task_id,
                        target=(
                            TaskStatus.QUEUED
                            if decision == "approve"
                            else TaskStatus.CANCELLED
                        ),
                        reason=(
                            f"approval:{approval_id}"
                            if decision == "approve"
                            else f"approval_rejected:{approval_id}"
                        ),
                        occurred_at=now,
                    )
                connection.execute(
                    """
                    UPDATE approvals
                    SET status = ?, resolved_by = ?, resolved_at = ?, decision_reason = ?
                    WHERE approval_id = ?
                    """,
                    (
                        target_status,
                        resolved_by,
                        now.isoformat(),
                        reason.strip(),
                        approval_id,
                    ),
                )

        if expired:
            raise ApprovalError("审批已过期。")
        return self.get(approval_id)

    def get(self, approval_id: str) -> ApprovalRecord:
        """读取无敏感令牌的审批记录。"""

        row = self.database.fetchone(
            "SELECT * FROM approvals WHERE approval_id = ?",
            (approval_id,),
        )
        if row is None:
            raise KeyError(f"审批不存在：{approval_id}")
        return self._record_from_row(row, now=datetime.now(UTC))

    def _decide_with_token(
        self,
        *,
        approval_id: str,
        token: str,
        decision: Literal["approve", "reject"],
        resolved_by: str,
        reason: str,
    ) -> ApprovalRecord:
        """保留旧 API 的一次性令牌语义，避免破坏既有调用方。"""

        now = datetime.now(UTC)
        expired = False
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM approvals WHERE approval_id = ?",
                (approval_id,),
            ).fetchone()
            if row is None:
                raise ApprovalError("审批不存在。")
            if row["status"] != ApprovalStatus.PENDING.value:
                raise ApprovalError("审批已处理，禁止重放。")
            if not hmac.compare_digest(row["token_hash"], self._hash_token(token)):
                raise ApprovalError("审批令牌无效。")
            if datetime.fromisoformat(row["expires_at"]) <= now:
                connection.execute(
                    "UPDATE approvals SET status = ?, resolved_at = ?, decision_reason = ? "
                    "WHERE approval_id = ?",
                    (
                        ApprovalStatus.EXPIRED.value,
                        now.isoformat(),
                        "expired",
                        approval_id,
                    ),
                )
                expired = True
            else:
                task_id = row["task_id"]
                if task_id is not None:
                    self.queue.transition_in_transaction(
                        connection,
                        task_id=task_id,
                        target=(
                            TaskStatus.QUEUED
                            if decision == "approve"
                            else TaskStatus.CANCELLED
                        ),
                        reason=(
                            f"approval:{approval_id}"
                            if decision == "approve"
                            else f"approval_rejected:{approval_id}"
                        ),
                        occurred_at=now,
                    )
                connection.execute(
                    """
                    UPDATE approvals
                    SET status = ?, resolved_by = ?, resolved_at = ?, decision_reason = ?
                    WHERE approval_id = ?
                    """,
                    (
                        (
                            ApprovalStatus.APPROVED.value
                            if decision == "approve"
                            else ApprovalStatus.REJECTED.value
                        ),
                        resolved_by,
                        now.isoformat(),
                        reason,
                        approval_id,
                    ),
                )

        if expired:
            raise ApprovalError("审批已过期。")
        return self.get(approval_id)

    def _record_from_row(self, row: object, *, now: datetime) -> ApprovalRecord:
        scope = json.loads(row["scope_json"])
        expires_at = datetime.fromisoformat(row["expires_at"])
        status = row["status"]
        if status == ApprovalStatus.PENDING.value and expires_at <= now:
            status = ApprovalStatus.EXPIRED.value
        return ApprovalRecord(
            approval_id=row["approval_id"],
            task_id=row["task_id"],
            approval_type=row["approval_type"],
            scope=scope,
            scope_summary=self._scope_summary(scope),
            request_digest=self._request_digest(row),
            status=status,
            requested_by=row["requested_by"],
            resolved_by=row["resolved_by"],
            expires_at=expires_at,
            requested_at=datetime.fromisoformat(row["requested_at"]),
            resolved_at=(
                None if row["resolved_at"] is None else datetime.fromisoformat(row["resolved_at"])
            ),
            decision_reason=row["decision_reason"],
        )

    @classmethod
    def _scope_summary(cls, scope: dict[str, object]) -> str:
        """只展示固定白名单标量，拒绝任意路径、嵌套正文和秘密字段。"""

        parts: list[str] = []
        for key in sorted(cls._SUMMARY_KEYS):
            if key not in scope:
                continue
            value = scope[key]
            if isinstance(value, bool | int | float | str):
                text = str(value).replace("\r", " ").replace("\n", " ").strip()
                if len(text) > 120:
                    text = text[:117] + "..."
                parts.append(f"{key}={text}")
        return "；".join(parts) if parts else "未提供可公开的范围摘要"

    @classmethod
    def _request_digest(cls, row: object) -> str:
        """摘要仅绑定不可变请求内容，状态变化不会破坏同向幂等重试。"""

        payload = {
            "approval_id": row["approval_id"],
            "task_id": row["task_id"],
            "approval_type": row["approval_type"],
            "scope": json.loads(row["scope_json"]),
            "requested_by": row["requested_by"],
            "requested_at": row["requested_at"],
            "expires_at": row["expires_at"],
        }
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _canonical_scope(scope: dict[str, object]) -> str:
        return json.dumps(
            scope,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @staticmethod
    def _hash_token(token: str) -> str:
        """生成不可逆令牌摘要。"""

        return hashlib.sha256(token.encode("utf-8")).hexdigest()
