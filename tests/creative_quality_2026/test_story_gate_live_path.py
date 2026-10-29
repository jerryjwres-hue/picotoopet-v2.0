"""The story gate and keyframe kit on the real Creative v2 path.

Real Coordinator, real SQLite, real Ollama adapter over a recording transport; only the model's
JSON is scripted. Nothing here looks at a picture or measures visual quality.
"""

from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

import pytest
import story_fixture_2026 as fx
from director_fixtures import V1, V2, OllamaDouble, Runtime, open_runtime, stage_outputs

from picotoopet_core.creative.director import (
    STORY_GATE_RULES,
    director_constraints,
    parse_goal_directives,
)
from picotoopet_core.creative.models import (
    CreativeBriefResult,
    CreativeJobStatus,
    CreativeScriptResult,
)
from picotoopet_core.creative.video_bible import KeyframeKit
from picotoopet_core.production.compiler import compile_production_plan

BASE_GOAL = (
    "Exactly 3 shots, text-to-video only: no reference image. Each shot 4.0 seconds, total "
    "12 seconds, landscape. A white cat gets a clip-on tag: hook, demo, payoff."
)
GATED_GOAL = BASE_GOAL + " Use the quality-first story gate."


@pytest.fixture
def runtime(tmp_path):  # type: ignore[no-untyped-def]
    rt = open_runtime(tmp_path)
    yield rt
    rt.database.close()


def _job(rt: Runtime, goal: str, profile: str = V2, key: str = "k"):  # type: ignore[no-untyped-def]
    job = rt.service.create_job(
        source_result_package_ids=[rt.result_id], creative_profile=profile,
        creative_objective=goal, idempotency_key=key,
    )
    task = next(
        item for item in rt.queue.list(limit=50)
        if item.resource_tag == f"creative:{job.creative_job_id}"
    )
    return job, task


def _outputs(rt: Runtime, job_id: str) -> list[dict]:
    ref = rt.source_ref_for(job_id)
    brief = {**fx.brief(), "required_source_finding_refs": [ref]}
    return [stage_outputs(ref)["idea"], brief, fx.script()]


def _bad_story() -> dict:
    bad = fx.bible()
    bad["shots"][1]["visible_action"] = (
        "a hand clips the tag onto the green scarf under Mochi's chin"
    )
    bad["scenes"].append({**bad["scenes"][0], "scene_id": "kitchen"})
    bad["shots"][2]["scene_id"] = "kitchen"
    return bad


# ── Directive selection ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (GATED_GOAL, True), ("quality-first story please", True), ("请启用故事门禁", True),
        ("Exactly 3 shots, quality first", False), (BASE_GOAL, False), ("", False), (None, False),
        ("no story gate", False), ("without story gate", False), ("不要故事门禁", False),
    ],
)
def test_story_gate_is_selected_only_by_an_explicit_positive_phrase(text, expected) -> None:
    assert parse_goal_directives(text).story_gate is expected


def test_gate_rules_reach_the_model_only_for_a_gated_goal() -> None:
    brief = CreativeBriefResult.model_validate(fx.brief())
    script = CreativeScriptResult.model_validate(fx.script())
    plain = director_constraints(brief, script, parse_goal_directives(BASE_GOAL))
    gated = director_constraints(brief, script, parse_goal_directives(GATED_GOAL))
    assert "story_gate" not in plain
    assert gated["story_gate"] == STORY_GATE_RULES
    assert {k: v for k, v in gated.items() if k != "story_gate"} == plain


# ── Real coordinator path ──────────────────────────────────────────────────────────────


def test_valid_story_reaches_creative_ready_with_three_untrusted_review_entries(
    runtime: Runtime,
) -> None:
    job, task = _job(runtime, GATED_GOAL)
    double = OllamaDouble([*_outputs(runtime, job.creative_job_id), fx.bible()])
    summary = runtime.coordinator(double.adapter).handler(task)
    assert summary.summary["status"] == "creative_ready" and len(double.requests) == 4
    assert double.data(3)["director_constraints"]["story_gate"] == STORY_GATE_RULES

    package = runtime.service.get_package(job.creative_job_id)
    assert package is not None
    stages = package.manifest["stage_results"]
    kit = KeyframeKit.model_validate(stages["keyframe_kit.v1"])
    assert kit.bible_digest == stages["video_bible.v1"]["bible_digest"]
    planned = [s["shot_id"] for s in stages["shot_plan.v1"]["shots"]]
    assert [k.shot_id for k in kit.keyframes] == planned
    assert {k.approval_status.value for k in kit.keyframes} == {"PENDING_HUMAN_REVIEW"}
    assert {p.trust_state for p in kit.reference_manifest_proposal} == {"UNTRUSTED_PROPOSAL"}
    assert "image_sha256" not in str(stages["keyframe_kit.v1"])

    # The unchanged compiler still reads the same package; nothing becomes I2V.
    plan = compile_production_plan(str(uuid4()), package.manifest, package.package_digest)
    assert {t.trusted_input_asset_ref for t in plan.tasks} == {None}
    assert len(plan.tasks) == 3


def test_malformed_story_is_corrected_deterministically_through_the_quality_gate(
    runtime: Runtime,
) -> None:
    job, task = _job(runtime, GATED_GOAL)
    double = OllamaDouble([*_outputs(runtime, job.creative_job_id), _bad_story(), fx.bible()])
    summary = runtime.coordinator(double.adapter).handler(task)
    assert summary.summary["status"] == "creative_ready" and len(double.requests) == 5
    retry = double.requests[4]["user"]
    for code in ("IDENTITY_COLOUR_DRIFT", "STORY_SCENE_SPLIT"):
        assert code in retry
    package = runtime.service.get_package(job.creative_job_id)
    assert package is not None and "keyframe_kit.v1" in package.manifest["stage_results"]


def test_story_that_stays_malformed_is_rejected_with_no_package_and_no_kit(
    runtime: Runtime,
) -> None:
    job, task = _job(runtime, GATED_GOAL)
    double = OllamaDouble([*_outputs(runtime, job.creative_job_id), _bad_story(), _bad_story()])
    summary = runtime.coordinator(double.adapter).handler(task)
    assert summary.summary["status"] == "NeedsHuman"
    record = runtime.repository.get_job(job.creative_job_id)
    assert record.status is CreativeJobStatus.NEEDS_HUMAN
    assert record.failure_code == "CREATIVE_VIDEO_BIBLE_UNRESOLVED"
    assert runtime.service.get_package(job.creative_job_id) is None


def test_the_same_story_without_the_phrase_keeps_the_legacy_gate_and_gets_no_kit(
    runtime: Runtime,
) -> None:
    job, task = _job(runtime, BASE_GOAL, key="legacy")
    legacy_ok = deepcopy(fx.bible())
    legacy_ok["scenes"].append({**legacy_ok["scenes"][0], "scene_id": "kitchen"})
    legacy_ok["shots"][2]["scene_id"] = "kitchen"  # fails the story gate, passes the old gate
    double = OllamaDouble([*_outputs(runtime, job.creative_job_id), legacy_ok])
    summary = runtime.coordinator(double.adapter).handler(task)
    assert summary.summary["status"] == "creative_ready" and len(double.requests) == 4
    assert "story_gate" not in double.data(3)["director_constraints"]
    package = runtime.service.get_package(job.creative_job_id)
    assert package is not None and "keyframe_kit.v1" not in package.manifest["stage_results"]


def test_v1_profile_is_untouched_by_the_phrase(runtime: Runtime) -> None:
    job, task = _job(runtime, GATED_GOAL, profile=V1, key="v1")
    ref = runtime.source_ref_for(job.creative_job_id)
    parts = stage_outputs(ref)
    shots = {
        "schema_version": "1.0", "creative_profile": V1, "warnings": [],
        "needs_deep_ai": False, "needs_human": False,
        "shots": [
            {"shot_id": f"shot-{i:03d}", "beat_id": f"beat-{i:03d}", "order": i,
             "duration_seconds": 4.0, "subject": "Mochi the white cat", "environment": "room",
             "action": action, "framing": "medium shot",
             "lighting_style": "warm light",
             "continuity_keys": ["white cat Mochi", "teal scarf"], "required_facts": [],
             "source_evidence_ids": [], "text_reference": None,
             "production_notes": "renderer-neutral", "render_intent": "GENERATIVE_VIDEO"}
            for i, action in (
                (1, "Mochi taps the tag with her paw"),
                (2, "a hand clips the tag onto the scarf"),
                (3, "Mochi trots past the lamp"),
            )
        ],
    }
    brief = {**fx.brief(), "required_source_finding_refs": [ref]}
    double = OllamaDouble([parts["idea"], brief, fx.script(), shots])
    summary = runtime.coordinator(double.adapter).handler(task)
    assert summary.summary["status"] == "creative_ready"
    package = runtime.service.get_package(job.creative_job_id)
    assert package is not None
    assert set(package.manifest["stage_results"]) == {
        "idea_ranking.v1", "creative_brief.v1", "script.v1", "shot_plan.v1"
    }
