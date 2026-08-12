from __future__ import annotations

import importlib
import importlib.util

import pytest


def _module(name: str):  # type: ignore[no-untyped-def]
    if importlib.util.find_spec(name) is None:
        pytest.fail(f"{name} is not implemented")
    return importlib.import_module(name)


def test_worker_paid_ai_config_is_disabled_without_explicit_opt_in_or_key() -> None:
    module = _module("picotoopet_core.deep_ai.provider")
    empty = module.DeepAiWorkerProviderConfig.from_environment({})
    assert empty.execution_enabled is False
    assert empty.api_key is None
    assert empty.provider_profile_id == "paid.reasoning.v1"
    assert empty.model_id == "gpt-5.6-terra"
    assert empty.endpoint == "https://api.openai.com/v1/responses"

    key_only = module.DeepAiWorkerProviderConfig.from_environment(
        {"OPENAI_API_KEY": "test-secret-not-real"}
    )
    assert key_only.execution_enabled is False


def test_worker_paid_ai_config_has_no_endpoint_or_model_environment_override() -> None:
    module = _module("picotoopet_core.deep_ai.provider")
    configured = module.DeepAiWorkerProviderConfig.from_environment(
        {
            "PICOTOOPET_PAID_AI_EXECUTION_ENABLED": "1",
            "OPENAI_API_KEY": "test-secret-not-real",
            "PICOTOOPET_PAID_AI_ENDPOINT": "https://evil.invalid/v1/responses",
            "PICOTOOPET_PAID_AI_MODEL": "attacker-model",
        }
    )
    assert configured.execution_enabled is True
    assert configured.endpoint == "https://api.openai.com/v1/responses"
    assert configured.model_id == "gpt-5.6-terra"
    assert configured.api_key is not None


def test_worker_paid_ai_config_refuses_enabled_without_key() -> None:
    module = _module("picotoopet_core.deep_ai.provider")
    with pytest.raises(ValueError, match="DEEP_AI_API_KEY_REQUIRED"):
        module.DeepAiWorkerProviderConfig.from_environment(
            {"PICOTOOPET_PAID_AI_EXECUTION_ENABLED": "1"}
        )
