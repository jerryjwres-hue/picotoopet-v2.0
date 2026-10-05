"""The production Worker CLI must bind the live adaptive budget, not a test-only stub."""

from __future__ import annotations

from types import SimpleNamespace

import picotoopet_core.cli as cli
from picotoopet_core.diagnostics.reliability import MemoryPressureSummary
from picotoopet_core.ollama.client import OllamaProcessSnapshot


class _FakeOllamaClient:
    def __init__(self, base_url: str, *, timeout_seconds: float) -> None:
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.closed = False

    def process_snapshot(self) -> OllamaProcessSnapshot:
        return OllamaProcessSnapshot(loaded_model_count=2, models=())

    def close(self) -> None:
        self.closed = True


def test_worker_cli_builds_live_adaptive_model_budget(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(cli, "OllamaClient", _FakeOllamaClient)
    monkeypatch.setattr(
        cli,
        "observe_memory_pressure",
        lambda: MemoryPressureSummary(level="warn", source="test"),
        raising=False,
    )
    builder = getattr(cli, "_build_autonomous_model_budget", None)
    assert callable(builder), "Worker CLI must expose the bounded live budget assembly helper"

    provider, client = builder(
        SimpleNamespace(local_intelligence_base_url="http://127.0.0.1:11434")
    )
    budget = provider(5_000)

    assert budget.memory_pressure == "warn"
    assert budget.loaded_model_count == 2
    assert budget.max_concurrency == 1
    assert budget.max_input_chars < 23_000
    assert client.base_url == "http://127.0.0.1:11434"
    assert client.timeout_seconds <= 2.0
