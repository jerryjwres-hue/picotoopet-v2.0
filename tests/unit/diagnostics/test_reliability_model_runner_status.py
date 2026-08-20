"""Reliability diagnostics must consume only the sanitized model-runner status projection."""

from __future__ import annotations

from pathlib import Path

from picotoopet_core.db.database import Database
from picotoopet_core.diagnostics.reliability import (
    MemoryPressureSummary,
    ReliabilityFaultCode,
)
from picotoopet_core.diagnostics.reliability_bundle import ReliabilityBundleBuilder
from picotoopet_core.diagnostics.reliability_service import ReliabilityService
from picotoopet_core.ollama.client import OllamaProcessSnapshot, OllamaVersionObservation
from picotoopet_core.ollama.model_runner import ModelRunnerStatus
from picotoopet_core.progress.repository import ProgressRepository
from picotoopet_core.worker.state import WorkerStateStore


class _HealthyOllama:
    def version_info(self) -> OllamaVersionObservation:
        return OllamaVersionObservation(version="0.0-test")

    def process_snapshot(self) -> OllamaProcessSnapshot:
        return OllamaProcessSnapshot(loaded_model_count=0, models=())


def _service(tmp_path: Path, status: ModelRunnerStatus) -> tuple[ReliabilityService, Database]:
    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()

    worker_state = WorkerStateStore(tmp_path / "state" / "worker-status.json")
    worker_state.publish(
        state="online",
        reason="idle",
        worker_id="worker-test",
        supported_task_types=(),
        active_task_id=None,
    )
    status_path = tmp_path / "runtime" / "model-runner" / "status.json"
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(status.model_dump_json(), encoding="utf-8")

    service = ReliabilityService(
        database=database,
        worker_state=worker_state,
        ollama=_HealthyOllama(),  # type: ignore[arg-type]
        progress=ProgressRepository(database),
        bundle_builder=ReliabilityBundleBuilder(
            managed_output_dir=tmp_path / "diagnostics",
            home_dir=tmp_path,
        ),
        memory_pressure=lambda: MemoryPressureSummary(level="normal", source="test"),
        model_runner_status_path=status_path,
    )
    return service, database


def test_model_runner_timeout_is_projected_as_reliability_fault(tmp_path: Path) -> None:
    service, database = _service(
        tmp_path,
        ModelRunnerStatus(
            outcome="timeout",
            consecutive_failures=1,
            circuit_open=False,
        ),
    )
    try:
        snapshot = service.snapshot()
    finally:
        database.close()

    assert snapshot.primary_fault is ReliabilityFaultCode.MODEL_JOB_TIMEOUT
    assert snapshot.status == "failed"


def test_model_runner_invalid_result_is_projected_as_reliability_fault(
    tmp_path: Path,
) -> None:
    service, database = _service(
        tmp_path,
        ModelRunnerStatus(
            outcome="result_invalid",
            consecutive_failures=1,
            circuit_open=False,
        ),
    )
    try:
        snapshot = service.snapshot()
    finally:
        database.close()

    assert snapshot.primary_fault is ReliabilityFaultCode.MODEL_OUTPUT_INVALID
    assert snapshot.status == "failed"
