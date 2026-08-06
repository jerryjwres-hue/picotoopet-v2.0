"""Broker Session 幂等预留、状态事实和 Mock Return 导回。"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

from picotoopet_core.db.database import Database
from picotoopet_core.handoffs.models import HandoffRecord, HandoffStatus
from picotoopet_core.handoffs.service import HandoffService
from picotoopet_core.returns.service import ReturnValidationService

from .models import (
    BrokerSessionCreateResult,
    BrokerSessionRecord,
    BrokerSessionStatus,
    MockBrokerReturnEnvelope,
)


class BrokerSessionError(RuntimeError):
    """Broker Session 读取、状态或 Return 导回失败。"""


class BrokerSessionConflict(BrokerSessionError):
    """幂等键、状态或资源绑定冲突。"""


class BrokerSessionPolicyError(BrokerSessionError):
    """操作违反固定 Mock Dev Broker 安全边界。"""


class BrokerSessionService:
    """Mac Core 中 Broker Session 的唯一事实服务。"""

    _PROVIDER         = "local-mock-dev-broker"
    _TIMEOUT_SECONDS  = 30
    _EXECUTION_NOTICE = (
        "仅运行应用内置 Mock Provider、固定 LocalAppData 沙盒和 Return 合同验证；"
        "未调用真实 Provider，未运行项目测试、构建、Git worktree、PR 或发布。"
    )
    _TERMINAL_STATES = frozenset(
        {
            BrokerSessionStatus.COMPLETED,
            BrokerSessionStatus.CANCELLED,
            BrokerSessionStatus.TIMED_OUT,
            BrokerSessionStatus.FAILED,
            BrokerSessionStatus.QUARANTINED,
        }
    )

    def __init__(
        self,
        database: Database,
        handoffs: HandoffService,
        returns: ReturnValidationService,
        *,
        api_token: str,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if len(api_token) < 16:
            raise ValueError("Broker Session HMAC 密钥长度不足。")
        self.database   = database
        self.handoffs   = handoffs
        self.returns    = returns
        self._api_token = api_token.encode("utf-8")
        self._clock     = clock or (lambda: datetime.now(UTC))

    def reserve_mock_session(
        self,
        handoff_id: str,
        *,
        idempotency_key: str,
    ) -> BrokerSessionCreateResult:
        """为 approved Handoff 幂等预留一个固定 Mock Broker Session。"""

        key      = self._require_idempotency_key(idempotency_key)
        existing = self._existing_by_idempotency(key, handoff_id)
        if existing is not None:
            return BrokerSessionCreateResult(
                record=existing,
                capability=self._session_capability(
                    existing.session_id,
                    existing.handoff_id,
                ),
            )
        handoff    = self._require_approved_handoff(handoff_id)
        session_id = str(uuid4())
        now        = self._now()
        preview    = BrokerSessionRecord(
            session_id=session_id,
            handoff_id=handoff.handoff_id,
            status=BrokerSessionStatus.RESERVED,
            provider=self._PROVIDER,
            timeout_seconds=self._TIMEOUT_SECONDS,
            request_digest=handoff.request_digest,
            package_digest=handoff.package_digest,
            return_id=None,
            event_count=0,
            sandbox_digest=None,
            failure_code=None,
            created_at=now,
            updated_at=now,
            finished_at=None,
            execution_notice=self._EXECUTION_NOTICE,
        )
        preview_json = self._canonical_json(preview.model_dump(mode="json"))
        try:
            with self.database.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO broker_sessions (
                        session_id, handoff_id, status, provider, timeout_seconds,
                        request_digest, package_digest, return_id, event_count,
                        sandbox_digest, failure_code, idempotency_key, created_at,
                        updated_at, finished_at, preview_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 0, NULL, NULL, ?, ?, ?, NULL, ?)
                    """,
                    (
                        session_id,
                        handoff.handoff_id,
                        BrokerSessionStatus.RESERVED.value,
                        self._PROVIDER,
                        self._TIMEOUT_SECONDS,
                        handoff.request_digest,
                        handoff.package_digest,
                        key,
                        now.isoformat(),
                        now.isoformat(),
                        preview_json,
                    ),
                )
        except Exception as error:
            existing = self._existing_by_idempotency(key, handoff_id)
            if existing is not None:
                return BrokerSessionCreateResult(
                    record=existing,
                    capability=self._session_capability(
                        existing.session_id,
                        existing.handoff_id,
                    ),
                )
            raise BrokerSessionConflict("Broker Session 持久化冲突。") from error
        return BrokerSessionCreateResult(
            record=preview,
            capability=self._session_capability(session_id, handoff.handoff_id),
        )

    def list_sessions(self, *, limit: int = 100) -> list[BrokerSessionRecord]:
        """按创建时间倒序返回最多 100 条安全投影。"""

        bounded = max(1, min(limit, 100))
        rows = self.database.fetchall(
            "SELECT preview_json FROM broker_sessions ORDER BY created_at DESC LIMIT ?",
            (bounded,),
        )
        return [
            BrokerSessionRecord.model_validate(json.loads(row["preview_json"]))
            for row in rows
        ]

    def get_session(self, session_id: str) -> BrokerSessionRecord:
        """读取一个 Broker Session 安全投影。"""

        row = self.database.fetchone(
            "SELECT preview_json FROM broker_sessions WHERE session_id = ?",
            (session_id,),
        )
        if row is None:
            raise KeyError(f"Broker Session 不存在：{session_id}")
        return BrokerSessionRecord.model_validate(json.loads(row["preview_json"]))

    def cancel_session(self, session_id: str) -> BrokerSessionRecord:
        """把未完成 Session 标记为 cancelled；进程终止仍由 Windows Broker 执行。"""

        current = self.get_session(session_id)
        if current.status in self._TERMINAL_STATES:
            return current
        return self._transition(
            current,
            BrokerSessionStatus.CANCELLED,
            failure_code="BROKER_CANCELLED",
            finished=True,
        )

    def mark_running(self, session_id: str) -> BrokerSessionRecord:
        """记录 Windows 已开始固定 Mock Broker 子进程。"""

        current = self.get_session(session_id)
        if current.status is BrokerSessionStatus.RUNNING:
            return current
        if current.status is not BrokerSessionStatus.RESERVED:
            raise BrokerSessionConflict("Broker Session 不能从当前状态进入 running。")
        return self._transition(current, BrokerSessionStatus.RUNNING)

    def ingest_mock_return(
        self,
        session_id: str,
        envelope: MockBrokerReturnEnvelope,
        *,
        capability: str,
        idempotency_key: str,
    ) -> BrokerSessionRecord:
        """验证 capability 与 Session 绑定；Return 细节由 Return 服务独立验证。"""

        del idempotency_key
        current  = self.get_session(session_id)
        expected = self._session_capability(current.session_id, current.handoff_id)
        if not hmac.compare_digest(capability, expected):
            raise BrokerSessionPolicyError("Broker Session capability 无效。")
        if (
            envelope.session_id != current.session_id
            or envelope.handoff_id != current.handoff_id
        ):
            raise BrokerSessionPolicyError("Broker Return 与 Session 绑定不匹配。")
        if (
            envelope.request_digest != current.request_digest
            or envelope.package_digest != current.package_digest
        ):
            raise BrokerSessionPolicyError("Broker Return digest 与 Session 事实不匹配。")
        raise NotImplementedError("Mock Return 验证将在 Return 策略任务中实现。")

    def _transition(
        self,
        current: BrokerSessionRecord,
        status: BrokerSessionStatus,
        *,
        failure_code: str | None = None,
        return_id: str | None = None,
        event_count: int | None = None,
        sandbox_digest: str | None = None,
        finished: bool = False,
    ) -> BrokerSessionRecord:
        now = self._now()
        preview = current.model_copy(
            update={
                "status": status,
                "failure_code": failure_code,
                "return_id": return_id if return_id is not None else current.return_id,
                "event_count": (
                    event_count if event_count is not None else current.event_count
                ),
                "sandbox_digest": (
                    sandbox_digest
                    if sandbox_digest is not None
                    else current.sandbox_digest
                ),
                "updated_at": now,
                "finished_at": now if finished else current.finished_at,
            }
        )
        preview_json = self._canonical_json(preview.model_dump(mode="json"))
        with self.database.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE broker_sessions
                SET status = ?, return_id = ?, event_count = ?, sandbox_digest = ?,
                    failure_code = ?, updated_at = ?, finished_at = ?, preview_json = ?
                WHERE session_id = ? AND status = ?
                """,
                (
                    status.value,
                    preview.return_id,
                    preview.event_count,
                    preview.sandbox_digest,
                    preview.failure_code,
                    now.isoformat(),
                    preview.finished_at.isoformat() if preview.finished_at else None,
                    preview_json,
                    current.session_id,
                    current.status.value,
                ),
            )
            if cursor.rowcount != 1:
                latest = self.get_session(current.session_id)
                if latest == preview:
                    return latest
                raise BrokerSessionConflict("Broker Session 状态已由其他请求更新。")
        return preview

    def _existing_by_idempotency(
        self,
        idempotency_key: str,
        handoff_id: str,
    ) -> BrokerSessionRecord | None:
        row = self.database.fetchone(
            "SELECT handoff_id, preview_json FROM broker_sessions WHERE idempotency_key = ?",
            (idempotency_key,),
        )
        if row is None:
            return None
        if row["handoff_id"] != handoff_id:
            raise BrokerSessionConflict("Idempotency-Key 已绑定不同的 Handoff。")
        return BrokerSessionRecord.model_validate(json.loads(row["preview_json"]))

    def _require_approved_handoff(self, handoff_id: str) -> HandoffRecord:
        handoff = self.handoffs.get(handoff_id)
        if handoff.status is not HandoffStatus.APPROVED:
            raise BrokerSessionPolicyError("只有 approved Handoff 可以创建 Broker Session。")
        return handoff

    def _session_capability(self, session_id: str, handoff_id: str) -> str:
        message = f"broker-session-v1:{session_id}:{handoff_id}".encode("utf-8")
        return hmac.new(self._api_token, message, hashlib.sha256).hexdigest()

    @staticmethod
    def _require_idempotency_key(value: str) -> str:
        key = value.strip()
        if not 1 <= len(key) <= 200 or any(ord(character) < 33 for character in key):
            raise BrokerSessionPolicyError("Idempotency-Key 不符合固定安全格式。")
        return key

    @staticmethod
    def _canonical_json(value: object) -> str:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
