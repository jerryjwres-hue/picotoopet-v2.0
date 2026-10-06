from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from uuid import uuid4

import pytest

from picotoopet_core.production.compiler import compile_production_plan


def _creative_manifest(
    render_intent: str = "GENERATIVE_VIDEO",
    *,
    duration_seconds: float = 3.0,
    output_profile_id: str | None = "video.landscape.v1",
    script_duration_seconds: float | None = None,
) -> dict[str, object]:
    brief: dict[str, object] = {
        "schema_version": "1.0",
        "creative_profile": "creative.content_plan.v1",
        "selected_idea_id": "idea-001",
        "target_audience": "pet owners",
        "customer_problem": "slow drying",
        "value_proposition": "save time",
        "primary_hook": "Dry faster",
        "emotional_tone": "practical",
        "content_format": "short video",
        "duration_min_seconds": 3,
        "duration_max_seconds": 20,
        "message_hierarchy": ["problem", "solution"],
        "required_source_finding_refs": ["result:finding:1"],
        "required_source_evidence_ids": ["reviews:key:r1"],
        "prohibited_claims": [],
        "cta_intent": "learn more",
        "continuity_notes": [],
        "needs_deep_ai": False,
        "needs_human": False,
    }
    if output_profile_id is not None:
        brief["output_profile_id"] = output_profile_id
    target = duration_seconds if script_duration_seconds is None else script_duration_seconds
    return {
        "schema_version": "1.0",
        "creative_package_id": str(uuid4()),
        "creative_job_id": str(uuid4()),
        "project_key": "pet-dryer-us",
        "creative_profile": "creative.content_plan.v1",
        "source_set_digest": "a" * 64,
        "quality_outcome": "PASS",
        "stage_results": {
            "creative_brief.v1": brief,
            "script.v1": {
                "schema_version": "1.0",
                "creative_profile": "creative.content_plan.v1",
                "script_id": "script-001",
                "title": "Dry faster",
                "target_duration_seconds": target,
                "beats": [
                    {
                        "beat_id": "beat-001",
                        "order": 1,
                        "duration_seconds": target,
                        "voiceover": "Drying time matters.",
                        "on_screen_text": None,
                        "visual_intent": "A compact dryer in use",
                        "claim_source_evidence_ids": ["reviews:key:r1"],
                        "unsupported_claim": False,
                    }
                ],
                "cta_beat_id": "beat-001",
                "warnings": [],
                "needs_deep_ai": False,
                "needs_human": False,
            },
            "shot_plan.v1": {
                "schema_version": "1.0",
                "creative_profile": "creative.content_plan.v1",
                "shots": [
                    {
                        "shot_id": "shot-001",
                        "beat_id": "beat-001",
                        "order": 1,
                        "duration_seconds": duration_seconds,
                        "subject": "compact pet dryer",
                        "environment": "clean home grooming area",
                        "action": "dryer turns while airflow is demonstrated",
                        "framing": "medium product shot",
                        "lighting_style": "soft daylight",
                        "continuity_keys": ["blue body", "same table"],
                        "required_facts": ["portable size"],
                        "source_evidence_ids": ["reviews:key:r1"],
                        "text_reference": None,
                        "production_notes": "renderer-neutral",
                        "render_intent": render_intent,
                    }
                ],
                "warnings": [],
                "needs_deep_ai": False,
                "needs_human": False,
            },
        },
    }


def test_three_second_shot_compiles_to_nearest_compatible_frame_count() -> None:
    plan = compile_production_plan(str(uuid4()), _creative_manifest(), "b" * 64)
    task = plan.tasks[0]

    assert plan.output_profile_id == "video.landscape.v1"
    assert plan.target_runtime_ms == 3000
    assert task.target_duration_ms == 3000
    assert task.execution_disposition == "Executable"
    assert task.workflow_id == "comfy.wan22.ti2v5b.t2v.v1"
    assert task.width == 832
    assert task.height == 480
    assert task.fps == 24
    assert task.frame_count == 73
    assert task.frame_count % 4 == 1
    assert abs(task.frame_count / task.fps - 3.0) <= 2 / task.fps


@pytest.mark.parametrize(("duration_seconds", "frame_count"), [(0.5, 13), (5.0, 121)])
def test_short_and_normal_supported_durations_remain_executable(
    duration_seconds: float,
    frame_count: int,
) -> None:
    plan = compile_production_plan(
        str(uuid4()),
        _creative_manifest(duration_seconds=duration_seconds),
        "b" * 64,
    )

    assert plan.tasks[0].execution_disposition == "Executable"
    assert plan.tasks[0].frame_count == frame_count


@pytest.mark.parametrize(
    ("profile_id", "width", "height"),
    [
        ("video.landscape.v1", 832, 480),
        ("video.vertical.v1", 480, 832),
        ("video.square.v1", 640, 640),
    ],
)
def test_closed_output_profiles_freeze_every_task(
    profile_id: str,
    width: int,
    height: int,
) -> None:
    manifest = _creative_manifest(output_profile_id=profile_id)
    shot_plan = manifest["stage_results"]["shot_plan.v1"]  # type: ignore[index]
    second = deepcopy(shot_plan["shots"][0])  # type: ignore[index]
    second["shot_id"] = "shot-002"
    second["beat_id"] = "beat-002"
    second["order"] = 2
    shot_plan["shots"].append(second)  # type: ignore[index]
    script = manifest["stage_results"]["script.v1"]  # type: ignore[index]
    script["beats"].append(  # type: ignore[index]
        {
            "beat_id": "beat-002",
            "order": 2,
            "duration_seconds": 3,
            "voiceover": None,
            "on_screen_text": None,
            "visual_intent": "Second shot",
            "claim_source_evidence_ids": [],
            "unsupported_claim": False,
        }
    )
    script["target_duration_seconds"] = 6  # type: ignore[index]

    plan = compile_production_plan(str(uuid4()), manifest, "b" * 64)

    assert plan.output_profile_id == profile_id
    assert plan.target_runtime_ms == 6000
    assert {(task.width, task.height, task.fps) for task in plan.tasks} == {
        (width, height, 24)
    }


def test_legacy_brief_without_profile_defaults_to_landscape() -> None:
    plan = compile_production_plan(
        str(uuid4()),
        _creative_manifest(output_profile_id=None),
        "b" * 64,
    )

    assert plan.output_profile_id == "video.landscape.v1"
    assert (plan.tasks[0].width, plan.tasks[0].height, plan.tasks[0].fps) == (832, 480, 24)


def test_unknown_profile_and_raw_renderer_authority_are_rejected() -> None:
    unknown = _creative_manifest(output_profile_id="video.custom.v1")
    with pytest.raises(ValueError, match="PRODUCTION_CREATIVE_BRIEF_INVALID"):
        compile_production_plan(str(uuid4()), unknown, "b" * 64)

    injected = _creative_manifest()
    injected["stage_results"]["creative_brief.v1"]["width"] = 1920  # type: ignore[index]
    injected["stage_results"]["creative_brief.v1"]["fps"] = 60  # type: ignore[index]
    with pytest.raises(ValueError, match="PRODUCTION_CREATIVE_BRIEF_INVALID"):
        compile_production_plan(str(uuid4()), injected, "b" * 64)


def test_over_limit_duration_fails_closed_without_executable_truncation() -> None:
    plan = compile_production_plan(
        str(uuid4()),
        _creative_manifest(duration_seconds=6.0),
        "b" * 64,
    )
    task = plan.tasks[0]

    assert task.target_duration_ms == 6000
    assert task.execution_disposition == "NeedsHuman"
    assert task.workflow_id is None


def test_script_and_shot_timeline_mismatch_beyond_existing_tolerance_is_rejected() -> None:
    with pytest.raises(ValueError, match="PRODUCTION_TIMELINE_MISMATCH"):
        compile_production_plan(
            str(uuid4()),
            _creative_manifest(duration_seconds=3.0, script_duration_seconds=9.0),
            "b" * 64,
        )


def test_identical_inputs_produce_identical_complete_plan() -> None:
    job_id = str(uuid4())
    manifest = _creative_manifest(output_profile_id="video.vertical.v1")

    first = compile_production_plan(job_id, manifest, "b" * 64)
    second = compile_production_plan(job_id, manifest, "b" * 64)

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.tasks[0].seed == second.tasks[0].seed
    first_digest = hashlib.sha256(
        json.dumps(
            first.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    second_digest = hashlib.sha256(
        json.dumps(
            second.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    assert first_digest == second_digest


def test_unsupported_render_intent_fails_closed_to_needs_human() -> None:
    plan = compile_production_plan(str(uuid4()), _creative_manifest("TEXT_CARD"), "b" * 64)
    task = plan.tasks[0]

    assert task.execution_disposition == "NeedsHuman"
    assert task.workflow_id is None
