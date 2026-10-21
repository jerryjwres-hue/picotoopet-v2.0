"""Multi-shot plan invariants that quality, yield and regeneration all depend on.

Synthetic Creative manifests only: nothing here renders, scores or looks at a picture, so none
of these tests can (or does) claim visual quality. They pin the plan-level contract that a
later human-review / regeneration workflow must be able to rely on.
"""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from uuid import uuid4

import pytest

from picotoopet_core.creative.models import CreativeStageKind
from picotoopet_core.creative.profiles import creative_profile_definition
from picotoopet_core.creative.quality import CreativeQualityGate
from picotoopet_core.creative.source import NormalizedCreativeSourceSet
from picotoopet_core.production.compiler import compile_production_plan
from picotoopet_core.production.profile import (
    VIDEO_OUTPUT_PROFILES,
    frame_count_for_duration,
)

_EVIDENCE = "reviews:key:r1"
_ANCHOR = ["golden retriever named Milo", "red collar"]


def _shot(index: int, duration: float, intent: str = "GENERATIVE_VIDEO", keys=None) -> dict:
    return {
        "shot_id": f"shot-{index:03d}",
        "beat_id": f"beat-{index:03d}",
        "order": index,
        "duration_seconds": duration,
        "subject": "golden retriever named Milo" if index != 2 else "Milo on a sofa",
        "environment": "bright living room",
        "action": f"Milo does action {index}",
        "framing": "medium shot",
        "lighting_style": "soft daylight",
        "continuity_keys": list(_ANCHOR) if keys is None else keys,
        "required_facts": [],
        "source_evidence_ids": [_EVIDENCE],
        "text_reference": None,
        "production_notes": "renderer-neutral",
        "render_intent": intent,
    }


def _manifest(shots: list[dict], *, continuity_notes=None, assets=None) -> dict:
    total = sum(shot["duration_seconds"] for shot in shots)
    brief = {
        "schema_version": "1.0",
        "creative_profile": "creative.content_plan.v1",
        "selected_idea_id": "idea-001",
        "target_audience": "dog owners",
        "customer_problem": "dull walks",
        "value_proposition": "fun",
        "primary_hook": "Meet Milo",
        "emotional_tone": "warm",
        "content_format": "short video",
        "output_profile_id": "video.landscape.v1",
        "duration_min_seconds": 3,
        "duration_max_seconds": 60,
        "message_hierarchy": ["hook", "benefit"],
        "required_source_finding_refs": ["result:finding:1"],
        "required_source_evidence_ids": [_EVIDENCE],
        "prohibited_claims": [],
        "cta_intent": "learn more",
        "continuity_notes": list(continuity_notes or []),
        "needs_deep_ai": False,
        "needs_human": False,
    }
    beats = [
        {
            "beat_id": shot["beat_id"], "order": shot["order"],
            "duration_seconds": shot["duration_seconds"], "voiceover": None,
            "on_screen_text": None, "visual_intent": f"beat {shot['order']}",
            "claim_source_evidence_ids": [_EVIDENCE], "unsupported_claim": False,
        }
        for shot in shots
    ]
    manifest = {
        "schema_version": "1.0",
        "creative_package_id": str(uuid4()),
        "creative_job_id": str(uuid4()),
        "project_key": "goal-multishot",
        "creative_profile": "creative.content_plan.v1",
        "source_set_digest": "a" * 64,
        "quality_outcome": "PASS",
        "stage_results": {
            "creative_brief.v1": brief,
            "script.v1": {
                "schema_version": "1.0", "creative_profile": "creative.content_plan.v1",
                "script_id": "script-001", "title": "Milo", "target_duration_seconds": total,
                "beats": beats, "cta_beat_id": beats[-1]["beat_id"], "warnings": [],
                "needs_deep_ai": False, "needs_human": False,
            },
            "shot_plan.v1": {
                "schema_version": "1.0", "creative_profile": "creative.content_plan.v1",
                "shots": shots, "warnings": [], "needs_deep_ai": False, "needs_human": False,
            },
        },
    }
    if assets:
        manifest["trusted_local_assets"] = assets
    return manifest


def _three_shot_manifest(**kwargs) -> dict:
    return _manifest([_shot(1, 3.0), _shot(2, 3.0), _shot(3, 2.0)], **kwargs)


def test_plan_is_deterministic_and_identity_stable_per_shot() -> None:
    job = str(uuid4())
    manifest = _three_shot_manifest()
    first = compile_production_plan(job, manifest, "b" * 64)
    second = compile_production_plan(job, deepcopy(manifest), "b" * 64)
    assert first.model_dump(mode="json") == second.model_dump(mode="json")

    # Every verdict/metric is keyed by (production_job_id, shot_id): both must be stable & unique.
    assert [t.shot_id for t in first.tasks] == ["shot-001", "shot-002", "shot-003"]
    assert [t.order for t in first.tasks] == [1, 2, 3]
    assert len({t.production_task_id for t in first.tasks}) == 3
    assert len({t.seed for t in first.tasks}) == 3

    other_job = compile_production_plan(str(uuid4()), deepcopy(manifest), "b" * 64)
    first_ids = {t.production_task_id for t in first.tasks}
    assert not first_ids & {t.production_task_id for t in other_job.tasks}
    assert not {t.seed for t in first.tasks} & {t.seed for t in other_job.tasks}


def test_timeline_adds_up_and_frames_stay_wan_compatible() -> None:
    plan = compile_production_plan(str(uuid4()), _three_shot_manifest(), "b" * 64)
    fps = VIDEO_OUTPUT_PROFILES[plan.output_profile_id].fps
    assert plan.target_runtime_ms == sum(t.target_duration_ms for t in plan.tasks) == 8000
    for task in plan.tasks:
        assert task.frame_count % 4 == 1
        rendered = Decimal(task.frame_count) / fps
        assert abs(rendered - Decimal(task.target_duration_ms) / 1000) <= Decimal(2) / fps


def test_each_shots_continuity_keys_reach_its_own_prompt() -> None:
    plan = compile_production_plan(str(uuid4()), _three_shot_manifest(), "b" * 64)
    for task in plan.tasks:
        for key in _ANCHOR:
            assert key in task.positive_prompt, f"{task.shot_id} lost continuity key {key!r}"


def test_unrenderable_shot_is_flagged_for_a_human_never_truncated() -> None:
    long_seconds = 8.0
    with pytest.raises(ValueError, match="PRODUCTION_SHOT_DURATION_UNSUPPORTED"):
        frame_count_for_duration(long_seconds, 24)
    manifest = _manifest([_shot(1, 3.0), _shot(2, long_seconds)])
    plan = compile_production_plan(str(uuid4()), manifest, "b" * 64)
    ok, too_long = plan.tasks
    assert ok.execution_disposition == "Executable"
    assert too_long.execution_disposition == "NeedsHuman"
    assert too_long.workflow_id is None
    # The planned duration is preserved; the shot is not silently shortened to fit.
    assert too_long.target_duration_ms == 8000


def test_image_to_video_without_trusted_asset_never_downgrades_to_text_to_video() -> None:
    shots = [_shot(1, 3.0, "IMAGE_TO_VIDEO"), _shot(2, 3.0, "IMAGE_TO_VIDEO")]
    without = compile_production_plan(str(uuid4()), _manifest(shots), "b" * 64)
    assert [t.execution_disposition for t in without.tasks] == ["NeedsHuman", "NeedsHuman"]
    assert all(t.workflow_id is None for t in without.tasks)

    with_asset = compile_production_plan(
        str(uuid4()), _manifest(deepcopy(shots), assets={"shot-001": "assets/milo.png"}), "b" * 64
    )
    first, second = with_asset.tasks
    assert first.execution_disposition == "Executable"
    assert first.workflow_id == "comfy.wan22.ti2v5b.i2v.v1"
    assert second.execution_disposition == "NeedsHuman"


@pytest.mark.parametrize(
    "intent", ["GENERATIVE_IMAGE", "PRODUCT_ASSET_COMPOSITE", "TEXT_CARD", "EXISTING_ASSET"]
)
def test_non_video_render_intents_are_not_silently_rendered(intent: str) -> None:
    plan = compile_production_plan(str(uuid4()), _manifest([_shot(1, 3.0, intent)]), "b" * 64)
    assert plan.tasks[0].execution_disposition == "NeedsHuman"


# ── Executable acceptance specs for the G006 quality-yield handoff ───────────────────────
# Strict xfail: they describe wanted behaviour that is NOT implemented today. When G006 ships
# the improvement the test flips to XPASS and strict mode forces removal of the marker.


def test_brief_continuity_notes_reach_every_shot_prompt() -> None:
    notes = ["Milo is a golden retriever with a red collar", "Always the same living room"]
    plan = compile_production_plan(
        str(uuid4()), _three_shot_manifest(continuity_notes=notes), "b" * 64
    )
    for task in plan.tasks:
        for note in notes:
            assert note in task.positive_prompt, f"{task.shot_id} misses brief note {note!r}"


def _gate_inputs(shots: list[dict]):
    script_beats = [{"beat_id": shot["beat_id"]} for shot in shots]
    source = NormalizedCreativeSourceSet(
        project_key="goal-multishot", result_package_ids=["r1"], result_digests=["c" * 64],
        findings=[], evidence_ids=[_EVIDENCE], source_set_digest="d" * 64,
    )
    raw = {
        "schema_version": "1.0", "creative_profile": "creative.content_plan.v1",
        "shots": shots, "warnings": [], "needs_deep_ai": False, "needs_human": False,
    }
    return source, {"script.v1": {"beats": script_beats}}, raw


def test_creative_gate_accepts_a_structurally_valid_shot_plan() -> None:
    source, previous, raw = _gate_inputs([_shot(1, 3.0), _shot(2, 3.0)])
    decision, parsed = CreativeQualityGate().evaluate(
        stage_kind=CreativeStageKind.SHOT_PLAN,
        profile=creative_profile_definition("creative.content_plan.v1"),
        source_set=source, previous_stages=previous, raw_result=raw,
    )
    assert decision.outcome.value == "PASS" and parsed is not None


def test_creative_gate_rejects_a_shot_the_renderer_cannot_produce() -> None:
    source, previous, raw = _gate_inputs([_shot(1, 3.0), _shot(2, 8.0)])
    decision, _ = CreativeQualityGate().evaluate(
        stage_kind=CreativeStageKind.SHOT_PLAN,
        profile=creative_profile_definition("creative.content_plan.v1"),
        source_set=source, previous_stages=previous, raw_result=raw,
    )
    assert decision.outcome.value == "RETRY"

# ── Additional G006 regression: legacy prompt compatibility / no evidence spoofing ─────
def test_empty_brief_continuity_preserves_prior_per_shot_prompt() -> None:
    plan = compile_production_plan(str(uuid4()), _three_shot_manifest(), "b" * 64)
    for task in plan.tasks:
        assert "wan22-shot-prompt-v1.1.0" not in task.positive_prompt
        assert "golden retriever named Milo" in task.positive_prompt


def test_nonvideo_shot_timing_does_not_spoof_video_feasibility() -> None:
    source, previous, raw = _gate_inputs([_shot(1, 8.0, intent="TEXT_CARD")])
    decision, parsed = CreativeQualityGate().evaluate(
        stage_kind=CreativeStageKind.SHOT_PLAN,
        profile=creative_profile_definition("creative.content_plan.v1"),
        source_set=source, previous_stages=previous, raw_result=raw,
    )
    assert decision.outcome.value == "PASS"
    assert parsed is not None
