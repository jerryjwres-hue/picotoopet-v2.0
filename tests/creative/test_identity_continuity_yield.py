"""Do identity, scene and light constraints reach each of the three independent Wan prompts?

Audit pins plus the Creative-side gates that make them real. Synthetic data only: these tests
prove which fields travel to the Production prompt and that contradictory or duplicated shot
text is repaired before the GPU, not that any picture improves.
"""

from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest
from director_fixtures import EVIDENCE, V1, V2, OllamaDouble, Runtime, good_bible, open_runtime
from test_three_shot_reliability import GOAL, _evaluate, _script, _shots, stage_outputs

from picotoopet_core.creative.director import (
    actions_too_similar,
    negative_conflicts,
    parse_goal_directives,
)
from picotoopet_core.creative.models import CreativeQualityOutcome, CreativeStageKind
from picotoopet_core.creative.video_bible import CAMERA_PHRASE, CameraMovement
from picotoopet_core.production.compiler import compile_production_plan

ROOT = Path(__file__).resolve().parents[2]
ANCHORS = ["cream golden retriever", "teal collar", "matte-white round tag"]


def _manifest(shots: list[dict], script: dict | None = None, notes: list[str] | None = None):
    out = stage_outputs("result:finding:1")
    brief = deepcopy(out["brief"])
    brief["continuity_notes"] = notes or []
    return {
        "creative_package_id": str(uuid4()), "project_key": "goal-x", "quality_outcome": "PASS",
        "stage_results": {
            "creative_brief.v1": brief, "script.v1": script or _script(),
            "shot_plan.v1": {"schema_version": "1.0", "creative_profile": V1, "shots": shots,
                             "warnings": [], "needs_deep_ai": False, "needs_human": False},
        },
    }


def _shot(n: int, **fields) -> dict:
    base = _shots(3)["shots"][n - 1]
    base.update(fields)
    return base


# ── Audit pins: exactly which Creative fields become Comfy text ────────────────────────


def test_only_these_creative_fields_reach_the_independent_wan_prompts() -> None:
    shots = [
        _shot(n, subject=f"SUBJ{n}", environment=f"ENV{n}", action=f"ACT{n}", framing=f"FRM{n}",
               lighting_style=f"LGT{n}", continuity_keys=[f"KEY{n}A", f"KEY{n}B"],
               required_facts=[f"FACT{n}"], text_reference=f"TXTREF{n}",
               production_notes=f"NOTES{n}")
        for n in (1, 2, 3)
    ]
    script = _script()
    for beat in script["beats"]:
        beat["voiceover"] = "VOICEOVERLINE"
        beat["visual_intent"] = "VISUALINTENT"
    plan = compile_production_plan(
        str(uuid4()), _manifest(shots, script, notes=["GLOBALNOTE"]), "e" * 64
    )
    for n, task in enumerate(plan.tasks, start=1):
        prompt = task.positive_prompt
        for token in (f"SUBJ{n}", "GLOBALNOTE", f"ENV{n}", f"ACT{n}", f"FRM{n}", f"LGT{n}",
                      f"KEY{n}A", f"KEY{n}B", f"FACT{n}"):
            assert token in prompt, (n, token)
        # Each prompt is independent: no other shot's text leaks into it.
        assert all(f"SUBJ{m}" not in prompt for m in (1, 2, 3) if m != n)
        # These never reach Wan, so they cannot carry identity or continuity.
        for lost in (f"TXTREF{n}", f"NOTES{n}", "VOICEOVERLINE", "VISUALINTENT"):
            assert lost not in prompt, lost
    assert len({t.seed for t in plan.tasks}) == 3  # independent noise per shot


def test_windows_forwards_the_compiled_prompt_verbatim_and_the_negative_is_fixed() -> None:
    """Read-only pin of the Windows contract this audit relies on (G006 owns the files)."""

    binder = (ROOT / "windows/desktop/src/PicotooPet.Desktop.Core/Production"
              / "ComfyWorkflowTemplateValidator.cs").read_text(encoding="utf-8")
    assert 'JsonValue.Create(task.PositivePrompt)' in binder
    template = json.loads(
        (ROOT / "windows/production/workflows/wan22-ti2v5b-t2v-api-v1.json").read_text("utf-8")
    )
    negative = next(
        node["inputs"]["text"] for node in template.values()
        if node["class_type"] == "CLIPTextEncode"
        and node["inputs"]["text"] != "__PICOTOO_POSITIVE_PROMPT__"
    )
    for avoided in ("静态", "过曝", "杂乱背景", "字幕", "细节模糊不清"):
        assert avoided in negative


# ── Gate: shared anchors, distinct actions, no clash with the fixed negative prompt ────


def _plan(shots, objective=GOAL):  # type: ignore[no-untyped-def]
    raw = {"schema_version": "1.0", "creative_profile": V1, "shots": shots, "warnings": [],
           "needs_deep_ai": False, "needs_human": False}
    return _evaluate(CreativeStageKind.SHOT_PLAN, raw, {"script.v1": _script()}, objective)


def test_healthy_plan_passes() -> None:
    assert _plan(_shots(3)["shots"]).outcome is CreativeQualityOutcome.PASS


def test_every_shot_must_repeat_the_same_identity_anchors() -> None:
    shots = _shots(3)["shots"]
    shots[1]["continuity_keys"] = []
    shots[2]["continuity_keys"] = ["a brown dog"]
    decision = _plan(shots)
    assert decision.outcome is CreativeQualityOutcome.RETRY
    assert decision.reasons == ["SHOT_IDENTITY_ANCHORS_MISSING"]
    text = decision.correction_instruction or ""
    assert "continuity_keys of EVERY shot" in text and "word for word" in text


def test_one_shared_anchor_is_not_enough() -> None:
    shots = _shots(3)["shots"]
    for shot in shots:
        shot["continuity_keys"] = ["teal collar"]
    assert _plan(shots).reasons == ["SHOT_IDENTITY_ANCHORS_MISSING"]


def test_anchor_comparison_ignores_case_and_spacing() -> None:
    shots = _shots(3)["shots"]
    shots[1]["continuity_keys"] = ["Cream  Golden Retriever", "TEAL collar"]
    assert _plan(shots).outcome is CreativeQualityOutcome.PASS


def test_near_duplicate_actions_are_retried_naming_the_pair() -> None:
    shots = _shots(3)["shots"]
    shots[1]["action"] = "the dog sits and tilts its head slightly"
    decision = _plan(shots)
    assert decision.reasons == ["SHOT_ACTIONS_NOT_DISTINCT"]
    assert "shot-001 and shot-002" in (decision.correction_instruction or "")


def test_action_similarity_works_for_english_and_chinese() -> None:
    assert actions_too_similar("the dog sits and waits", "the dog sits and waits.")
    assert not actions_too_similar("the dog sits", "the dog runs across the grass")
    assert actions_too_similar("小狗坐在门廊上摇尾巴", "小狗坐在门廊上摇尾巴")
    assert not actions_too_similar("小狗坐在门廊上摇尾巴", "项圈标签扣在项圈上")


@pytest.mark.parametrize(
    "word", ["static", "overexposed", "cluttered", "subtitles", "caption", "blurry", "garish"]
)
def test_words_the_fixed_negative_prompt_forbids_are_not_allowed_in_the_positive(
    word: str,
) -> None:
    shots = _shots(3)["shots"]
    shots[2]["framing"] = f"medium shot, {word} look"
    decision = _plan(shots)
    assert decision.reasons == ["PROMPT_CONTRADICTS_NEGATIVE"]
    assert word in (decision.correction_instruction or "")


def test_negative_conflicts_matches_whole_words_only() -> None:
    assert negative_conflicts(["a static look"]) == ["static"]
    assert negative_conflicts(["a static camera"]) == []  # fixed-camera wording is allowed
    assert negative_conflicts(["the statically lit room", "a stately dog"]) == []


def test_plain_goals_keep_the_existing_freedom() -> None:
    drifting = _shots(3)["shots"]
    for shot in drifting:
        shot["continuity_keys"] = []
        shot["action"] = "waits"
        shot["framing"] = "static shot"
    for objective in (None, "Create a short product education video."):
        assert _plan(drifting, objective).outcome is CreativeQualityOutcome.PASS
    # A count alone (without T2V-only) already asks for a coherent multi-shot sequence.
    assert parse_goal_directives("Exactly 3 shots").shot_count == 3
    assert _plan(drifting, "Exactly 3 shots, landscape").reasons[:1] == [
        "SHOT_IDENTITY_ANCHORS_MISSING"
    ]


# ── v2 Video Bible carries the same discipline ─────────────────────────────────────────


def test_v2_static_camera_phrase_no_longer_collides_with_the_negative_prompt() -> None:
    assert negative_conflicts(list(CAMERA_PHRASE.values())) == []
    assert "no camera movement" in CAMERA_PHRASE[CameraMovement.STATIC]


def _three_shot_bible() -> dict:
    bible = good_bible()
    bible["arc"] = [{"beat_id": f"beat-{n:03d}", "role": role}
                    for n, role in ((1, "HOOK"), (2, "DEMO"), (3, "CTA"))]
    bible["shots"] = [dict(s, duration_seconds=4.0, beat_id=f"beat-{i:03d}", order=i,
                           shot_id=f"shot-{i:03d}")
                      for i, s in enumerate(bible["shots"][:3], start=1)]
    bible["shots"][2]["featured"] = ["SUBJECT", "PRODUCT"]
    return bible


@pytest.fixture
def runtime(tmp_path):  # type: ignore[no-untyped-def]
    rt = open_runtime(tmp_path)
    yield rt
    rt.database.close()


def _run_v2(rt: Runtime, bible: dict, second: dict | None = None):  # type: ignore[no-untyped-def]
    job = rt.service.create_job(
        source_result_package_ids=[rt.result_id], creative_profile=V2,
        creative_objective=GOAL, idempotency_key=f"yield-{uuid4()}",
    )
    task = next(i for i in rt.queue.list(limit=50)
                if i.resource_tag == f"creative:{job.creative_job_id}")
    parts = stage_outputs(rt.source_ref_for(job.creative_job_id))
    outputs = [parts["idea"], parts["brief"], _script(3, 4.0), bible]
    if second is not None:
        outputs.append(second)
    double = OllamaDouble(outputs)
    summary = rt.coordinator(double.adapter).handler(task)
    return job, double, summary


def test_v2_bible_with_too_few_anchors_duplicate_actions_or_clashing_words_is_repaired(
    runtime: Runtime,
) -> None:
    bad = _three_shot_bible()
    bad["continuity_anchors"] = ["cream golden retriever"]
    bad["global_continuity_notes"] = []
    bad["shots"][1]["visible_action"] = bad["shots"][0]["visible_action"] + " slowly"
    bad["scenes"][0]["environment_phrase"] = "static porch with a cluttered garden"
    job, double, summary = _run_v2(runtime, bad, _three_shot_bible())
    assert summary.summary["status"] == "creative_ready"
    retry = double.requests[4]["user"]
    for code in ("CONTINUITY_ANCHORS_TOO_FEW", "SHOT_ACTIONS_NOT_DISTINCT",
                 "PROMPT_CONTRADICTS_NEGATIVE"):
        assert code in retry
    package = runtime.service.get_package(job.creative_job_id)
    assert package is not None
    plan = compile_production_plan(str(uuid4()), package.manifest, package.package_digest)
    assert len(plan.tasks) == 3
    for task in plan.tasks:
        for anchor in ANCHORS:
            assert anchor in task.positive_prompt
    assert len({re.sub(r"\W+", " ", t.positive_prompt) for t in plan.tasks}) == 3


# ── End to end: v1 Goal whose first plan drifts is repaired into three consistent prompts


def test_v1_first_plan_with_drift_and_duplicate_actions_is_repaired_before_the_gpu(
    runtime: Runtime,
) -> None:
    job = runtime.service.create_job(
        source_result_package_ids=[runtime.result_id], creative_profile=V1,
        creative_objective=GOAL, idempotency_key="yield-v1",
    )
    task = next(i for i in runtime.queue.list(limit=50)
                if i.resource_tag == f"creative:{job.creative_job_id}")
    parts = stage_outputs(runtime.source_ref_for(job.creative_job_id))
    drifting = _shots(3)["shots"]
    for shot in drifting:
        shot["action"] = "the dog stands in the park"
        shot["continuity_keys"] = []
    drifting[1]["subject"] = "the dog"
    good = _shots(3)["shots"]
    for shot in good:
        shot["continuity_keys"] = ["cream golden retriever", "teal collar", "soft daylight"]
    double = OllamaDouble([parts["idea"], parts["brief"], _script(3, 4.0),
                           {"schema_version": "1.0", "creative_profile": V1,
                            "shots": drifting, "warnings": [], "needs_deep_ai": False,
                            "needs_human": False},
                           {"schema_version": "1.0", "creative_profile": V1,
                            "shots": good, "warnings": [], "needs_deep_ai": False,
                            "needs_human": False}])
    summary = runtime.coordinator(double.adapter).handler(task)
    assert summary.summary["status"] == "creative_ready"
    retry = double.requests[4]["user"]
    assert "continuity_keys of EVERY shot" in retry
    assert "shot-001 and shot-002" in retry
    package = runtime.service.get_package(job.creative_job_id)
    assert package is not None
    plan = compile_production_plan(str(uuid4()), package.manifest, package.package_digest)
    prompts = [t.positive_prompt for t in plan.tasks]
    for prompt in prompts:
        for anchor in ("cream golden retriever", "teal collar", "soft daylight"):
            assert anchor in prompt
    actions = [re.search(r"(the dog [^;]+|a small white tag[^;]+)", p).group(1) for p in prompts]
    assert len(set(actions)) == 3
    assert all(EVIDENCE not in prompt for prompt in prompts)  # evidence ids never reach Wan


# ── The recommended first real-run Goal must satisfy every deterministic gate it triggers ──

FIRST_RUN_GOAL = (
    "Exactly 3 shots, text-to-video only: no reference image, no image-to-video, no text cards. "
    "Each shot 4.0 seconds, total 12 seconds, landscape. In continuity_keys of every shot repeat "
    "word for word: cream golden retriever, teal collar, matte-white round tag, sunny wooden "
    "porch, soft morning light. Shot 1 hook: the dog sits on the porch and tilts its head toward "
    "the camera. Shot 2 demo: close view of the collar while the small round tag rests on it and "
    "the dog turns its head slightly. Shot 3 payoff: the dog trots toward the camera and sits, "
    "the tag visible on the collar. One action per shot; no on-screen text, no logo, no hands."
)


def test_first_real_run_goal_text_is_parsed_and_cannot_trip_the_negative_vocabulary() -> None:
    directives = parse_goal_directives(FIRST_RUN_GOAL)
    assert (directives.shot_count, directives.text_to_video_only) == (3, True)
    assert negative_conflicts([FIRST_RUN_GOAL]) == []
    assert len(FIRST_RUN_GOAL) < 800  # constraints come first and survive the 2000-char cut
