"""SQLite 项目仓储。"""

from __future__ import annotations

from datetime import UTC, datetime
from sqlite3 import Row
from uuid import uuid4

from picotoopet_core.db.database import Database
from picotoopet_core.domain.enums import Classification
from picotoopet_core.domain.models import ProjectCreate, ProjectRecord


class ProjectRepository:
    """创建和读取 V2 项目元数据。"""

    def __init__(self, database: Database) -> None:
        self.database = database

    def create(self, request: ProjectCreate) -> ProjectRecord:
        """创建项目，不触碰 workspace_root 指向的数据。"""

        now        = datetime.now(UTC)
        project_id = str(uuid4())
        self.database.execute(
            """
            INSERT INTO projects (
                project_id, title, project_type, source_app, classification,
                workspace_root, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                request.title,
                request.project_type,
                request.source_app,
                request.classification.value,
                request.workspace_root,
                "Active",
                now.isoformat(),
                now.isoformat(),
            ),
        )
        return self.get(project_id)

    def get(self, project_id: str) -> ProjectRecord:
        """读取项目。"""

        row = self.database.fetchone("SELECT * FROM projects WHERE project_id = ?", (project_id,))
        if row is None:
            raise KeyError(f"项目不存在：{project_id}")
        return self._row_to_record(row)

    def list(self) -> list[ProjectRecord]:
        """按创建时间倒序列出项目。"""

        rows = self.database.fetchall("SELECT * FROM projects ORDER BY created_at DESC")
        return [self._row_to_record(row) for row in rows]

    @staticmethod
    def _row_to_record(row: Row) -> ProjectRecord:
        """把 SQLite 行转换为领域模型。"""

        return ProjectRecord(
            project_id=row["project_id"],
            title=row["title"],
            project_type=row["project_type"],
            source_app=row["source_app"],
            classification=Classification(row["classification"]),
            workspace_root=row["workspace_root"],
            status=row["status"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
