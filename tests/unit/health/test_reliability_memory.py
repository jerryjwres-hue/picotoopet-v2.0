"""Health supervision must expose coarse memory pressure without process dumps."""

from pathlib import Path

from picotoopet_core.config.paths import RuntimePaths
from picotoopet_core.db.database import Database
from picotoopet_core.diagnostics.reliability import MemoryPressureSummary
from picotoopet_core.health.supervisor import HealthSupervisor
from picotoopet_core.ollama.resident_manager import ResidentResult, ResidentStatus


class FakeResident:
    def ensure_resident(self) -> ResidentResult:
        return ResidentResult(
            status=ResidentStatus.RESIDENT,
            model_name="gpt-oss:20b",
            detail="test",
        )


def _database(tmp_path: Path) -> tuple[RuntimePaths, Database]:
    paths = RuntimePaths.from_root(tmp_path / "runtime")
    paths.ensure()
    database = Database(paths.database_file)
    database.open()
    database.apply_migrations()
    return paths, database


def test_high_memory_pressure_degrades_health_without_exposing_process_data(
    tmp_path: Path,
) -> None:
    paths, database = _database(tmp_path)
    supervisor = HealthSupervisor(
        database=database,
        paths=paths,
        resident=FakeResident(),
        memory_pressure=lambda: MemoryPressureSummary(
            level="high",
            source="fixture",
            available_bytes=512 * 1024 * 1024,
        ),
    )

    report = supervisor.run_once()

    assert report.status == "degraded"
    assert report.checks["memory_pressure"].status == "degraded"
    assert report.checks["memory_pressure"].detail == "high"
    assert database.scalar(
        "SELECT detail FROM service_health WHERE service_name = 'memory_pressure'"
    ) == "high"
    database.close()


def test_unknown_memory_pressure_is_recorded_but_not_invented_as_failure(tmp_path: Path) -> None:
    paths, database = _database(tmp_path)
    supervisor = HealthSupervisor(
        database=database,
        paths=paths,
        resident=FakeResident(),
        memory_pressure=lambda: MemoryPressureSummary(level="unknown", source="unsupported"),
    )

    report = supervisor.run_once()

    assert report.status == "ok"
    assert report.checks["memory_pressure"].status == "unknown"
    assert report.checks["memory_pressure"].detail == "unknown"
    database.close()
