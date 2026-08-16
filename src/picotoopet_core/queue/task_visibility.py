"""用户可恢复的任务可见性；与执行状态完全正交。"""

from __future__ import annotations

from datetime import UTC, datetime

from picotoopet_core.db.database import Database
from picotoopet_core.domain.models import TaskRecord


class TaskVisibilityRepository:
    """持久化“从普通列表隐藏/恢复”事实，不删除任务或结果。"""

    def __init__(self, database: Database) -> None:
        self._database = database

    def is_hidden(self, task_id: str) -> bool:
        row = self._database.fetchone(
            "SELECT is_hidden FROM task_visibility WHERE task_id = ?",
            (task_id,),
        )
        return row is not None and bool(row["is_hidden"])

    def set_hidden(self, task_id: str, *, hidden: bool) -> None:
        now = datetime.now(UTC).isoformat()
        with self._database.transaction() as connection:
            exists = connection.execute(
                "SELECT 1 FROM tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if exists is None:
                raise KeyError(f"任务不存在：{task_id}")
            connection.execute(
                """
                INSERT INTO task_visibility(task_id, is_hidden, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    is_hidden = excluded.is_hidden,
                    updated_at = excluded.updated_at
                """,
                (task_id, 1 if hidden else 0, now),
            )

    def decorate(self, task: TaskRecord) -> TaskRecord:
        """把持久化可见性投影进 API TaskRecord。"""

        return task.model_copy(update={"is_hidden": self.is_hidden(task.task_id)})

    def decorate_many(self, tasks: list[TaskRecord]) -> list[TaskRecord]:
        if not tasks:
            return []
        task_ids = [task.task_id for task in tasks]
        placeholders = ",".join("?" for _ in task_ids)
        rows = self._database.fetchall(
            f"SELECT task_id, is_hidden FROM task_visibility "
            f"WHERE task_id IN ({placeholders})",
            task_ids,
        )
        hidden = {row["task_id"]: bool(row["is_hidden"]) for row in rows}
        return [
            task.model_copy(update={"is_hidden": hidden.get(task.task_id, False)})
            for task in tasks
        ]
