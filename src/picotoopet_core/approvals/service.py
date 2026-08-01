"""限时、限范围、一次性人工审批令牌。"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel

from picotoopet_core.db.database import Database
from picotoopet_core.domain.enums import ApprovalStatus, TaskStatus
from picotoopet_core.queue.repository import QueueRepository


class ApprovalError(RuntimeError):
    """审批请求无效、过期或已使用。"""


class ApprovalGrant(BaseModel):
    """仅在创建时返回一次的明文授权。"""

    approval_id: str
    token: str
    expires_at: datetime


class ApprovalRecord(BaseModel):
    """不含明文令牌的审批记录。"""

    approval_id: str
    task_id: str | None
    approval_type: str
    scope: dict[str, object]
    status: str
    requested_by: str
    resolved_by: str | None
    expires_at: datetime
    requested_at: datetime
    resolved_at: datetime | None
    decision_reason: str | None


class ApprovalService:
    """创建与消费审批令牌，并恢复等待中的任务。"""

    def __init__(self, database: Database, queue: QueueRepository) -> None:
        self.database = database
        self.queue    = queue

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

        now         = datetime.now(UTC)
        approval_id = str(uuid4())
        token       = secrets.token_urlsafe(32)
        token_hash  = self._hash_token(token)
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
                    json.dumps(scope, ensure_ascii=False, separators=(",", ":")),
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

        now       = datetime.now(UTC)
        expired   = False
        task_id: str | None = None
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
            expires_at = datetime.fromisoformat(row["expires_at"])
            if expires_at <= now:
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
                        target=TaskStatus.QUEUED,
                        reason=f"approval:{approval_id}",
                        occurred_at=now,
                    )
                connection.execute(
                    """
                    UPDATE approvals
                    SET status = ?, resolved_by = ?, resolved_at = ?, decision_reason = ?
                    WHERE approval_id = ?
                    """,
                    (
                        ApprovalStatus.APPROVED.value,
                        resolved_by,
                        now.isoformat(),
                        reason,
                        approval_id,
                    ),
                )

        if expired:
            raise ApprovalError("审批已过期。")
        return self.get(approval_id)

    def reject(
        self,
        *,
        approval_id: str,
        token: str,
        resolved_by: str,
        reason: str,
    ) -> ApprovalRecord:
        """一次性拒绝审批，并取消对应等待任务。"""

        now       = datetime.now(UTC)
        expired   = False
        task_id: str | None = None
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
                        target=TaskStatus.CANCELLED,
                        reason=f"approval_rejected:{approval_id}",
                        occurred_at=now,
                    )
                connection.execute(
                    """
                    UPDATE approvals
                    SET status = ?, resolved_by = ?, resolved_at = ?, decision_reason = ?
                    WHERE approval_id = ?
                    """,
                    (
                        ApprovalStatus.REJECTED.value,
                        resolved_by,
                        now.isoformat(),
                        reason,
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
        return ApprovalRecord(
            approval_id=row["approval_id"],
            task_id=row["task_id"],
            approval_type=row["approval_type"],
            scope=json.loads(row["scope_json"]),
            status=row["status"],
            requested_by=row["requested_by"],
            resolved_by=row["resolved_by"],
            expires_at=datetime.fromisoformat(row["expires_at"]),
            requested_at=datetime.fromisoformat(row["requested_at"]),
            resolved_at=(
                None if row["resolved_at"] is None else datetime.fromisoformat(row["resolved_at"])
            ),
            decision_reason=row["decision_reason"],
        )

    @staticmethod
    def _hash_token(token: str) -> str:
        """生成不可逆令牌摘要。"""

        return hashlib.sha256(token.encode("utf-8")).hexdigest()
