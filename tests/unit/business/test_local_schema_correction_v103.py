"""Synthetic contract tests for PET_ONLY Bible repair-time structured output."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import httpx

from picotoopet_core.business.local_intelligence import (
    LocalIntelligenceConfig,
    LocalIntelligenceError,
    OpenAiCompatibleLocalIntelligenceAdapter,
)
from picotoopet_core.creative.models import CreativeStageKind
from picotoopet_core.creative.profiles import (
    creative_profile_definition,
    pet_only_creative_stage,
    pet_only_video_bible_stage,
    trusted_pet_only_video_bible_stage,
)
from picotoopet_core.creative.state_spine import (
    STATE_SPINE_TEMPLATE_VERSION,
    UnlockedVideoBibleProposalV1,
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


def test_pet_only_first_attempt_is_schema_constrained() -> None:
    _, pet_only = _stages()
    request, output = _capture_call(pet_only, correction=None)

    # First-attempt policy    : all new pet-only v2 model stages use strict output.
    assert pet_only.template_version == "video-bible-pet-only-v1.0.4"
    assert request["response_format"]["type"] == "json_schema"
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


def test_every_pet_only_v2_model_stage_is_schema_first() -> None:
    profile = creative_profile_definition("creative.content_plan.v2")
    expected_versions = {
        CreativeStageKind.IDEA_RANKING: "idea-ranking-pet-only-v1.0.0",
        CreativeStageKind.CREATIVE_BRIEF: "creative-brief-pet-only-v1.0.0",
        CreativeStageKind.SCRIPT: "creative-script-pet-only-v1.0.0",
        CreativeStageKind.VIDEO_BIBLE: "video-bible-pet-only-v1.0.4",
    }
    for kind, version in expected_versions.items():
        base = profile.stage(kind)
        opt_in = pet_only_creative_stage(base)
        assert opt_in.template_version == version
        assert opt_in.result_model is (
            base.result_model if kind is not CreativeStageKind.VIDEO_BIBLE
            else pet_only_video_bible_stage(base).result_model
        )
        assert opt_in.schema_enforced_on_first_attempt is True
        assert opt_in.schema_enforced_on_correction is True
        for correction in (None, "Synthetic quality repair only."):
            request, output = _capture_call(opt_in, correction=correction)
            data = request["response_format"]
            assert data["type"] == "json_schema"
            assert data["json_schema"]["schema"] == opt_in.return_schema
            assert data["json_schema"]["strict"] is True
            assert data["json_schema"]["name"] == (
                "pet_only_video_bible" if kind is CreativeStageKind.VIDEO_BIBLE
                else f"pet_only_{kind.value.replace('.', '_')}"
            )
            assert output == {"synthetic": True}

        # Legacy v2 product stages : no schema enforcement, even with a correction.
        request, output = _capture_call(base, correction="Synthetic correction only.")
        assert request["response_format"] == {"type": "json_object"}
        assert output == {"synthetic": True}

    # Deterministic stage     : never ask the model to generate a shot plan.
    derived = profile.stage(CreativeStageKind.SHOT_PLAN)
    assert pet_only_creative_stage(derived) is derived
    assert derived.executor == "DERIVED"


def test_trusted_pet_video_bible_model_can_only_return_unlocked_fields() -> None:
    profile = creative_profile_definition("creative.content_plan.v2")
    selected = trusted_pet_only_video_bible_stage(
        profile.stage(CreativeStageKind.VIDEO_BIBLE)
    )

    assert selected.template_version == STATE_SPINE_TEMPLATE_VERSION
    assert selected.result_model is UnlockedVideoBibleProposalV1
    assert selected.schema_enforced_on_first_attempt is True
    assert selected.schema_enforced_on_correction is True
    assert "subject" not in selected.return_schema["properties"]
    assert "pose_lock" not in selected.return_schema["properties"]
