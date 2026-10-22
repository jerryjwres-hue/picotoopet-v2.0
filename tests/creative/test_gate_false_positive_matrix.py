"""Fixed positive / negative cases for the multi-shot Creative gates.

Each row states the *desired* decision for a realistic model output. A wrong REJECT costs one of
the stage's two model attempts for nothing; a wrong ACCEPT lets a defect reach the GPU. Rows that
document a known, accepted miss say so in their id. Synthetic text only.
"""

from __future__ import annotations

import pytest
from director_fixtures import EVIDENCE, V1, Runtime, open_runtime
from test_three_shot_reliability import GOAL, _evaluate, _script, _shots, stage_outputs

from picotoopet_core.creative.director import (
    near_duplicate_actions,
    negative_conflicts,
    parse_goal_directives,
)
from picotoopet_core.creative.models import CreativeQualityOutcome as Outcome
from picotoopet_core.creative.models import CreativeStageKind

PASS, RETRY = Outcome.PASS, Outcome.RETRY


def _decide(shots, objective=GOAL, script=None):  # type: ignore[no-untyped-def]
    raw = {"schema_version": "1.0", "creative_profile": V1, "shots": shots, "warnings": [],
           "needs_deep_ai": False, "needs_human": False}
    return _evaluate(
        CreativeStageKind.SHOT_PLAN, raw, {"script.v1": script or _script()}, objective
    )


def _with(**fields):  # type: ignore[no-untyped-def]
    """Same value on every shot."""

    shots = _shots(3)["shots"]
    for shot in shots:
        for name, value in fields.items():
            shot[name] = list(value) if isinstance(value, list) else value
    return shots


def _each(field, values):  # type: ignore[no-untyped-def]
    """One value per shot."""

    shots = _shots(3)["shots"]
    for shot, value in zip(shots, values, strict=True):
        shot[field] = value
    return shots


# ── continuity_keys: identical is not enough, they must mean something ─────────────────


@pytest.mark.parametrize(
    ("keys", "outcome"),
    [
        (["cream golden retriever", "teal collar"], PASS),
        (["金毛犬", "蓝色项圈"], PASS),
        (["a", "b"], RETRY),
        (["x1", "x2"], RETRY),
        (["video", "scene"], RETRY),
        (["same", "consistent"], RETRY),
        (["n/a", "tbd"], RETRY),
        (["teal collar", "a"], RETRY),
        (["teal collar"], RETRY),
    ],
    ids=["identity", "cjk", "single-letters", "tokens", "generic-nouns", "filler-words",
         "placeholders", "one-real-one-filler", "single-anchor"],
)
def test_shared_keys_must_carry_identity_meaning(keys, outcome) -> None:  # type: ignore[no-untyped-def]
    decision = _decide(_with(continuity_keys=keys))
    assert decision.outcome is outcome
    if outcome is RETRY:
        assert decision.reasons == ["SHOT_IDENTITY_ANCHORS_MISSING"]


def test_anchor_matching_ignores_case_spacing_punctuation_and_width() -> None:
    per_shot = [
        ["teal collar.", "Cream Golden Retriever"],
        ["teal  collar", "cream golden retriever,"],
        ["Teal Collar!", "cream-golden retriever"],
    ]
    assert _decide(_each("continuity_keys", per_shot)).outcome is PASS


# ── actions: boilerplate must not hide a real difference, paraphrase is a known miss ───

PORCH = "the cream golden retriever on the sunny wooden porch"


@pytest.mark.parametrize(
    ("actions", "outcome"),
    [
        (["the dog sits and tilts its head", "a small white tag clicks onto the collar",
          "the dog runs across the grass toward the camera"], PASS),
        ([f"{PORCH} sits down and tilts its head", f"{PORCH} lowers its head to sniff the tag",
          f"{PORCH} trots toward the camera and sits"], PASS),
        (["小狗在阳光明媚的木质门廊上坐下", "小狗在阳光明媚的木质门廊上奔跑",
          "小狗在阳光明媚的木质门廊上趴下休息"], PASS),
        (["the dog sits", "the dog runs", "the dog jumps"], PASS),
        (["the dog sits and tilts its head", "the dog sits and tilts its head slightly",
          "the dog runs across the grass"], RETRY),
        (["the dog sits and waits", "the dog sits and waits.", "the dog runs"], RETRY),
        ([f"{PORCH} sits down", f"{PORCH} sits down", f"{PORCH} trots toward the camera"], RETRY),
        (["小狗坐在门廊上摇尾巴", "小狗坐在门廊上摇尾巴", "项圈标签扣在项圈上"], RETRY),
        # Accepted limitation: paraphrases with different words are not detected.
        (["the dog sits calmly", "the dog is sitting quietly", "the dog runs"], PASS),
    ],
    ids=["short-distinct", "english-boilerplate", "chinese-boilerplate", "one-word-verbs",
         "adverb-only", "punctuation-only", "boilerplate-duplicate", "chinese-duplicate",
         "known-miss-paraphrase"],
)
def test_action_distinctness_is_about_the_action_not_the_scene(actions, outcome) -> None:  # type: ignore[no-untyped-def]
    decision = _decide(_each("action", actions))
    assert decision.outcome is outcome
    if outcome is RETRY:
        assert decision.reasons == ["SHOT_ACTIONS_NOT_DISTINCT"]


def test_near_duplicate_pair_is_reported_by_position() -> None:
    assert near_duplicate_actions(["the dog sits", "the dog runs", "the dog sits"]) == (0, 2)
    assert near_duplicate_actions(["the dog sits", "the dog runs"]) is None
    assert near_duplicate_actions([]) is None


# ── negative-prompt vocabulary: fixed-camera wording must stay allowed ─────────────────


@pytest.mark.parametrize(
    ("framing", "outcome"),
    [
        ("medium shot, static camera", PASS),
        ("wide shot on a static tripod", PASS),
        ("static shot of the porch", PASS),
        ("固定机位，静态镜头", PASS),
        ("locked-off camera", PASS),
        ("fixed camera", PASS),
        ("medium shot, blurry background", PASS),
        ("medium shot, shallow depth of field with a blurry foreground", PASS),
        ("a static image of the dog", RETRY),
        ("static pose, static background", RETRY),
        ("blurry fur and a blurry face", RETRY),
        ("overexposed sky", RETRY),
        ("cluttered room", RETRY),
        ("no subtitles", RETRY),
        ("画面过曝", RETRY),
        ("杂乱背景，字幕", RETRY),
    ],
)
def test_negative_vocabulary_only_rejects_what_cancels_itself(framing, outcome) -> None:  # type: ignore[no-untyped-def]
    decision = _decide(_with(framing=framing))
    assert decision.outcome is outcome, framing
    if outcome is RETRY:
        assert decision.reasons == ["PROMPT_CONTRADICTS_NEGATIVE"]


def test_conflict_words_are_reported_once_in_order() -> None:
    assert negative_conflicts(["cluttered and overexposed", "cluttered", "字幕"]) == [
        "cluttered", "overexposed", "字幕",
    ]


# ── "N shots" is not always a shot count ───────────────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "count"),
    [
        ("A video about 2 shots of espresso", None),
        ("three flu shots for the dog", None),
        ("a vaccine, 3 shots over a month", None),
        ("Make a video with 2 shots of espresso", None),
        ("Exactly 3 shots of the dog on the porch", 3),
        ("3-shot video", 3),
        ("请拍三个镜头", 3),
    ],
)
def test_shot_count_ignores_drinks_and_injections(text, count) -> None:  # type: ignore[no-untyped-def]
    assert parse_goal_directives(text).shot_count == count


# ── one repair must cover every defect, not one per attempt ────────────────────────────


def test_one_correction_lists_beat_coverage_anchor_and_action_defects_together() -> None:
    shots = _with(continuity_keys=[], action="the dog stands in the park")
    for shot in shots:
        shot["beat_id"] = "beat-001" if shot["order"] < 3 else "beat-002"  # beat-003 uncovered
    decision = _decide(shots)
    assert decision.outcome is RETRY
    assert set(decision.reasons) == {
        "SCRIPT_BEAT_NOT_COVERED", "SHOT_IDENTITY_ANCHORS_MISSING", "SHOT_ACTIONS_NOT_DISTINCT"
    }
    text = decision.correction_instruction or ""
    assert "beat-003" in text and "EVERY shot" in text and "different visible action" in text
    assert len(text) <= 2000


def test_unknown_beat_and_unknown_evidence_are_reported_with_the_other_defects() -> None:
    shots = _with(continuity_keys=[])
    shots[0]["beat_id"] = "beat-404"
    shots[1]["source_evidence_ids"] = ["reviews:key:invented"]
    decision = _decide(shots)
    assert {"UNKNOWN_SCRIPT_BEAT", "UNKNOWN_SOURCE_EVIDENCE_ID",
            "SHOT_IDENTITY_ANCHORS_MISSING"} <= set(decision.reasons)


def test_script_stage_reports_every_shot_count_bound_at_once() -> None:
    decision = _evaluate(CreativeStageKind.SCRIPT, _script(4, 9.0), {}, GOAL)
    assert decision.outcome is RETRY
    assert decision.reasons == ["SCRIPT_BEATS_EXCEED_SHOT_COUNT", "SCRIPT_TOO_LONG_FOR_SHOT_COUNT"]
    text = decision.correction_instruction or ""
    assert "at most 3 script beats" in text and "at most 15.0 seconds" in text


def test_healthy_plan_still_passes_with_evidence_and_beats() -> None:
    assert _decide(_shots(3)["shots"]).outcome is PASS
    assert EVIDENCE


@pytest.fixture
def runtime(tmp_path):  # type: ignore[no-untyped-def]
    rt = open_runtime(tmp_path)
    yield rt
    rt.database.close()


__all__ = ["Runtime", "stage_outputs"]
