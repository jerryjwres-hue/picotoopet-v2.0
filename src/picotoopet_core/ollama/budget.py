"""Conservative adaptive budgeting for bounded local-model input."""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from picotoopet_core.diagnostics.reliability import MemoryPressureSummary
from picotoopet_core.ollama.client import OllamaProcessSnapshot

MemoryPressureLevel = Literal["unknown", "normal", "warn", "high"]

_BASE_MAX_INPUT_CHARS = 23_000
_BASE_MAX_ESTIMATED_TOKENS = 5_750
_MIN_MAX_INPUT_CHARS = 4_000
_MIN_MAX_ESTIMATED_TOKENS = 1_000
_VALID_PRESSURE_LEVELS = frozenset({"unknown", "normal", "warn", "high"})


class ModelInputBudget(BaseModel):
    """Resource-derived limits that may tighten but never expand the local context."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    estimated_tokens: int = Field(ge=0, le=1_000_000)
    memory_pressure: MemoryPressureLevel
    loaded_model_count: int = Field(ge=0, le=100_000)
    max_estimated_tokens: int = Field(ge=_MIN_MAX_ESTIMATED_TOKENS, le=_BASE_MAX_ESTIMATED_TOKENS)
    max_input_chars: int = Field(ge=_MIN_MAX_INPUT_CHARS, le=_BASE_MAX_INPUT_CHARS)
    max_concurrency: int = Field(default=1, ge=1, le=1)
    requires_chunking: bool


class AdaptiveModelInputBudgetProvider:
    """Read only coarse live resource facts and fail closed to a conservative budget."""

    def __init__(
        self,
        *,
        memory_pressure: Callable[[], MemoryPressureSummary],
        process_snapshot: Callable[[], OllamaProcessSnapshot],
    ) -> None:
        self._memory_pressure = memory_pressure
        self._process_snapshot = process_snapshot

    def __call__(self, estimated_tokens: int) -> ModelInputBudget:
        pressure: MemoryPressureLevel = "unknown"
        loaded_model_count = 1

        try:
            observed_pressure = self._memory_pressure().level
            if observed_pressure in _VALID_PRESSURE_LEVELS:
                pressure = observed_pressure
        except Exception:
            pressure = "unknown"

        try:
            snapshot = self._process_snapshot()
            loaded_model_count = max(1, int(snapshot.loaded_model_count))
        except Exception:
            loaded_model_count = 1

        return plan_model_input_budget(
            estimated_tokens=estimated_tokens,
            memory_pressure=pressure,
            loaded_model_count=loaded_model_count,
        )


def plan_model_input_budget(
    *,
    estimated_tokens: int,
    memory_pressure: MemoryPressureLevel,
    loaded_model_count: int,
) -> ModelInputBudget:
    """Return one deterministic single-model budget from coarse, non-secret resource facts."""

    if estimated_tokens < 0:
        raise ValueError("estimated_tokens must be non-negative")
    if loaded_model_count < 0:
        raise ValueError("loaded_model_count must be non-negative")

    pressure_factor = {
        "normal": 1.00,
        "warn": 0.75,
        "high": 0.50,
        "unknown": 0.75,
    }[memory_pressure]
    if loaded_model_count <= 1:
        loaded_model_factor = 1.00
    elif loaded_model_count == 2:
        loaded_model_factor = 0.85
    else:
        loaded_model_factor = 0.70

    factor = min(1.0, pressure_factor, loaded_model_factor)
    max_estimated_tokens = max(
        _MIN_MAX_ESTIMATED_TOKENS,
        int(_BASE_MAX_ESTIMATED_TOKENS * factor),
    )
    max_input_chars = max(
        _MIN_MAX_INPUT_CHARS,
        min(_BASE_MAX_INPUT_CHARS, max_estimated_tokens * 4),
    )
    return ModelInputBudget(
        estimated_tokens=min(estimated_tokens, 1_000_000),
        memory_pressure=memory_pressure,
        loaded_model_count=min(loaded_model_count, 100_000),
        max_estimated_tokens=max_estimated_tokens,
        max_input_chars=max_input_chars,
        max_concurrency=1,
        requires_chunking=estimated_tokens > max_estimated_tokens,
    )
