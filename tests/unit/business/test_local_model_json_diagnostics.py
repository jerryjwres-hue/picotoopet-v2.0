"""Only sanitized Ollama completion diagnostics may survive malformed JSON."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from picotoopet_core.business.local_intelligence import (
    LocalIntelligenceConfig,
    LocalIntelligenceError,
    OpenAiCompatibleLocalIntelligenceAdapter,
)


def _run_completion(content: str, *, finish_reason: object = "length", usage: object = None):
    # Synthetic response only : never use actual pet evidence or prompts in tests.
    payload = {
        "choices": [{"message": {"content": content}, "finish_reason": finish_reason}],
        "usage": usage,
    }
    client = httpx.Client(
        base_url="http://127.0.0.1:11434/v1/",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)),
    )
    profile = SimpleNamespace(
        system_prompt="Synthetic test directive.",
        return_schema={"type": "object"},
        temperature=0.0,
        max_output_tokens=3600,
    )
    try:
        return OpenAiCompatibleLocalIntelligenceAdapter(
            LocalIntelligenceConfig(), client=client,
        ).run(profile, {"fixture": "synthetic"})
    finally:
        client.close()


def test_malformed_json_keeps_only_bounded_completion_metadata() -> None:
    private_marker = "SYNTHETIC_SECRET_SHOULD_NOT_SURVIVE"
    invalid_content = "{\n" + private_marker

    with pytest.raises(LocalIntelligenceError) as error:
        _run_completion(
            invalid_content,
            usage={"prompt_tokens": 120, "completion_tokens": 3600, "total_tokens": 3720},
        )

    assert error.value.code == "LOCAL_MODEL_JSON_INVALID"
    assert str(error.value) == "LOCAL_MODEL_JSON_INVALID"
    assert error.value.diagnostics == {
        "finish_reason": "length",
        "usage": {"prompt_tokens": 120, "completion_tokens": 3600, "total_tokens": 3720},
        "content_bytes": len(invalid_content.encode("utf-8")),
        "json_error_kind": "syntax",
        "json_error_position": 2,
    }
    assert private_marker not in repr(error.value.diagnostics)


def test_non_object_completion_is_classified_without_content() -> None:
    with pytest.raises(LocalIntelligenceError) as error:
        _run_completion("[1, 2]", finish_reason="stop")

    assert error.value.code == "LOCAL_MODEL_JSON_INVALID"
    assert error.value.diagnostics == {
        "finish_reason": "stop",
        "usage": {},
        "content_bytes": len("[1, 2]"),
        "json_error_kind": "top_level_non_object",
        "json_error_position": None,
    }


def test_untrusted_provider_metadata_is_stripped() -> None:
    with pytest.raises(LocalIntelligenceError) as error:
        _run_completion(
            "not json",
            finish_reason=["hidden", "response"],
            usage={"prompt_tokens": "private-token", "total_tokens": -1},
        )

    # Fixed-field allowlist   : malformed metadata cannot enter Stage error_message.
    assert error.value.diagnostics["finish_reason"] == "unknown"
    assert error.value.diagnostics["usage"] == {}
    assert "private-token" not in repr(error.value.diagnostics)


def test_valid_json_contract_is_unchanged() -> None:
    assert _run_completion('{"ok":true}', finish_reason="stop") == {"ok": True}
