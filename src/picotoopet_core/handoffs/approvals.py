"""在现有 ApprovalService 上增加 Handoff 与受控资源审批能力。"""

from __future__ import annotations

import secrets
from datetime import datetime
from sqlite3 import Connection
from uuid import uuid4

from picotoopet_core.approvals.service import ApprovalGrant, ApprovalService
from picotoopet_core.domain.enums import ApprovalStatus


class HandoffApprovalService(ApprovalService):
    """兼容现有任务审批，并允许无 task_id 的 digest-bound 资源审批。"""

    _SUMMARY_KEYS = ApprovalService._SUMMARY_KEYS | frozenset(
        {
            "handoff_id",
            "package_digest",
            "request_digest",
            "template_id",
            "test_count",
            "commit_candidate_id",
            "adoption_candidate_id",
            "session_id",
            "return_id",
            "base_commit",
            "change_set_digest",
            "local_ref",
            "message_digest",
        }
    )

    def request_resource_in_transaction(
        self,
        connection: Connection,
        *,
        approval_type: str,
        scope: dict[str, object],
        requested_by: str,
        expires_at: datetime,
        requested_at: datetime,
    ) -> ApprovalGrant:
        """在调用方事务中创建 task_id 为空的一次性资源审批。"""

        approval_id = str(uuid4())
        token = secrets.token_urlsafe(32)
        connection.execute(
            """
            INSERT INTO approvals (
                approval_id, task_id, approval_type, scope_json, status, token_hash,
                requested_by, expires_at, requested_at
            ) VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                approval_id,
                approval_type,
                self._canonical_scope(scope),
                ApprovalStatus.PENDING.value,
                self._hash_token(token),
                requested_by,
                expires_at.isoformat(),
                requested_at.isoformat(),
            ),
        )
        return ApprovalGrant(
            approval_id=approval_id,
            token=token,
            expires_at=expires_at,
        )
