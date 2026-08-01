"""数据库、磁盘和 Ollama 常驻状态监督。"""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from typing import Protocol

from pydantic import BaseModel

from picotoopet_core.config.paths import RuntimePaths
from picotoopet_core.db.database import Database
from picotoopet_core.ollama.resident_manager import ResidentResult, ResidentStatus


class ResidentLike(Protocol):
    """健康监督器依赖的最小常驻管理接口。"""

    def ensure_resident(self) -> ResidentResult:
        """检查并恢复核心模型。"""


class HealthCheck(BaseModel):
    """单项健康检查。"""

    status: str
    detail: str


class HealthReport(BaseModel):
    """一次完整监督结果。"""

    status: str
    checked_at: datetime
    checks: dict[str, HealthCheck]


class HealthSupervisor:
    """执行本地健康检查并持久化脱敏结果。"""

    def __init__(
        self,
        *,
        database: Database,
        paths: RuntimePaths,
        resident: ResidentLike,
        minimum_free_bytes: int = 5 * 1024**3,
    ) -> None:
        self.database           = database
        self.paths              = paths
        self.resident           = resident
        self.minimum_free_bytes = minimum_free_bytes

    def run_once(self) -> HealthReport:
        """运行一次检查；异常转为 degraded，不让守护进程崩溃。"""

        checked_at = datetime.now(UTC)
        checks: dict[str, HealthCheck] = {}

        try:
            database_ok = self.database.scalar("SELECT 1") == 1
            checks["database"] = HealthCheck(
                status="ok" if database_ok else "error",
                detail="SQLite 可读写。" if database_ok else "SQLite 检查失败。",
            )
        except Exception as exc:  # noqa: BLE001 - 健康层必须聚合异常
            checks["database"] = HealthCheck(
                status="error",
                detail=f"SQLite 异常：{type(exc).__name__}",
            )

        try:
            free_bytes = shutil.disk_usage(self.paths.root).free
            disk_ok    = free_bytes >= self.minimum_free_bytes
            checks["disk"] = HealthCheck(
                status="ok" if disk_ok else "degraded",
                detail=f"可用空间 {free_bytes} 字节。",
            )
        except Exception as exc:  # noqa: BLE001 - 健康层必须聚合异常
            checks["disk"] = HealthCheck(
                status="error",
                detail=f"磁盘检查异常：{type(exc).__name__}",
            )

        resident_result = self.resident.ensure_resident()
        checks["ollama_resident"] = HealthCheck(
            status="ok" if resident_result.status is ResidentStatus.RESIDENT else "degraded",
            detail=resident_result.detail,
        )

        for name, check in checks.items():
            self.database.execute(
                """
                INSERT INTO service_health(service_name, status, details_json, checked_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(service_name) DO UPDATE SET
                    status = excluded.status,
                    details_json = excluded.details_json,
                    checked_at = excluded.checked_at
                """,
                (
                    name,
                    check.status,
                    json.dumps({"detail": check.detail}, ensure_ascii=False, separators=(",", ":")),
                    checked_at.isoformat(),
                ),
            )

        overall = "ok" if all(check.status == "ok" for check in checks.values()) else "degraded"
        return HealthReport(status=overall, checked_at=checked_at, checks=checks)
