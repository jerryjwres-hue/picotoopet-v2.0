"""Slice D 诊断任务的原子结果、取消和重试生命周期。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from sqlite3 import Connection, Row
from uuid import uuid4

from picotoopet_core.domain.enums import TaskStatus
from picotoopet_core.domain.models import TaskRecord
from picotoopet_core.results.models import StoredResult

from .repository import LeaseOwnershipError, QueueRepository
from .state_machine import InvalidTransitionError, ensure_transition


class DiagnosticQueueRepository(QueueRepository):
    """在基础耐久队列上增加诊断结果的专属事务边界。"""

    def complete_leased_with_result(
        self,
        task_id: str,
        *,
        worker_id: str,
        stored_result: StoredResult,
        schema_version: str,
        trace_id: str | None = None,
    ) -> TaskRecord:
        """原子提交结果元数据、任务终态、attempt、事件和 Outbox。"""

        now = datetime.now(UTC)
        result_id = str(uuid4())
        manifest = {
            "object_hash": stored_result.object_hash,
            "size_bytes": stored_result.size_bytes,
            "result_type": stored_result.result_type,
            "media_type": "application/json",
        }
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            self._assert_active_lease(row, worker_id=worker_id, now=now)
            assert row is not None
            if self._cancel_requested_in_transaction(connection, task_id):
                raise LeaseOwnershipError("任务已有取消意图，禁止提交结果。")
            current = TaskStatus(row["status"])
            ensure_transition(current, TaskStatus.COMPLETED)

            connection.execute(
                """
                INSERT INTO results (
                    result_id, project_id, task_id, result_type,
                    object_hash, manifest_json, schema_version, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result_id,
                    row["project_id"],
                    task_id,
                    stored_result.result_type,
                    stored_result.object_hash,
                    json.dumps(
                        manifest,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    schema_version,
                    now.isoformat(),
                ),
            )
            connection.execute(
                """
                UPDATE tasks
                SET status = ?, result_id = ?, updated_at = ?, finished_at = ?,
                    lease_owner = NULL, lease_expires_at = NULL,
                    error_code = NULL, error_message = NULL
                WHERE task_id = ?
                """,
                (
                    TaskStatus.COMPLETED.value,
                    result_id,
                    now.isoformat(),
                    now.isoformat(),
                    task_id,
                ),
            )
            connection.execute(
                """
                UPDATE task_attempts
                SET finished_at = ?, status = ?, error_code = NULL, error_message = NULL
                WHERE task_id = ? AND worker_id = ? AND finished_at IS NULL
                """,
                (
                    now.isoformat(),
                    TaskStatus.COMPLETED.value,
                    task_id,
                    worker_id,
                ),
            )
            self._insert_event(
                connection,
                task_id=task_id,
                from_status=current,
                to_status=TaskStatus.COMPLETED,
                reason="worker_completed_with_result",
                trace_id=trace_id,
                created_at=now,
            )
            updated = connection.execute(
                "SELECT * FROM tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            assert updated is not None
            record = self._row_to_record(updated)
            self._append_task_update(
                connection,
                record=record,
                reason="worker_completed_with_result",
                trace_id=trace_id,
                created_at=now,
            )
            self.outbox.append_in_transaction(
                connection,
                topic="result.created",
                payload={
                    "result_id": result_id,
                    "task_id": task_id,
                    "result_type": stored_result.result_type,
                    "object_hash": stored_result.object_hash,
                    "size_bytes": stored_result.size_bytes,
                    "schema_version": schema_version,
                },
                trace_id=trace_id,
                created_at=now,
            )
            return record

    def request_cancel(
        self,
        task_id: str,
        *,
        trace_id: str | None = None,
    ) -> TaskRecord:
        """Queued 立即取消；Running 只写入幂等取消意图。"""

        now = datetime.now(UTC)
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"任务不存在：{task_id}")
            current = TaskStatus(row["status"])
            if current is TaskStatus.CANCELLED:
                return self._row_to_record(row)
            if current is TaskStatus.QUEUED:
                return self.transition_in_transaction(
                    connection,
                    task_id=task_id,
                    target=TaskStatus.CANCELLED,
                    reason="api_cancel",
                    occurred_at=now,
                    trace_id=trace_id,
                )
            if current is not TaskStatus.RUNNING:
                raise InvalidTransitionError(
                    f"只有 Queued 或 Running 任务可以取消，当前为 {current.value}。"
                )
            if self._cancel_requested_in_transaction(connection, task_id):
                return self._row_to_record(row)

            self._insert_event(
                connection,
                task_id=task_id,
                from_status=TaskStatus.RUNNING,
                to_status=TaskStatus.RUNNING,
                reason="cancel_requested",
                trace_id=trace_id,
                created_at=now,
            )
            self.outbox.append_in_transaction(
                connection,
                topic="task.cancel_requested",
                payload={
                    "task_id": task_id,
                    "status": TaskStatus.RUNNING.value,
                    "reason": "cancel_requested",
                },
                trace_id=trace_id,
                created_at=now,
            )
            return self._row_to_record(row)

    def is_cancel_requested(self, task_id: str, *, worker_id: str) -> bool:
        """仅允许当前租约所有者读取 Running 任务的取消意图。"""

        now = datetime.now(UTC)
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            self._assert_active_lease(row, worker_id=worker_id, now=now)
            return self._cancel_requested_in_transaction(connection, task_id)

    def cancel_leased(
        self,
        task_id: str,
        *,
        worker_id: str,
        trace_id: str | None = None,
    ) -> TaskRecord:
        """由当前租约所有者把已请求取消的任务提交为唯一 Cancelled 终态。"""

        now = datetime.now(UTC)
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            self._assert_active_lease(row, worker_id=worker_id, now=now)
            assert row is not None
            if not self._cancel_requested_in_transaction(connection, task_id):
                raise LeaseOwnershipError("任务没有取消意图。")
            current = TaskStatus(row["status"])
            ensure_transition(current, TaskStatus.CANCELLED)

            connection.execute(
                """
                UPDATE tasks
                SET status = ?, updated_at = ?, finished_at = ?,
                    lease_owner = NULL, lease_expires_at = NULL,
                    error_code = ?, error_message = ?
                WHERE task_id = ?
                """,
                (
                    TaskStatus.CANCELLED.value,
                    now.isoformat(),
                    now.isoformat(),
                    "WORKER_TASK_CANCELLED",
                    "任务已取消。",
                    task_id,
                ),
            )
            connection.execute(
                """
                UPDATE task_attempts
                SET finished_at = ?, status = ?, error_code = ?, error_message = ?
                WHERE task_id = ? AND worker_id = ? AND finished_at IS NULL
                """,
                (
                    now.isoformat(),
                    TaskStatus.CANCELLED.value,
                    "WORKER_TASK_CANCELLED",
                    "任务已取消。",
                    task_id,
                    worker_id,
                ),
            )
            self._insert_event(
                connection,
                task_id=task_id,
                from_status=current,
                to_status=TaskStatus.CANCELLED,
                reason="worker_cancelled",
                trace_id=trace_id,
                created_at=now,
            )
            updated = connection.execute(
                "SELECT * FROM tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            assert updated is not None
            record = self._row_to_record(updated)
            self._append_task_update(
                connection,
                record=record,
                reason="worker_cancelled",
                trace_id=trace_id,
                created_at=now,
            )
            return record

    def recover_expired_supported_leases(
        self,
        *,
        supported_task_types: tuple[str, ...],
        now: datetime | None = None,
        limit: int = 100,
    ) -> list[str]:
        """只恢复当前 Worker 明确支持且租约已过期的 Running 任务。"""

        if not supported_task_types:
            return []
        checked_at = now or datetime.now(UTC)
        bounded_limit = max(1, min(int(limit), 1000))
        placeholders = ",".join("?" for _ in supported_task_types)
        recovered: list[str] = []
        with self.database.transaction() as connection:
            rows = connection.execute(
                "SELECT * FROM tasks "
                "WHERE status = ? AND lease_expires_at IS NOT NULL "
                "AND lease_expires_at < ? "
                f"AND task_type IN ({placeholders}) "
                "ORDER BY lease_expires_at ASC, rowid ASC LIMIT ?",
                (
                    TaskStatus.RUNNING.value,
                    checked_at.isoformat(),
                    *supported_task_types,
                    bounded_limit,
                ),
            ).fetchall()
            for row in rows:
                target = (
                    TaskStatus.FAILED
                    if int(row["attempt_count"]) >= int(row["max_attempts"])
                    else TaskStatus.RETRYING
                )
                ensure_transition(TaskStatus.RUNNING, target)
                terminal_at = checked_at.isoformat() if target is TaskStatus.FAILED else None
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = ?, lease_owner = NULL, lease_expires_at = NULL,
                        updated_at = ?, finished_at = COALESCE(?, finished_at),
                        error_code = ?, error_message = ?
                    WHERE task_id = ?
                    """,
                    (
                        target.value,
                        checked_at.isoformat(),
                        terminal_at,
                        "LEASE_EXPIRED",
                        "任务租约过期，已由受控恢复流程处理。",
                        row["task_id"],
                    ),
                )
                connection.execute(
                    """
                    UPDATE task_attempts
                    SET finished_at = ?, status = ?, error_code = ?, error_message = ?
                    WHERE task_id = ? AND finished_at IS NULL
                    """,
                    (
                        checked_at.isoformat(),
                        TaskStatus.FAILED.value,
                        "LEASE_EXPIRED",
                        "任务租约过期。",
                        row["task_id"],
                    ),
                )
                self._insert_event(
                    connection,
                    task_id=row["task_id"],
                    from_status=TaskStatus.RUNNING,
                    to_status=target,
                    reason="lease_expired",
                    trace_id=None,
                    created_at=checked_at,
                )
                updated = connection.execute(
                    "SELECT * FROM tasks WHERE task_id = ?",
                    (row["task_id"],),
                ).fetchone()
                assert updated is not None
                self._append_task_update(
                    connection,
                    record=self._row_to_record(updated),
                    reason="lease_expired",
                    trace_id=None,
                    created_at=checked_at,
                )
                recovered.append(row["task_id"])
        return recovered

    def promote_retries(
        self,
        *,
        supported_task_types: tuple[str, ...],
        limit: int = 100,
        trace_id: str | None = None,
    ) -> list[str]:
        """只把明确支持类型的 Retrying 有界恢复为 Queued。"""

        if not supported_task_types:
            return []
        bounded_limit = max(1, min(int(limit), 1000))
        placeholders = ",".join("?" for _ in supported_task_types)
        promoted: list[str] = []
        with self.database.transaction() as connection:
            rows = connection.execute(
                "SELECT task_id FROM tasks "
                "WHERE status = ? "
                f"AND task_type IN ({placeholders}) "
                "ORDER BY updated_at ASC, rowid ASC LIMIT ?",
                (
                    TaskStatus.RETRYING.value,
                    *supported_task_types,
                    bounded_limit,
                ),
            ).fetchall()
            for row in rows:
                task_id = row["task_id"]
                self.transition_in_transaction(
                    connection,
                    task_id=task_id,
                    target=TaskStatus.QUEUED,
                    reason="retry_ready",
                    trace_id=trace_id,
                )
                promoted.append(task_id)
        return promoted

    @staticmethod
    def _cancel_requested_in_transaction(
        connection: Connection,
        task_id: str,
    ) -> bool:
        row = connection.execute(
            """
            SELECT 1
            FROM task_events
            WHERE task_id = ? AND reason = 'cancel_requested'
            ORDER BY created_at DESC, rowid DESC
            LIMIT 1
            """,
            (task_id,),
        ).fetchone()
        return row is not None

    @staticmethod
    def _row_to_record(row: Row) -> TaskRecord:
        """把 SQLite 行转换为包含 result_id 的稳定领域模型。"""

        return TaskRecord(
            task_id=row["task_id"],
            parent_task_id=row["parent_task_id"],
            project_id=row["project_id"],
            task_type=row["task_type"],
            status=TaskStatus(row["status"]),
            priority=int(row["priority"]),
            resource_tag=row["resource_tag"],
            payload=json.loads(row["payload_json"]),
            result_id=row["result_id"],
            attempt_count=int(row["attempt_count"]),
            max_attempts=int(row["max_attempts"]),
            timeout_seconds=int(row["timeout_seconds"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            error_code=row["error_code"],
            error_message=row["error_message"],
        )
