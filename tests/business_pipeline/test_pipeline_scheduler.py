from __future__ import annotations

import importlib
import importlib.util
from types import SimpleNamespace

import pytest


def _scheduler_type():  # type: ignore[no-untyped-def]
    if importlib.util.find_spec("picotoopet_core.business_pipeline.scheduler") is None:
        pytest.fail("2.3.21.1 BusinessPipelineScheduler is not implemented")
    return importlib.import_module("picotoopet_core.business_pipeline.scheduler").BusinessPipelineScheduler


class _PipelineFake:
    def __init__(self) -> None:
        self.runs = [
            SimpleNamespace(pipeline_run_id="run-1"),
            SimpleNamespace(pipeline_run_id="run-2"),
            SimpleNamespace(pipeline_run_id="run-3"),
        ]
        self.reconciled: list[str] = []

    def list_runs(self, *, limit: int = 100):  # type: ignore[no-untyped-def]
        assert limit == 200
        return self.runs

    def reconcile(self, pipeline_run_id: str):  # type: ignore[no-untyped-def]
        self.reconciled.append(pipeline_run_id)
        if pipeline_run_id == "run-2":
            raise RuntimeError("simulated one-run failure")
        return SimpleNamespace(pipeline_run_id=pipeline_run_id)


def test_scheduler_reconciles_all_and_isolates_one_run_failure() -> None:
    service = _PipelineFake()
    scheduler = _scheduler_type()(service)
    reconciled = scheduler.reconcile_all(limit=200)
    assert service.reconciled == ["run-1", "run-2", "run-3"]
    assert [item.pipeline_run_id for item in reconciled] == ["run-1", "run-3"]
