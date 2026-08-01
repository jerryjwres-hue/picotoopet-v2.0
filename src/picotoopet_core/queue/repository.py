"""SQLite 耐久任务队列仓储。"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from sqlite3 import Connection, Row
from uuid import uuid4

from picotoopet_core.db.database import Database
from picotoopet_core.domain.enums import CloudPolicy, TaskStatus
from picotoopet_core.domain.models import TaskCreate, TaskRecord
from picotoopet_core.events.outbox import EventOutbox

from .state_machine import InvalidTransitionError, ensure_transition


_ACTIVE_DEDUPE_STATUSES = (
    TaskStatus.CREATED,
    TaskStatus.VALIDATING,
    TaskStatus.QUEUED,
    TaskStatus.RUNNING,
    TaskStatus.WAITING_FOR_TOOL,
    TaskStatus.WAITING_FOR_APPROVAL,
    TaskStatus.RETRYING,
)


class QueueRepository:
    """提供任务创建、租约、恢复、事件和状态转换。"""

    def __init__(self, database: Database, *, outbox: EventOutbox | None = None) -> None:
        self.database = database
        self.outbox   = outbox or EventOutbox(database)

    def create(self, request: TaskCreate, *, trace_id: str | None = None) -> TaskRecord:
        """在单一事务中幂等创建任务和对应 Outbox 事件。"""

        with self.database.transaction() as connection:
            return self._create_in_transaction(
                connection,
                request=request,
                trace_id=trace_id,
            )

    def _create_in_transaction(
        self,
        connection: Connection,
        *,
        request: TaskCreate,
        parent_task_id: str | None = None,
        trace_id: str | None = None,
    ) -> TaskRecord:
        """复用调用方事务创建任务，保证关联写入原子提交。"""

        if request.idempotency_key:
            existing = connection.execute(
                "SELECT * FROM tasks WHERE idempotency_key = ?",
                (request.idempotency_key,),
            ).fetchone()
            if existing is not None:
                return self._row_to_record(existing)

        if request.dedupe_key:
            placeholders = ",".join("?" for _ in _ACTIVE_DEDUPE_STATUSES)
            existing = connection.execute(
                f"SELECT * FROM tasks WHERE dedupe_key = ? "
                f"AND status IN ({placeholders}) ORDER BY created_at LIMIT 1",
                (request.dedupe_key, *(status.value for status in _ACTIVE_DEDUPE_STATUSES)),
            ).fetchone()
            if existing is not None:
                return self._row_to_record(existing)

        now          = datetime.now(UTC)
        task_id      = str(uuid4())
        final_status = (
            TaskStatus.WAITING_FOR_APPROVAL
            if request.cloud_policy is CloudPolicy.CLOUD_MANUAL
            else TaskStatus.QUEUED
        )
        connection.execute(
            """
            INSERT INTO tasks (
                task_id, parent_task_id, project_id, task_type, status, priority,
                resource_tag, idempotency_key, dedupe_key, payload_json,
                attempt_count, max_attempts, timeout_seconds, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
            """,
            (
                task_id,
                parent_task_id,
                request.project_id,
                request.task_type,
                final_status.value,
                request.priority,
                request.resource_tag,
                request.idempotency_key,
                request.dedupe_key,
                json.dumps(request.payload, ensure_ascii=False, separators=(",", ":")),
                request.max_attempts,
                request.timeout_seconds,
                now.isoformat(),
                now.isoformat(),
            ),
        )
        reason = "cloud_manual" if final_status is TaskStatus.WAITING_FOR_APPROVAL else "created"
        self._insert_event(
            connection,
            task_id=task_id,
            from_status=None,
            to_status=final_status,
            reason=reason,
            trace_id=trace_id,
            created_at=now,
        )
        row = connection.execute(
            "SELECT * FROM tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        assert row is not None
        record = self._row_to_record(row)
        self._append_task_update(
            connection,
            record=record,
            reason=reason,
            trace_id=trace_id,
            created_at=now,
        )
        return record

    def get(self, task_id: str) -> TaskRecord:
        """读取单个任务，不存在时抛出 KeyError。"""

        row = self.database.fetchone("SELECT * FROM tasks WHERE task_id = ?", (task_id,))
        if row is None:
            raise KeyError(f"任务不存在：{task_id}")
        return self._row_to_record(row)

    def list(
        self,
        status: TaskStatus | None = None,
        *,
        exclude_resource_tag: str | None = None,
        limit: int | None = None,
    ) -> list[TaskRecord]:
        """按创建时间倒序列出任务，并支持桌面快照的受控过滤与限量。"""

        clauses: list[str] = []
        parameters: list[object] = []
        if status is not None:
            clauses.append("status = ?")
            parameters.append(status.value)
        if exclude_resource_tag is not None:
            clauses.append("(resource_tag IS NULL OR resource_tag <> ?)")
            parameters.append(exclude_resource_tag)

        sql = "SELECT * FROM tasks"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC, rowid DESC"
        if limit is not None:
            normalized_limit = max(1, min(int(limit), 5000))
            sql += " LIMIT ?"
            parameters.append(normalized_limit)

        rows = self.database.fetchall(sql, tuple(parameters))
        return [self._row_to_record(row) for row in rows]

    def retry(
        self,
        task_id: str,
        *,
        trace_id: str | None = None,
    ) -> TaskRecord:
        """原子创建失败或取消任务的子任务，不重开原终态记录。"""

        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"任务不存在：{task_id}")
            original = self._row_to_record(row)
            if original.status not in {TaskStatus.FAILED, TaskStatus.CANCELLED}:
                raise InvalidTransitionError("只有 Failed 或 Cancelled 任务可以重试。")
            return self._create_in_transaction(
                connection,
                request=TaskCreate(
                    project_id=original.project_id,
                    task_type=original.task_type,
                    payload=original.payload,
                    priority=original.priority,
                    resource_tag=original.resource_tag,
                    max_attempts=original.max_attempts,
                    timeout_seconds=original.timeout_seconds,
                ),
                parent_task_id=original.task_id,
                trace_id=trace_id,
            )

    def lease_next(
        self,
        worker_id: str,
        lease_seconds: int = 60,
        *,
        trace_id: str | None = None,
    ) -> TaskRecord | None:
        """按优先级领取一个任务，并写入可恢复租约和状态事件。"""

        now          = datetime.now(UTC)
        lease_expiry = now + timedelta(seconds=lease_seconds)
        with self.database.transaction() as connection:
            row = connection.execute(
                """
                SELECT * FROM tasks
                WHERE status = ?
                  AND (not_before IS NULL OR not_before <= ?)
                ORDER BY priority ASC, created_at ASC
                LIMIT 1
                """,
                (TaskStatus.QUEUED.value, now.isoformat()),
            ).fetchone()
            if row is None:
                return None

            task_id = row["task_id"]
            ensure_transition(TaskStatus(row["status"]), TaskStatus.RUNNING)
            connection.execute(
                """
                UPDATE tasks
                SET status = ?, attempt_count = attempt_count + 1,
                    lease_owner = ?, lease_expires_at = ?, started_at = COALESCE(started_at, ?),
                    updated_at = ?
                WHERE task_id = ?
                """,
                (
                    TaskStatus.RUNNING.value,
                    worker_id,
                    lease_expiry.isoformat(),
                    now.isoformat(),
                    now.isoformat(),
                    task_id,
                ),
            )
            reason = f"leased:{worker_id}"
            self._insert_event(
                connection,
                task_id=task_id,
                from_status=TaskStatus.QUEUED,
                to_status=TaskStatus.RUNNING,
                reason=reason,
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
                reason=reason,
                trace_id=trace_id,
                created_at=now,
            )
            return record

    def recover_expired_leases(self, now: datetime | None = None) -> list[str]:
        """恢复租约过期任务；达到重试上限时转为失败。"""

        checked_at = now or datetime.now(UTC)
        recovered: list[str] = []
        with self.database.transaction() as connection:
            rows = connection.execute(
                """
                SELECT * FROM tasks
                WHERE status = ? AND lease_expires_at IS NOT NULL AND lease_expires_at < ?
                ORDER BY lease_expires_at ASC
                """,
                (TaskStatus.RUNNING.value, checked_at.isoformat()),
            ).fetchall()
            for row in rows:
                old_status = TaskStatus(row["status"])
                new_status = (
                    TaskStatus.FAILED
                    if int(row["attempt_count"]) >= int(row["max_attempts"])
                    else TaskStatus.RETRYING
                )
                ensure_transition(old_status, new_status)
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = ?, lease_owner = NULL, lease_expires_at = NULL,
                        updated_at = ?, finished_at = CASE WHEN ? = ? THEN ? ELSE finished_at END,
                        error_code = ?, error_message = ?
                    WHERE task_id = ?
                    """,
                    (
                        new_status.value,
                        checked_at.isoformat(),
                        new_status.value,
                        TaskStatus.FAILED.value,
                        checked_at.isoformat(),
                        "LEASE_EXPIRED",
                        "任务租约过期，已由恢复流程处理。",
                        row["task_id"],
                    ),
                )
                self._insert_event(
                    connection,
                    task_id=row["task_id"],
                    from_status=old_status,
                    to_status=new_status,
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

    def transition(
        self,
        task_id: str,
        target: TaskStatus,
        reason: str,
        *,
        trace_id: str | None = None,
    ) -> TaskRecord:
        """在独立事务中执行受状态机保护的任务转换。"""

        with self.database.transaction() as connection:
            return self.transition_in_transaction(
                connection,
                task_id=task_id,
                target=target,
                reason=reason,
                trace_id=trace_id,
            )

    def transition_in_transaction(
        self,
        connection: Connection,
        *,
        task_id: str,
        target: TaskStatus,
        reason: str,
        occurred_at: datetime | None = None,
        trace_id: str | None = None,
    ) -> TaskRecord:
        """复用调用方事务完成转换，供审批等跨表原子操作使用。"""

        now = occurred_at or datetime.now(UTC)
        row = connection.execute(
            "SELECT * FROM tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"任务不存在：{task_id}")

        current = TaskStatus(row["status"])
        ensure_transition(current, target)
        terminal_at = now.isoformat() if target in {
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        } else None
        connection.execute(
            """
            UPDATE tasks
            SET status = ?, updated_at = ?,
                finished_at = COALESCE(?, finished_at),
                lease_owner = CASE WHEN ? = ? THEN lease_owner ELSE NULL END,
                lease_expires_at = CASE WHEN ? = ? THEN lease_expires_at ELSE NULL END
            WHERE task_id = ?
            """,
            (
                target.value,
                now.isoformat(),
                terminal_at,
                target.value,
                TaskStatus.RUNNING.value,
                target.value,
                TaskStatus.RUNNING.value,
                task_id,
            ),
        )
        self._insert_event(
            connection,
            task_id=task_id,
            from_status=current,
            to_status=target,
            reason=reason,
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
            reason=reason,
            trace_id=trace_id,
            created_at=now,
        )
        return record

    def _append_task_update(
        self,
        connection: Connection,
        *,
        record: TaskRecord,
        reason: str,
        trace_id: str | None,
        created_at: datetime,
    ) -> None:
        """把当前任务快照加入与业务事务一致的 Outbox。"""

        payload = record.model_dump(mode="json")
        payload["reason"] = reason
        self.outbox.append_in_transaction(
            connection,
            topic="task.updated",
            payload=payload,
            trace_id=trace_id,
            created_at=created_at,
        )

    @staticmethod
    def _insert_event(
        connection: Connection,
        *,
        task_id: str,
        from_status: TaskStatus | None,
        to_status: TaskStatus,
        reason: str,
        trace_id: str | None,
        created_at: datetime,
    ) -> None:
        """追加不可变任务状态事件。"""

        connection.execute(
            """
            INSERT INTO task_events (
                event_id, task_id, from_status, to_status, reason, trace_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid4()),
                task_id,
                None if from_status is None else from_status.value,
                to_status.value,
                reason,
                trace_id,
                created_at.isoformat(),
            ),
        )

    @staticmethod
    def _row_to_record(row: Row) -> TaskRecord:
        """把 SQLite 行转换为稳定领域模型。"""

        return TaskRecord(
            task_id=row["task_id"],
            parent_task_id=row["parent_task_id"],
            project_id=row["project_id"],
            task_type=row["task_type"],
            status=TaskStatus(row["status"]),
            priority=int(row["priority"]),
            resource_tag=row["resource_tag"],
            payload=json.loads(row["payload_json"]),
            attempt_count=int(row["attempt_count"]),
            max_attempts=int(row["max_attempts"]),
            timeout_seconds=int(row["timeout_seconds"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            error_code=row["error_code"],
            error_message=row["error_message"],
        )
