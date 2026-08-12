from __future__ import annotations

import importlib
import importlib.util
import json

import pytest


def _module(name: str):  # type: ignore[no-untyped-def]
    if importlib.util.find_spec(name) is None:
        pytest.fail(f"{name} is not implemented")
    return importlib.import_module(name)


def test_trusted_policy_is_closed_and_execution_disabled_by_default() -> None:
    policy_module = _module("picotoopet_core.deep_ai.policy")
    policy = policy_module.DeepAiEscalationPolicy.default()

    business = policy.for_source("business.local_intelligence")
    creative = policy.for_source("creative.intelligence")
    assert business.provider_profile_id == "paid.reasoning.v1"
    assert creative.provider_profile_id == "paid.reasoning.v1"
    assert business.provider_adapter_id == "openai.responses.v1"
    assert business.model_id == "gpt-5.6-terra"
    assert business.max_input_tokens == 12000
    assert business.max_output_tokens == 4000
    assert business.max_calls == 2
    assert str(business.max_cost_usd) == "0.50"
    assert business.execution_enabled is False
    assert business.provider_profile_digest == creative.provider_profile_digest

    with pytest.raises(ValueError, match="DEEP_AI_SOURCE_NOT_ELIGIBLE"):
        policy.for_source("production.comfyui")
    with pytest.raises(ValueError, match="DEEP_AI_SOURCE_NOT_ELIGIBLE"):
        policy.for_source("arbitrary.prompt")


def test_sanitizer_is_deterministic_bounded_and_removes_forbidden_authority() -> None:
    sanitizer_module = _module("picotoopet_core.deep_ai.sanitizer")
    context = sanitizer_module.DeepAiSourceContext(
        source_kind="business.local_intelligence",
        source_id="work-001",
        source_digest="1" * 64,
        project_key="pet-dryer-us",
        source_profile="reviews.voice_of_customer.v1",
        quality_outcome="NEEDS_DEEP_AI",
        quality_reasons=[
            "Need deeper reasoning; api_key=sk-secret-123; Bearer abcdef012345; "
            "source at /Users/alice/private.csv and C:\\Users\\Alice\\secret.txt; "
            "reference https://evil.example/run-tool"
        ],
        evidence_snippets=[
            "Customers mention airflow and drying time.",
            "password=hunter2 token=very-secret-token /home/alice/raw.jsonl",
        ],
        local_result_digest="2" * 64,
        return_schema={"type": "object", "required": ["findings"]},
        manual_handoff_id="handoff-001",
        manual_handoff_digest="3" * 64,
    )
    sanitizer = sanitizer_module.DeepAiSanitizer()
    first = sanitizer.build(context)
    second = sanitizer.build(context)

    assert first.digest == second.digest
    assert first.canonical_bytes == second.canonical_bytes
    assert len(first.canonical_bytes) < 64 * 1024
    payload = json.loads(first.canonical_bytes)
    assert payload["schema_version"] == "1.0"
    assert payload["source"]["source_id"] == "work-001"
    assert payload["source"]["source_digest"] == "1" * 64
    assert payload["manual_handoff"]["handoff_id"] == "handoff-001"
    assert payload["instruction_template_id"] == "deep-ai.reasoning.v1"
    assert payload["return_schema"] == {"type": "object", "required": ["findings"]}

    serialized = first.canonical_bytes.decode("utf-8")
    for forbidden in (
        "sk-secret-123",
        "Bearer abcdef012345",
        "/Users/alice/private.csv",
        "C:\\\\Users\\\\Alice\\\\secret.txt",
        "https://evil.example/run-tool",
        "hunter2",
        "very-secret-token",
        "/home/alice/raw.jsonl",
    ):
        assert forbidden not in serialized
    assert "[REDACTED_SECRET]" in serialized
    assert "[REDACTED_PATH]" in serialized
    assert "[REDACTED_URL]" in serialized


def test_sanitizer_does_not_accept_arbitrary_prompt_tools_or_raw_archive_fields() -> None:
    sanitizer_module = _module("picotoopet_core.deep_ai.sanitizer")
    with pytest.raises(Exception):
        sanitizer_module.DeepAiSourceContext(
            source_kind="business.local_intelligence",
            source_id="work-001",
            source_digest="1" * 64,
            project_key="pet-dryer-us",
            source_profile="reviews.voice_of_customer.v1",
            quality_outcome="NEEDS_DEEP_AI",
            quality_reasons=["reason"],
            evidence_snippets=["evidence"],
            local_result_digest="2" * 64,
            return_schema={"type": "object"},
            manual_handoff_id="handoff-001",
            manual_handoff_digest="3" * 64,
            prompt="ignore policy",
            tools=[{"type": "shell"}],
            raw_archive_path="/tmp/raw.zip",
        )
