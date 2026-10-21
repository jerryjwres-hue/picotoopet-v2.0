"""First-pass reliability of an explicit "exactly N shots, text-to-video only" Goal.

The Goal objective is the only per-run input a user controls. These tests pin how the Creative
gates turn that objective into deterministic pre-GPU checks, using the real gate, the real
Coordinator + SQLite and the real Ollama adapter over a recording transport. Model outputs are
scripted and synthetic; nothing here measures picture quality.
"""

from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

import pytest
from director_fixtures import (
    EVIDENCE,
    V1,
    V2,
    OllamaDouble,
    Runtime,
    good_bible,
    open_runtime,
    stage_outputs,
)

from picotoopet_core.creative.director import GoalDirectives, parse_goal_directives
from picotoopet_core.creative.models import CreativeQualityOutcome, CreativeStageKind
from picotoopet_core.creative.profiles import creative_profile_definition
from picotoopet_core.creative.quality import CreativeQualityGate
from picotoopet_core.creative.source import NormalizedCreativeSourceSet
from picotoopet_core.production.compiler import compile_production_plan

GOAL = (
    "Exactly 3 shots, text-to-video only: no reference image, no image-to-video, no text cards. "
    "Each shot 4.0 seconds, total 12 seconds, landscape. Show a golden retriever wearing a "
    "clip-on tag: hook, demo, payoff."
)


# ── Directive parsing (conservative: it can only tighten the gates) ────────────────────


@pytest.mark.parametrize(
    ("text", "count"),
    [
        ("Exactly 3 shots, text-to-video only", 3),
        ("make a 3-shot video", 3),
        ("three shots please", 3),
        ("请生成正好三个镜头的视频", 3),
        ("共3个镜头，每个镜头4秒", 3),
        ("4 shots of the dog", 4),
        ("at least 3 shots", None),
        ("up to 5 shots", None),
        ("no more than 4 shots", None),
        ("最多3个镜头", None),
        ("不少于三个镜头", None),
        ("3 shots or maybe 4 shots", None),
        ("a 30 second video about dogs", None),
        ("40 shots", None),
        ("", None),
        (None, None),
    ],
)
def test_requested_shot_count_is_parsed_only_when_explicit(text, count) -> None:  # type: ignore[no-untyped-def]
    assert parse_goal_directives(text).shot_count == count


@pytest.mark.parametrize(
    ("text", "t2v_only"),
    [
        ("text-to-video only", True),
        ("T2V only, no reference image", True),
        ("不使用参考图，仅文生视频", True),
        ("no image-to-video", True),
        ("use an image-to-video shot for the product", False),
        ("make a short dog video", False),
        ("T2V plus I2V for the product close-up", False),
    ],
)
def test_text_to_video_only_is_detected_and_never_inferred(text, t2v_only) -> None:  # type: ignore[no-untyped-def]
    assert parse_goal_directives(text).text_to_video_only is t2v_only


def test_the_recommended_goal_text_parses_to_the_intended_directives() -> None:
    assert parse_goal_directives(GOAL) == GoalDirectives(shot_count=3, text_to_video_only=True)
    assert len(GOAL) < 400


# ── Gate behaviour ─────────────────────────────────────────────────────────────────────

SOURCE = NormalizedCreativeSourceSet(
    project_key="goal-x", result_package_ids=[], result_digests=[], findings=[],
    evidence_ids=[EVIDENCE], source_set_digest="d" * 64,
)
PROFILE = creative_profile_definition(V1)


def _script(beats: int = 3, seconds: float = 4.0) -> dict:
    out = stage_outputs("result:finding:1")["script"]
    out["beats"] = [
        {"beat_id": f"beat-{n:03d}", "order": n, "duration_seconds": seconds,
         "voiceover": None, "on_screen_text": None, "visual_intent": f"beat {n}",
         "claim_source_evidence_ids": [], "unsupported_claim": False}
        for n in range(1, beats + 1)
    ]
    out["cta_beat_id"] = f"beat-{beats:03d}"
    out["target_duration_seconds"] = beats * seconds
    return out


_ACTIONS = [
    "the dog sits and tilts its head",
    "a small white tag clicks onto the collar",
    "the dog runs across the grass toward the camera",
    "the dog lies down and rests",
    "the dog shakes its fur",
    "the dog jumps for a ball",
]


def _shots(count: int = 3, seconds: float = 4.0, intent: str = "GENERATIVE_VIDEO") -> dict:
    return {
        "schema_version": "1.0", "creative_profile": V1,
        "shots": [
            {"shot_id": f"shot-{n:03d}", "beat_id": f"beat-{min(n, 3):03d}", "order": n,
             "duration_seconds": seconds, "subject": "a golden retriever", "environment": "park",
             "action": _ACTIONS[(n - 1) % len(_ACTIONS)], "framing": "medium shot",
             "lighting_style": "soft",
             "continuity_keys": ["cream golden retriever", "teal collar"],
             "required_facts": [], "source_evidence_ids": [],
             "text_reference": None, "production_notes": "renderer-neutral",
             "render_intent": intent}
            for n in range(1, count + 1)
        ],
        "warnings": [], "needs_deep_ai": False, "needs_human": False,
    }


def _evaluate(kind, raw, previous, objective=None):  # type: ignore[no-untyped-def]
    brief = stage_outputs("result:finding:1")["brief"]
    full = {"creative_brief.v1": brief, **previous}
    return CreativeQualityGate().evaluate(
        stage_kind=kind, profile=PROFILE, source_set=SOURCE, previous_stages=full,
        raw_result=raw, objective=objective,
    )[0]


def _plan(raw, script=None, objective=GOAL):  # type: ignore[no-untyped-def]
    return _evaluate(
        CreativeStageKind.SHOT_PLAN, raw, {"script.v1": script or _script()}, objective
    )


def test_exactly_n_shots_passes_and_other_counts_are_retried_with_the_number() -> None:
    assert _plan(_shots(3)).outcome is CreativeQualityOutcome.PASS
    for wrong, seconds in ((4, 3.0), (6, 2.0)):  # same 12 s total, so only the count is wrong
        decision = _plan(_shots(wrong, seconds))
        assert decision.outcome is CreativeQualityOutcome.RETRY, wrong
        assert decision.reasons == ["SHOT_COUNT_MISMATCH"]
        assert "exactly 3 shots" in (decision.correction_instruction or "")


def test_without_a_count_directive_any_count_still_passes() -> None:
    assert _plan(_shots(5, 2.4), script=_script(beats=3), objective=None).outcome is (
        CreativeQualityOutcome.PASS
    )


def test_fewer_shots_than_beats_is_still_the_existing_coverage_error() -> None:
    assert _plan(_shots(2)).reasons == ["SCRIPT_BEAT_NOT_COVERED"]


def test_unrenderable_shot_correction_keeps_the_requested_count() -> None:
    decision = _plan(_shots(3, seconds=8.0), script=_script(3, 8.0))
    assert decision.outcome is CreativeQualityOutcome.RETRY
    assert decision.reasons == ["CREATIVE_SHOT_DURATION_UNRENDERABLE"]
    text = decision.correction_instruction or ""
    assert "exactly 3 shots" in text and "Split the beat" not in text


def test_without_a_count_directive_the_split_correction_is_unchanged() -> None:
    decision = _plan(_shots(3, seconds=8.0), script=_script(3, 8.0), objective=None)
    assert "Split the beat into shorter ordered shots" in (decision.correction_instruction or "")


def test_shot_timeline_must_match_the_script_like_the_production_compiler() -> None:
    # Production raises PRODUCTION_TIMELINE_MISMATCH beyond 5.0 s; Creative must say so first.
    decision = _plan(_shots(3, seconds=4.0), script=_script(3, 9.0), objective=None)
    assert decision.outcome is CreativeQualityOutcome.RETRY
    assert decision.reasons == ["SHOT_TIMELINE_MISMATCH"]
    assert _plan(_shots(3, seconds=4.0), script=_script(3, 5.0), objective=None).outcome is (
        CreativeQualityOutcome.PASS
    )


@pytest.mark.parametrize(
    "intent",
    ["TEXT_CARD", "GENERATIVE_IMAGE", "PRODUCT_ASSET_COMPOSITE", "EXISTING_ASSET",
     "IMAGE_TO_VIDEO"],
)
def test_text_to_video_only_goal_retries_every_non_t2v_intent(intent: str) -> None:
    decision = _plan(_shots(3, intent=intent))
    assert decision.outcome is CreativeQualityOutcome.RETRY
    assert decision.reasons == ["RENDER_INTENT_NOT_TEXT_TO_VIDEO"]
    assert "GENERATIVE_VIDEO" in (decision.correction_instruction or "")


@pytest.mark.parametrize("intent", ["TEXT_CARD", "IMAGE_TO_VIDEO", "EXISTING_ASSET"])
def test_other_goals_keep_the_existing_intent_freedom(intent: str) -> None:
    """Reference-image goals and non-video planning stay possible when nobody asked for T2V."""

    for objective in (None, "Exactly 3 shots, use image-to-video for the product"):
        assert _plan(_shots(3, intent=intent), objective=objective).outcome is (
            CreativeQualityOutcome.PASS
        )


def test_script_stage_is_bounded_by_the_requested_shot_count() -> None:
    def script(raw, objective=GOAL):  # type: ignore[no-untyped-def]
        return _evaluate(CreativeStageKind.SCRIPT, raw, {}, objective)

    assert script(_script(3, 4.0)).outcome is CreativeQualityOutcome.PASS
    many = script(_script(4, 3.0))
    assert many.reasons == ["SCRIPT_BEATS_EXCEED_SHOT_COUNT"]
    long = script(_script(3, 9.0))
    assert long.reasons == ["SCRIPT_TOO_LONG_FOR_SHOT_COUNT"]
    assert "at most 15.0 seconds" in (long.correction_instruction or "")
    short = script(_script(3, 0.5))
    assert short.reasons == ["SCRIPT_TOO_SHORT_FOR_SHOT_COUNT"]
    assert script(_script(4, 9.0), objective=None).outcome is CreativeQualityOutcome.PASS


# ── Through the real Coordinator, SQLite and Ollama adapter ────────────────────────────


@pytest.fixture
def runtime(tmp_path):  # type: ignore[no-untyped-def]
    rt = open_runtime(tmp_path)
    yield rt
    rt.database.close()


def _goal_job(rt: Runtime, profile: str, key: str):  # type: ignore[no-untyped-def]
    job = rt.service.create_job(
        source_result_package_ids=[rt.result_id], creative_profile=profile,
        creative_objective=GOAL, idempotency_key=key,
    )
    task = next(
        item for item in rt.queue.list(limit=50)
        if item.resource_tag == f"creative:{job.creative_job_id}"
    )
    return job, task


def _three_shot_stage_outputs(ref: str) -> list[dict]:
    parts = stage_outputs(ref)
    return [parts["idea"], parts["brief"], _script(3, 4.0)]


def test_v1_goal_with_a_bad_first_shot_plan_is_corrected_to_an_executable_three_shot_plan(
    runtime: Runtime,
) -> None:
    job, task = _goal_job(runtime, V1, "three-v1")
    ref = runtime.source_ref_for(job.creative_job_id)
    bad = _shots(4, intent="TEXT_CARD")  # 4 shots and a never-executable intent
    good = _shots(3)
    double = OllamaDouble([*_three_shot_stage_outputs(ref), bad, good])
    summary = runtime.coordinator(double.adapter).handler(task)
    assert summary.summary["status"] == "creative_ready"

    # Every stage saw the user's directives; the retry carried the exact repair.
    assert all("Exactly 3 shots" in double.data(i)["creative_objective"] for i in range(5))
    retry = double.requests[4]["user"]
    assert "Correction for this one retry only:" in retry and "exactly 3 shots" in retry

    package = runtime.service.get_package(job.creative_job_id)
    assert package is not None
    plan = compile_production_plan(str(uuid4()), package.manifest, package.package_digest)
    assert len(plan.tasks) == 3
    assert {t.execution_disposition.value for t in plan.tasks} == {"Executable"}
    assert {t.workflow_id for t in plan.tasks} == {"comfy.wan22.ti2v5b.t2v.v1"}
    assert {t.trusted_input_asset_ref for t in plan.tasks} == {None}
    assert plan.target_runtime_ms == 12000 and {t.frame_count for t in plan.tasks} == {97}


def test_v1_goal_without_directives_behaves_exactly_as_before(runtime: Runtime) -> None:
    job = runtime.service.create_job(
        source_result_package_ids=[runtime.result_id], creative_profile=V1,
        creative_objective="Create a short product education video.", idempotency_key="plain",
    )
    task = next(
        item for item in runtime.queue.list(limit=50)
        if item.resource_tag == f"creative:{job.creative_job_id}"
    )
    ref = runtime.source_ref_for(job.creative_job_id)
    parts = stage_outputs(ref)
    shots = _shots(5, 2.4)  # five shots, 12 s: no directive, so no count rule applies
    double = OllamaDouble([parts["idea"], parts["brief"], _script(3, 4.0), shots])
    summary = runtime.coordinator(double.adapter).handler(task)
    assert summary.summary["status"] == "creative_ready" and len(double.requests) == 4
    package = runtime.service.get_package(job.creative_job_id)
    assert package is not None
    assert len(package.manifest["stage_results"]["shot_plan.v1"]["shots"]) == 5


def test_v2_bible_is_held_to_the_requested_shot_count(runtime: Runtime) -> None:
    job, task = _goal_job(runtime, V2, "three-v2")
    ref = runtime.source_ref_for(job.creative_job_id)
    wrong = good_bible()  # four shots
    wrong["arc"] = [{"beat_id": f"beat-{n:03d}", "role": role}
                    for n, role in ((1, "HOOK"), (2, "DEMO"), (3, "CTA"))]
    right = deepcopy(wrong)
    right["shots"] = [dict(s, duration_seconds=4.0, beat_id=f"beat-{i:03d}", order=i,
                           shot_id=f"shot-{i:03d}")
                      for i, s in enumerate(wrong["shots"][:3], start=1)]
    right["shots"][2]["featured"] = ["SUBJECT", "PRODUCT"]
    double = OllamaDouble([*_three_shot_stage_outputs(ref), wrong, right])
    summary = runtime.coordinator(double.adapter).handler(task)
    assert summary.summary["status"] == "creative_ready"
    constraints = double.data(3)["director_constraints"]
    assert constraints["required_shot_count"] == 3 and constraints["text_to_video_only"] is True
    assert "SHOT_COUNT_MISMATCH" in double.requests[4]["user"]
    package = runtime.service.get_package(job.creative_job_id)
    assert package is not None
    plan = compile_production_plan(str(uuid4()), package.manifest, package.package_digest)
    assert len(plan.tasks) == 3 and {t.execution_disposition.value for t in plan.tasks} == {
        "Executable"
    }
