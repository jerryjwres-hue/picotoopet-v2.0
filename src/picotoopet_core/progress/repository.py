"""SQLite repository for durable truthful task progress."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from sqlite3 import Row

from picotoopet_core.db.database import Database

from .models import ProgressEvent, ProgressSnapshot, ProgressUpdate


def _json(value: object) -> str:
    """Canonical JSON keeps diagnostic comparisons deterministic."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class ProgressRepository:
    """Append-only progress facts; callers never choose event sequence numbers."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def append(self, update: ProgressUpdate) -> ProgressEvent:
        """Atomically allocate the next per-task sequence and persist one event."""

        now = datetime.now(UTC)
        with self.database.transaction() as connection:
            task = connection.execute(
                "SELECT 1 FROM tasks WHERE task_id = ?",
                (update.task_id,),
            ).fetchone()
            if task is None:
                raise KeyError(f"task not found: {update.task_id}")
            sequence = int(
                connection.execute(
                    "SELECT COALESCE(MAX(sequence), 0) + 1 "
                    "FROM task_progress_events WHERE task_id = ?",
                    (update.task_id,),
                ).fetchone()[0]
            )
            connection.execute(
                """
                INSERT INTO task_progress_events (
                    task_id, sequence, stage, completed, total, message,
                    component, details_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    update.task_id,
                    sequence,
                    update.stage,
                    update.completed,
                    update.total,
                    update.message,
                    update.component,
                    _json(update.details),
                    now.isoformat(),
                ),
            )
        return ProgressEvent(
            task_id=update.task_id,
            sequence=sequence,
            stage=update.stage,
            completed=update.completed,
            total=update.total,
            message=update.message,
            component=update.component,
            details=update.details,
            created_at=now,
        )

    def snapshot(self, task_id: str, *, recent_limit: int = 50) -> ProgressSnapshot:
        """Return a bounded current snapshot without inventing elapsed-time progress."""

        if not task_id.strip() or len(task_id) > 200:
            raise ValueError("task_id must be 1-200 characters")
        task = self.database.fetchone("SELECT 1 FROM tasks WHERE task_id = ?", (task_id,))
        if task is None:
            raise KeyError(f"task not found: {task_id}")

        bounded = max(1, min(int(recent_limit), 50))
        rows = self.database.fetchall(
            """
            SELECT * FROM task_progress_events
            WHERE task_id = ?
            ORDER BY sequence DESC
            LIMIT ?
            """,
            (task_id, bounded),
        )
        if not rows:
            return ProgressSnapshot(task_id=task_id)

        events = [self._row_to_event(row) for row in reversed(rows)]
        latest = events[-1]
        percent = None
        if latest.completed is not None and latest.total is not None:
            percent = round((latest.completed / latest.total) * 100.0, 2)
        return ProgressSnapshot(
            task_id=task_id,
            stage=latest.stage,
            completed=latest.completed,
            total=latest.total,
            percent=percent,
            latest_message=latest.message,
            component=latest.component,
            last_activity_at=latest.created_at,
            recent_events=events,
        )

    @staticmethod
    def _row_to_event(row: Row) -> ProgressEvent:
        return ProgressEvent(
            task_id=row["task_id"],
            sequence=int(row["sequence"]),
            stage=row["stage"],
            completed=row["completed"],
            total=row["total"],
            message=row["message"],
            component=row["component"],
            details=json.loads(row["details_json"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )
