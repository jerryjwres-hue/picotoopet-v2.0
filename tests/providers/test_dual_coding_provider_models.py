from __future__ import annotations

import pytest
from pydantic import ValidationError

from picotoopet_core.providers.models import (
    ProviderBudget,
    ProviderReadinessStatus,
    ProviderStatusRecord,
)


def test_provider_status_accepts_only_codex_and_claude_code() -> None:
    for provider in ("codex", "claude_code"):
        record = ProviderStatusRecord(
            provider=provider,
            readiness=ProviderReadinessStatus.READY,
            message=f"{provider} ready",
        )
        assert record.provider == provider

    with pytest.raises(ValidationError):
        ProviderStatusRecord(
            provider="arbitrary-provider",
            readiness=ProviderReadinessStatus.READY,
            message="must not validate",
        )


def test_shared_coding_provider_budget_remains_strictly_frugal() -> None:
    budget = ProviderBudget()

    assert budget.max_turns == 8
    assert budget.timeout_seconds == 900
    assert budget.max_changed_files == 5
    assert budget.max_file_bytes == 65536
    assert budget.max_return_bytes == 262144
    assert budget.automatic_retries == 0
    assert budget.concurrency == 1
    assert budget.network_tools_allowed is False

    for override in (
        {"max_turns": 9},
        {"automatic_retries": 1},
        {"concurrency": 2},
        {"network_tools_allowed": True},
    ):
        with pytest.raises(ValidationError):
            ProviderBudget(**override)
