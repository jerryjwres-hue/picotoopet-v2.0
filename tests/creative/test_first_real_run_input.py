"""The exact input for the first real 3 x 4 s text-to-video run, checked against the contracts.

Model outputs are synthetic and written to follow the Goal; they prove the Goal parses to the
intended directives, that a compliant answer passes every gate and compiles to three
Executable 4.0 s tasks with the identity words in each independent prompt, and that explicitly
requested shot durations are enforced. They say nothing about picture quality.
"""

from __future__ import annotations

import re
from uuid import uuid4

import pytest
from director_fixtures import EVIDENCE, V1
from test_three_shot_reliability import GOAL, _evaluate, _script, stage_outputs

from picotoopet_core.creative.director import negative_conflicts, parse_goal_directives
from picotoopet_core.creative.models import CreativeQualityOutcome as Outcome
from picotoopet_core.creative.models import CreativeStageKind
from picotoopet_core.production.compiler import compile_production_plan

FIRST_RUN_GOAL = (
    "Exactly 3 shots, text-to-video only (T2V). Each shot 4.0 seconds, total 12 seconds, "
    "landscape. Repeat these identity anchors word for word in continuity_keys of every shot: "
    "cream golden retriever, teal collar, matte-white round tag, sunny wooden porch, soft "
    "morning light. Shot 1 hook: the dog sits on the porch and tilts its head toward the "
    "camera. Shot 2 demo: close view of the collar while the small round tag rests on it and "
    "the dog turns its head slightly. Shot 3 payoff: the dog trots toward the camera and sits, "
    "the tag visible on the collar. One simple action per shot. Only the dog, the collar and "
    "the tag appear in frame; the collar and tag are plain, unmarked surfaces; natural, soft "
    "colors."
)
ANCHORS = ["cream golden retriever", "teal collar", "matte-white round tag",
           "sunny wooden porch", "soft morning light"]
ACTIONS = [
    "the dog sits on the porch and tilts its head toward the camera",
    "close view of the collar while the small round tag rests on it and the dog turns its "
    "head slightly",
    "the dog trots toward the camera and sits, the tag visible on the collar",
]


def _plan(durations=(4.0, 4.0, 4.0)):  # type: ignore[no-untyped-def]
    shots = [
        {"shot_id": f"shot-{n:03d}", "beat_id": f"beat-{n:03d}", "order": n,
         "duration_seconds": durations[n - 1],
         "subject": "a cream golden retriever wearing a teal collar",
         "environment": "a sunny wooden porch", "action": ACTIONS[n - 1],
         "framing": ("close-up" if n == 2 else "medium shot") + ", fixed camera",
         "lighting_style": "soft morning light", "continuity_keys": list(ANCHORS),
         "required_facts": [], "source_evidence_ids": [], "text_reference": None,
         "production_notes": "renderer-neutral", "render_intent": "GENERATIVE_VIDEO"}
        for n in (1, 2, 3)
    ]
    return {"schema_version": "1.0", "creative_profile": V1, "shots": shots, "warnings": [],
            "needs_deep_ai": False, "needs_human": False}


# ── the Goal text itself ───────────────────────────────────────────────────────────────


def test_goal_text_parses_to_the_intended_directives() -> None:
    directives = parse_goal_directives(FIRST_RUN_GOAL)
    assert (directives.shot_count, directives.text_to_video_only) == (3, True)
    assert directives.shot_seconds == 4.0


def test_goal_text_is_positive_only_and_cannot_trip_the_negative_vocabulary() -> None:
    """Text encoders do not understand negation: a 'no hands' echoed into a shot field tends
    to draw hands. The Goal therefore says what is in frame instead of what is not."""

    assert re.search(r"\b(no|not|without|never|don't|avoid)\b", FIRST_RUN_GOAL.casefold()) is None
    assert negative_conflicts([FIRST_RUN_GOAL]) == []
    assert len(FIRST_RUN_GOAL) < 900  # directives come first and survive the 2000-char cut


def test_goal_text_stays_inside_the_script_stage_bounds() -> None:
    script = _evaluate(CreativeStageKind.SCRIPT, _script(3, 4.0), {}, FIRST_RUN_GOAL)
    assert script.outcome is Outcome.PASS


# ── a compliant answer passes and becomes three Executable 4.0 s tasks ────────────────


def _decide(raw, objective=FIRST_RUN_GOAL):  # type: ignore[no-untyped-def]
    return _evaluate(CreativeStageKind.SHOT_PLAN, raw, {"script.v1": _script(3, 4.0)}, objective)


def test_a_compliant_plan_passes_every_gate() -> None:
    assert _decide(_plan()).outcome is Outcome.PASS


def test_compliant_plan_compiles_to_three_independent_prompts_with_the_same_identity() -> None:
    out = stage_outputs("result:finding:1")
    manifest = {
        "creative_package_id": str(uuid4()), "project_key": "goal-x", "quality_outcome": "PASS",
        "stage_results": {"creative_brief.v1": out["brief"], "script.v1": _script(3, 4.0),
                          "shot_plan.v1": _plan()},
    }
    plan = compile_production_plan(str(uuid4()), manifest, "e" * 64)
    assert [t.execution_disposition.value for t in plan.tasks] == ["Executable"] * 3
    assert {t.workflow_id for t in plan.tasks} == {"comfy.wan22.ti2v5b.t2v.v1"}
    assert [t.frame_count for t in plan.tasks] == [97, 97, 97]
    assert [t.target_duration_ms for t in plan.tasks] == [4000, 4000, 4000]
    assert plan.target_runtime_ms == 12000
    assert len({t.seed for t in plan.tasks}) == 3
    prompts = [t.positive_prompt for t in plan.tasks]
    for prompt in prompts:
        for anchor in ANCHORS:
            assert anchor in prompt
        assert negative_conflicts([prompt]) == []
        # no negation, no version label, no evidence id reaches the encoder
        assert re.search(r"\b(no|not|without|never)\b", prompt.casefold()) is None
        assert "wan22-shot-prompt" not in prompt and EVIDENCE not in prompt
        assert len(prompt) < 700
    assert len({p.split(";")[2] for p in prompts}) == 3  # three different actions


# ── explicitly requested shot length is enforced (an exact ask, not a heuristic) ───────


@pytest.mark.parametrize(
    ("text", "seconds"),
    [
        ("Each shot 4.0 seconds", 4.0),
        ("every shot 3 seconds long", 3.0),
        ("4 seconds per shot", 4.0),
        ("three 4-second shots", 4.0),
        ("每个镜头4秒", 4.0),
        ("每镜头 3.5 秒", 3.5),
        ("each shot at most 5 seconds", None),
        ("shots up to 4 seconds", None),
        ("each shot 9 seconds", None),
        ("a 12 second video", None),
        ("each shot 3 seconds, each shot 5 seconds", None),
        ("", None),
    ],
)
def test_requested_shot_length_is_parsed_only_when_exact(text, seconds) -> None:  # type: ignore[no-untyped-def]
    assert parse_goal_directives(text).shot_seconds == seconds


def test_shots_that_ignore_the_requested_length_are_retried_naming_each_shot() -> None:
    decision = _decide(_plan((5.0, 4.0, 3.0)))
    assert decision.outcome is Outcome.RETRY
    assert decision.reasons == ["SHOT_DURATION_NOT_AS_REQUESTED"]
    text = decision.correction_instruction or ""
    assert "exactly 4.0 seconds" in text and "shot-001" in text and "shot-003" in text
    assert "shot-002" not in text


def test_length_is_not_enforced_when_the_goal_does_not_ask_for_it() -> None:
    assert _decide(_plan((5.0, 4.0, 3.0)), objective=GOAL.replace("Each shot 4.0 seconds, ",
                                                                  "")).outcome is Outcome.PASS
    assert _decide(_plan((5.0, 4.0, 3.0)), objective=None).outcome is Outcome.PASS


def test_v2_bible_is_held_to_the_requested_shot_length_and_told_about_it() -> None:
    from director_fixtures import good_bible

    from picotoopet_core.creative.director import director_constraints
    from picotoopet_core.creative.models import CreativeBriefResult, CreativeScriptResult
    from picotoopet_core.creative.video_bible import VideoBibleDraft, evaluate_video_bible

    out = stage_outputs("result:finding:1")
    brief = CreativeBriefResult.model_validate(out["brief"])
    script = CreativeScriptResult.model_validate(_script(3, 4.0))
    directives = parse_goal_directives(FIRST_RUN_GOAL)
    constraints = director_constraints(brief, script, directives)
    assert constraints["required_shot_seconds"] == 4.0 and constraints["required_shot_count"] == 3

    bible = good_bible()
    bible["arc"] = [{"beat_id": f"beat-{n:03d}", "role": role}
                    for n, role in ((1, "HOOK"), (2, "DEMO"), (3, "CTA"))]
    bible["shots"] = [dict(s, duration_seconds=4.0, beat_id=f"beat-{i:03d}", order=i,
                           shot_id=f"shot-{i:03d}")
                      for i, s in enumerate(bible["shots"][:3], start=1)]
    bible["shots"][2]["featured"] = ["SUBJECT", "PRODUCT"]
    findings = evaluate_video_bible(
        VideoBibleDraft.model_validate(bible), brief=brief, script=script,
        evidence_ids={EVIDENCE}, required_shot_count=3, required_shot_seconds=4.0,
    )
    assert [f.code for f in findings] == []
    bible["shots"][1]["duration_seconds"] = 5.0
    findings = evaluate_video_bible(
        VideoBibleDraft.model_validate(bible), brief=brief, script=script,
        evidence_ids={EVIDENCE}, required_shot_count=3, required_shot_seconds=4.0,
    )
    assert "SHOT_DURATION_NOT_AS_REQUESTED" in [f.code for f in findings]
