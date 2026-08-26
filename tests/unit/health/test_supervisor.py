from pathlib import Path

from picotoopet_core.config.paths import RuntimePaths
from picotoopet_core.db.database import Database
from picotoopet_core.diagnostics.reliability import MemoryPressureSummary
from picotoopet_core.health.supervisor import HealthSupervisor
from picotoopet_core.ollama.resident_manager import ResidentResult, ResidentStatus


class FakeResident:
    def __init__(self, status: ResidentStatus) -> None:
        self.status = status
        self.calls  = 0

    def ensure_resident(self) -> ResidentResult:
        self.calls += 1
        return ResidentResult(status=self.status, model_name="gpt-oss:20b", detail="test")


def _normal_memory() -> MemoryPressureSummary:
    # ── Unit tests must not depend on the hosted runner's live memory pressure. ──
    return MemoryPressureSummary(level="normal", source="fixture")


def test_supervisor_aggregates_database_disk_memory_and_resident_health(tmp_path: Path) -> None:
    """健康监督器必须检查数据库、磁盘、内存压力和核心模型并持久化结果。"""

    paths = RuntimePaths.from_root(tmp_path / "runtime")
    paths.ensure()
    database = Database(paths.database_file)
    database.open()
    database.apply_migrations()
    resident = FakeResident(ResidentStatus.RESIDENT)
    supervisor = HealthSupervisor(
        database=database,
        paths=paths,
        resident=resident,
        memory_pressure=_normal_memory,
    )

    report = supervisor.run_once()

    assert report.status == "ok"
    assert report.checks["database"].status == "ok"
    assert report.checks["disk"].status == "ok"
    assert report.checks["memory_pressure"].status == "ok"
    assert report.checks["ollama_resident"].status == "ok"
    assert resident.calls == 1
    assert database.scalar("SELECT COUNT(*) FROM service_health") == 4
    database.close()


def test_supervisor_is_degraded_when_model_is_missing(tmp_path: Path) -> None:
    """核心模型缺失必须明确标记为 degraded，而不是虚报正常。"""

    paths = RuntimePaths.from_root(tmp_path / "runtime")
    paths.ensure()
    database = Database(paths.database_file)
    database.open()
    database.apply_migrations()
    supervisor = HealthSupervisor(
        database=database,
        paths=paths,
        resident=FakeResident(ResidentStatus.MODEL_MISSING),
        memory_pressure=_normal_memory,
    )

    assert supervisor.run_once().status == "degraded"
    database.close()
