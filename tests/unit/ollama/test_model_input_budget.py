"""Adaptive local-model input budgeting must only tighten resource use."""

from __future__ import annotations

from picotoopet_core.diagnostics.reliability import MemoryPressureSummary
from picotoopet_core.ollama.budget import (
    AdaptiveModelInputBudgetProvider,
    ModelInputBudget,
    plan_model_input_budget,
)
from picotoopet_core.ollama.client import OllamaProcessSnapshot


def test_high_memory_pressure_reduces_input_budget_and_keeps_single_concurrency() -> None:
    normal = plan_model_input_budget(
        estimated_tokens=5_000,
        memory_pressure="normal",
        loaded_model_count=1,
    )
    warn = plan_model_input_budget(
        estimated_tokens=5_000,
        memory_pressure="warn",
        loaded_model_count=1,
    )
    high = plan_model_input_budget(
        estimated_tokens=5_000,
        memory_pressure="high",
        loaded_model_count=1,
    )

    assert isinstance(normal, ModelInputBudget)
    assert normal.max_concurrency == warn.max_concurrency == high.max_concurrency == 1
    assert normal.max_input_chars > warn.max_input_chars > high.max_input_chars
    assert normal.max_estimated_tokens > warn.max_estimated_tokens > high.max_estimated_tokens


def test_loaded_models_can_only_tighten_budget_never_expand_context() -> None:
    one_model = plan_model_input_budget(
        estimated_tokens=8_000,
        memory_pressure="normal",
        loaded_model_count=1,
    )
    three_models = plan_model_input_budget(
        estimated_tokens=8_000,
        memory_pressure="normal",
        loaded_model_count=3,
    )

    assert three_models.max_concurrency == 1
    assert three_models.max_input_chars <= one_model.max_input_chars
    assert three_models.max_estimated_tokens <= one_model.max_estimated_tokens
    assert three_models.max_input_chars <= 23_000


def test_live_provider_uses_memory_pressure_and_loaded_model_count() -> None:
    provider = AdaptiveModelInputBudgetProvider(
        memory_pressure=lambda: MemoryPressureSummary(level="high", source="test"),
        process_snapshot=lambda: OllamaProcessSnapshot(loaded_model_count=3, models=()),
    )

    observed = provider(8_000)
    expected = plan_model_input_budget(
        estimated_tokens=8_000,
        memory_pressure="high",
        loaded_model_count=3,
    )

    assert observed == expected
    assert observed.max_concurrency == 1


def test_live_provider_probe_failures_fall_back_to_conservative_unknown_budget() -> None:
    def unavailable():  # type: ignore[no-untyped-def]
        raise OSError("probe unavailable")

    provider = AdaptiveModelInputBudgetProvider(
        memory_pressure=unavailable,
        process_snapshot=unavailable,
    )

    observed = provider(5_000)
    warn_baseline = plan_model_input_budget(
        estimated_tokens=5_000,
        memory_pressure="warn",
        loaded_model_count=1,
    )

    assert observed.memory_pressure == "unknown"
    assert observed.loaded_model_count == 1
    assert observed.max_input_chars <= warn_baseline.max_input_chars
    assert observed.max_concurrency == 1
