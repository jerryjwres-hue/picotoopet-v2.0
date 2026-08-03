"""结果元数据只读仓储。"""

from __future__ import annotations

import json
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from picotoopet_core.db.database import Database


class ResultRecord(BaseModel):
    """SQLite results 行的稳定公共模型。"""

    model_config = ConfigDict(frozen=True)

    result_id: str
    project_id: str | None
    task_id: str
    result_type: str
    object_hash: str
    manifest: dict[str, object]
    schema_version: str
    created_at: datetime


class ResultRepository:
    """只通过标识符读取结果元数据，不返回文件路径。"""

    def __init__(self, database: Database) -> None:
        self.database = database

    def get(self, result_id: str) -> ResultRecord:
        row = self.database.fetchone(
            "SELECT * FROM results WHERE result_id = ?",
            (result_id,),
        )
        if row is None:
            raise KeyError(f"结果不存在：{result_id}")
        return self._row_to_record(row)

    def get_for_task(self, task_id: str) -> ResultRecord:
        row = self.database.fetchone(
            "SELECT * FROM results WHERE task_id = ? ORDER BY created_at DESC LIMIT 1",
            (task_id,),
        )
        if row is None:
            raise KeyError(f"任务结果不存在：{task_id}")
        return self._row_to_record(row)

    @staticmethod
    def _row_to_record(row) -> ResultRecord:  # type: ignore[no-untyped-def]
        return ResultRecord(
            result_id=row["result_id"],
            project_id=row["project_id"],
            task_id=row["task_id"],
            result_type=row["result_type"],
            object_hash=row["object_hash"],
            manifest=json.loads(row["manifest_json"]),
            schema_version=row["schema_version"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )
