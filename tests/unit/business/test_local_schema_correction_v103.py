"""Synthetic contract tests for PET_ONLY Bible repair-time structured output."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from picotoopet_core.business.local_intelligence import (
    LocalIntelligenceConfig,
    LocalIntelligenceError,
    OpenAiCompatibleLocalIntelligenceAdapter,
)
from picotoopet_core.creative.models import CreativeStageKind
from picotoopet_core.creative.profiles import (
    creative_profile_definition,
    pet_only_video_bible_stage,
)


def _capture_call(
    profile: Any,
    *,
    correction: str | None,
    content: str = '{"synthetic": true}',
) -> tuple[dict[str, Any], dict[str, Any] | LocalIntelligenceError]:
    requests: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        # Loopback-only mock    : capture request structure without model inference.
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"content": content},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 8345,
                    "completion_tokens": 1934,
                    "total_tokens": 10279,
                },
            },
        )

    client = httpx.Client(
        base_url="http://127.0.0.1:11434/v1/",
        transport=httpx.MockTransport(respond),
    )
    try:
        adapter = OpenAiCompatibleLocalIntelligenceAdapter(
            LocalIntelligenceConfig(), client=client
        )
        try:
            output: dict[str, Any] | LocalIntelligenceError = adapter.run(
                profile, {"fixture": "synthetic"}, correction=correction
            )
        except LocalIntelligenceError as error:
            output = error
        assert len(requests) == 1
        return requests[0], output
    finally:
        client.close()


def _stages() -> tuple[Any, Any]:
    base = creative_profile_definition("creative.content_plan.v2").stage(
        CreativeStageKind.VIDEO_BIBLE
    )
    return base, pet_only_video_bible_stage(base)


def test_pet_only_first_attempt_keeps_original_json_object() -> None:
    _, pet_only = _stages()
    request, output = _capture_call(pet_only, correction=None)

    # First attempt stays fixed : only the second quality-repair call gets schema mode.
    assert pet_only.template_version == "video-bible-pet-only-v1.0.3"
    assert request["response_format"] == {"type": "json_object"}
    assert output == {"synthetic": True}


def test_pet_only_correction_passes_strict_schema_to_local_ollama() -> None:
    _, pet_only = _stages()
    request, output = _capture_call(
        pet_only, correction="Repair synthetic schema defects only."
    )
    requested = request["response_format"]

    # Trusted profile schema   : do not build schema from untrusted source text.
    assert requested["type"] == "json_schema"
    assert requested["json_schema"]["name"] == "pet_only_video_bible"
    assert requested["json_schema"]["strict"] is True
    assert requested["json_schema"]["schema"] == pet_only.return_schema
    assert "PetOnlyVideoBibleDraft" in str(requested["json_schema"]["schema"])
    assert output == {"synthetic": True}


def test_other_stages_preserve_json_object_even_on_correction() -> None:
    base, _ = _stages()
    for profile in (
        base,
        SimpleNamespace(
            system_prompt="synthetic",
            return_schema={"type": "object"},
            temperature=0.0,
            max_output_tokens=500,
        ),
    ):
        request, output = _capture_call(profile, correction="repair")
        assert request["response_format"] == {"type": "json_object"}
        assert output == {"synthetic": True}


def test_malformed_stop_response_remains_fail_closed_even_with_schema() -> None:
    _, pet_only = _stages()
    invalid = '{"synthetic": true'
    request, output = _capture_call(
        pet_only, correction="Repair synthetic schema defects only.", content=invalid
    )

    # No silent JSON repair    : malformed model text cannot be accepted or reserialized.
    assert request["response_format"]["type"] == "json_schema"
    assert isinstance(output, LocalIntelligenceError)
    assert output.code == "LOCAL_MODEL_JSON_INVALID"
    assert output.diagnostics["finish_reason"] == "stop"
    assert output.diagnostics["json_error_kind"] == "syntax"
    assert output.diagnostics["json_error_position"] == len(invalid)
    assert "synthetic" not in str(output)
