"""Adaptive local-model input budgeting must only tighten resource use."""

from __future__ import annotations

from picotoopet_core.ollama.budget import ModelInputBudget, plan_model_input_budget


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
