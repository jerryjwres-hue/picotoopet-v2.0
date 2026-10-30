"""The story gate and keyframe review proposal are the DEFAULT for three-shot Creative v2 work.

No magic phrase: eligibility comes from typed facts (an exact shot-count directive of 3, or a
Bible with exactly three shots). Real Coordinator, SQLite and Ollama adapter transport; only the
model JSON is scripted. Text checks only: no image exists, nothing is approved, no GPU is used.
"""

from __future__ import annotations

import json
import re
from copy import deepcopy
from uuid import uuid4

import pytest
import story_fixture_2026 as fx
from director_fixtures import V1, V2, OllamaDouble, Runtime, open_runtime, stage_outputs

from picotoopet_core.creative.director import (
    GoalDirectives,
    parse_goal_directives,
    story_gate_applies,
)
from picotoopet_core.creative.execution import CreativeIntelligenceCoordinator
from picotoopet_core.creative.models import CreativeJobStatus, CreativeStageKind
from picotoopet_core.creative.video_bible import (
    KEYFRAME_REVIEW_NOTICE,
    KEYFRAME_REVIEW_NOTICE_KEY,
    KeyframeKit,
    VideoBibleDraft,
    evaluate_story_storyboard,
)
from picotoopet_core.production.compiler import compile_production_plan

PLAIN_GOAL = "Create a short, warm product video about a clip-on pet tag."  # no keyword, no count
COUNT_GOAL = "Exactly 3 shots, text-to-video only. Each shot 4.0 seconds, total 12 seconds."


@pytest.fixture
def runtime(tmp_path):  # type: ignore[no-untyped-def]
    rt = open_runtime(tmp_path)
    yield rt
    rt.database.close()


def _job(rt: Runtime, goal: str, profile: str = V2, key: str = "d"):  # type: ignore[no-untyped-def]
    job = rt.service.create_job(
        source_result_package_ids=[rt.result_id], creative_profile=profile,
        creative_objective=goal, idempotency_key=key,
    )
    task = next(i for i in rt.queue.list(limit=50)
                if i.resource_tag == f"creative:{job.creative_job_id}")
    return job, task


def _outputs(rt: Runtime, job_id: str, bible: dict) -> list[dict]:
    ref = rt.source_ref_for(job_id)
    return [stage_outputs(ref)["idea"], {**fx.brief(), "required_source_finding_refs": [ref]},
            fx.script(), bible]


# ── Eligibility is typed, never a magic word ───────────────────────────────────────────


@pytest.mark.parametrize(
    ("goal", "bible_shots", "expected"),
    [
        (PLAIN_GOAL, 3, True), (PLAIN_GOAL, 4, False), (PLAIN_GOAL, 5, False),
        (COUNT_GOAL, 3, True), (COUNT_GOAL, 4, True),   # the Goal itself says three shots
        ("Exactly 4 shots.", 3, False),                  # an explicit other count wins
        ("Exactly 2 shots.", 4, False), (None, 3, True), ("", 6, False),
    ],
)
def test_eligibility_comes_from_the_shot_count_not_from_keywords(
    goal, bible_shots, expected
) -> None:
    assert story_gate_applies(parse_goal_directives(goal), bible_shots) is expected


def test_the_explicit_phrase_still_selects_the_gate_for_any_size() -> None:
    assert story_gate_applies(GoalDirectives(story_gate=True), 5) is True


# ── Default operation through the real Coordinator ─────────────────────────────────────


@pytest.mark.parametrize("goal", [PLAIN_GOAL, COUNT_GOAL])
def test_valid_three_shot_story_gets_the_kit_and_an_unambiguous_notice_by_default(
    runtime: Runtime, goal: str
) -> None:
    job, task = _job(runtime, goal)
    double = OllamaDouble(_outputs(runtime, job.creative_job_id, fx.bible()))
    summary = runtime.coordinator(double.adapter).handler(task)
    assert summary.summary["status"] == "creative_ready" and len(double.requests) == 4
    package = runtime.service.get_package(job.creative_job_id)
    assert package is not None
    stages = package.manifest["stage_results"]
    kit = KeyframeKit.model_validate(stages["keyframe_kit.v1"])
    assert {k.approval_status.value for k in kit.keyframes} == {"PENDING_HUMAN_REVIEW"}
    notice = stages[KEYFRAME_REVIEW_NOTICE_KEY]
    assert notice["images_exist"] is False and notice["render_authorized"] is False
    assert notice["approval_status"] == "PENDING_HUMAN_REVIEW"
    assert "human" in notice["requirement"] and "trusted references" in notice["requirement"]


def test_count_directive_tells_the_model_the_rules_without_changing_the_stage_digest(
    runtime: Runtime,
) -> None:
    job, task = _job(runtime, COUNT_GOAL)
    double = OllamaDouble(_outputs(runtime, job.creative_job_id, fx.bible()))
    runtime.coordinator(double.adapter).handler(task)
    context = double.data(3)
    assert context["director_constraints"]["story_quality_rules"]
    legacy = deepcopy(context)
    del legacy["director_constraints"]["story_quality_rules"]
    stage = runtime.repository.get_stage(job.creative_job_id, CreativeStageKind.VIDEO_BIBLE)
    assert stage is not None
    # A Bible stage persisted before the default existed has exactly this immutable input.
    assert stage.input_digest == CreativeIntelligenceCoordinator._digest(legacy)


def _drift(b: dict) -> None:
    b["shots"][1]["visible_action"] = "a hand clips the tag onto the green scarf under Mochi's chin"


def _floating_lamp(b: dict) -> None:
    b["shots"][2]["visible_action"] = (
        "Mochi walks left to right past the floating lamp, the tag swaying on the scarf"
    )


def _no_contact(b: dict) -> None:
    b["shots"][1].update(visible_action="a hand presents the charcoal tag",
                         opening_state="Mochi waits", closing_state="the charcoal tag is shown")
    b["shots"][0]["closing_state"] = "Mochi waits"


def _disconnected_payoff(b: dict) -> None:
    b["shots"][2]["opening_state"] = "Mochi sleeps on the sofa"
    b["shots"][2]["featured"] = ["SUBJECT"]


def _split_room(b: dict) -> None:
    b["scenes"].append({**b["scenes"][0], "scene_id": "kitchen"})
    b["shots"][2]["scene_id"] = "kitchen"


@pytest.mark.parametrize(
    ("mutate", "codes"),
    [
        (_drift, {"IDENTITY_COLOUR_DRIFT"}),
        (_floating_lamp, {"FLOATING_OBJECT_WORDING"}),
        (_no_contact, {"PRODUCT_CONTACT_MISSING"}),
        (_disconnected_payoff, {"STORY_STATE_GAP", "STORY_PAYOFF_MISSING"}),
        (_split_room, {"STORY_SCENE_SPLIT"}),
    ],
)
@pytest.mark.parametrize("goal", [PLAIN_GOAL, COUNT_GOAL])
def test_a_flawed_story_is_corrected_once_and_then_passes(
    runtime: Runtime, goal, mutate, codes
) -> None:
    bad = fx.bible()
    mutate(bad)
    job, task = _job(runtime, goal)
    double = OllamaDouble([*_outputs(runtime, job.creative_job_id, bad), fx.bible()])
    summary = runtime.coordinator(double.adapter).handler(task)
    assert summary.summary["status"] == "creative_ready" and len(double.requests) == 5
    for code in codes:
        assert code in double.requests[4]["user"]


def test_a_story_that_stays_flawed_is_needs_human_with_no_package_and_no_send(
    runtime: Runtime,
) -> None:
    bad = fx.bible()
    _drift(bad)
    job, task = _job(runtime, PLAIN_GOAL)
    double = OllamaDouble([*_outputs(runtime, job.creative_job_id, bad), bad])
    assert runtime.coordinator(double.adapter).handler(task).summary["status"] == "NeedsHuman"
    record = runtime.repository.get_job(job.creative_job_id)
    assert record.status is CreativeJobStatus.NEEDS_HUMAN
    assert record.failure_code == "CREATIVE_VIDEO_BIBLE_UNRESOLVED"
    assert runtime.service.get_package(job.creative_job_id) is None
    # Nothing was queued beyond the creative task itself: no production or GPU admission.
    assert {i.resource_tag for i in runtime.queue.list(limit=50)} == {
        f"creative:{job.creative_job_id}"
    }


def test_nothing_is_approved_or_authorized_and_the_plan_stays_text_to_video(
    runtime: Runtime,
) -> None:
    job, task = _job(runtime, PLAIN_GOAL)
    runtime.coordinator(
        OllamaDouble(_outputs(runtime, job.creative_job_id, fx.bible())).adapter
    ).handler(task)
    package = runtime.service.get_package(job.creative_job_id)
    assert package is not None
    text = json.dumps(package.manifest)
    # Only prose may mention them (the Core hand-off list); no key carries a reference or digest.
    assert '"trusted_local_assets"' not in text and '"image_sha256"' not in text
    assert '"human_approved": true' not in text.lower() and "ACCEPT" not in text
    plan = compile_production_plan(str(uuid4()), package.manifest, package.package_digest)
    assert {t.trusted_input_asset_ref for t in plan.tasks} == {None}
    assert {t.workflow_id for t in plan.tasks} == {"comfy.wan22.ti2v5b.t2v.v1"}
    assert {i.resource_tag for i in runtime.queue.list(limit=50)} == {
        f"creative:{job.creative_job_id}"
    }


def test_restart_or_tampering_after_the_package_exists_leaves_it_intact(
    runtime: Runtime,
) -> None:
    job, task = _job(runtime, PLAIN_GOAL)
    runtime.coordinator(
        OllamaDouble(_outputs(runtime, job.creative_job_id, fx.bible())).adapter
    ).handler(task)
    before = runtime.service.get_package(job.creative_job_id)
    assert before is not None
    runtime.database.execute(
        "UPDATE creative_stage_runs SET result_json='{}' WHERE creative_job_id=? "
        "AND stage_kind=?", (job.creative_job_id, CreativeStageKind.SHOT_PLAN.value),
    )
    silent = OllamaDouble([])
    summary = runtime.coordinator(silent.adapter).handler(task)
    after = runtime.service.get_package(job.creative_job_id)
    assert summary.summary["status"] == "creative_ready" and silent.requests == []
    assert after is not None and after.package_digest == before.package_digest


def test_legacy_non_three_shot_v2_and_v1_goals_are_unchanged(runtime: Runtime) -> None:
    job, task = _job(runtime, PLAIN_GOAL, key="four")
    parts = stage_outputs(runtime.source_ref_for(job.creative_job_id))
    double = OllamaDouble([parts["idea"], parts["brief"], parts["script"], parts["bible"]])
    assert runtime.coordinator(double.adapter).handler(task).summary["status"] == "creative_ready"
    stages = runtime.service.get_package(job.creative_job_id).manifest["stage_results"]
    assert "keyframe_kit.v1" not in stages and KEYFRAME_REVIEW_NOTICE_KEY not in stages

    v1_job, v1_task = _job(runtime, COUNT_GOAL, profile=V1, key="v1")
    ref = runtime.source_ref_for(v1_job.creative_job_id)
    shots = {
        "schema_version": "1.0", "creative_profile": V1, "warnings": [],
        "needs_deep_ai": False, "needs_human": False,
        "shots": [
            {"shot_id": f"shot-{i:03d}", "beat_id": f"beat-{i:03d}", "order": i,
             "duration_seconds": 4.0, "subject": "Mochi the white cat", "environment": "room",
             "action": action, "framing": "medium shot", "lighting_style": "warm light",
             "continuity_keys": ["white cat Mochi", "teal scarf"], "required_facts": [],
             "source_evidence_ids": [], "text_reference": None,
             "production_notes": "renderer-neutral", "render_intent": "GENERATIVE_VIDEO"}
            for i, action in ((1, "Mochi taps the tag with her paw"),
                              (2, "a hand clips the tag onto the scarf"),
                              (3, "Mochi trots past the lamp"))
        ],
    }
    v1 = OllamaDouble([stage_outputs(ref)["idea"],
                       {**fx.brief(), "required_source_finding_refs": [ref]}, fx.script(), shots])
    assert runtime.coordinator(v1.adapter).handler(v1_task).summary["status"] == "creative_ready"
    assert set(runtime.service.get_package(v1_job.creative_job_id).manifest["stage_results"]) == {
        "idea_ranking.v1", "creative_brief.v1", "script.v1", "shot_plan.v1"
    }


# ── The notice is subject-neutral (a dog/collar story, not the cat/scarf fixture) ──────


def _dog_story() -> dict:
    text = json.dumps(fx.bible())
    for old, new in (
        ("white short-haired cat", "cream golden retriever"),
        ("short-haired cat", "golden retriever"),
        ("one white cat", "one cream dog"), ("teal scarf", "teal collar"), ("scarf", "collar"),
        ("Mochi", "Biscuit"), ("pointed upright ears", "floppy ears"), ("white coat", "cream coat"),
    ):
        text = text.replace(old, new)
    story = json.loads(text)
    story["subject"].update(species="dog", subject_id="biscuit")
    return story


def test_the_notice_and_kit_are_subject_neutral_for_a_dog_collar_story(runtime: Runtime) -> None:
    job, task = _job(runtime, PLAIN_GOAL, key="dog")
    double = OllamaDouble(_outputs(runtime, job.creative_job_id, _dog_story()))
    assert runtime.coordinator(double.adapter).handler(task).summary["status"] == "creative_ready"
    stages = runtime.service.get_package(job.creative_job_id).manifest["stage_results"]
    notice = json.dumps(KEYFRAME_REVIEW_NOTICE)
    assert stages[KEYFRAME_REVIEW_NOTICE_KEY] == KEYFRAME_REVIEW_NOTICE
    kit = KeyframeKit.model_validate(stages["keyframe_kit.v1"])
    assert "golden retriever" in kit.keyframes[0].still_prompt
    forbidden = re.compile(r"\b(cat|cats|scarf|dog|collar|lamp|Mochi)\b", re.IGNORECASE)
    assert forbidden.search(notice) is None
    assert forbidden.search(json.dumps([k.review_checklist for k in kit.keyframes])) is None
    enforcement = json.dumps(stages["keyframe_kit.v1"]["core_enforcement_required"])
    assert forbidden.search(enforcement) is None


# ── A job that was in progress before the default existed ──────────────────────────────


def _old_behavior(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The selection rule as it was before #179: only the explicit phrase."""

    import picotoopet_core.creative.director as director
    import picotoopet_core.creative.execution as execution
    import picotoopet_core.creative.quality as quality

    def old(directives, bible_shot_count):  # type: ignore[no-untyped-def]
        return bool(directives is not None and directives.story_gate)

    for module in (director, execution, quality):
        monkeypatch.setattr(module, "story_gate_applies", old)


def _stage_row(rt: Runtime, job_id: str, kind: CreativeStageKind) -> dict:
    row = rt.database.fetchone(
        "SELECT status,input_digest,result_json,model_attempts FROM creative_stage_runs "
        "WHERE creative_job_id=? AND stage_kind=?", (job_id, kind.value),
    )
    return dict(row)


def test_a_three_shot_v2_job_in_progress_before_the_default_resumes_unchanged(
    runtime: Runtime, monkeypatch
) -> None:
    import picotoopet_core.creative.execution as execution

    legacy = fx.bible()  # passes the old gate, is NOT a connected single-scene story
    legacy["scenes"].append({**legacy["scenes"][0], "scene_id": "kitchen"})
    legacy["shots"][2]["scene_id"] = "kitchen"
    job, task = _job(runtime, COUNT_GOAL, key="old")

    with monkeypatch.context() as old_world:
        _old_behavior(old_world)
        old_world.setattr(
            execution, "derive_shot_plan",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("process died after the Bible")),
        )
        with pytest.raises(RuntimeError):
            runtime.coordinator(
                OllamaDouble(_outputs(runtime, job.creative_job_id, legacy)).adapter
            ).handler(task)
    before = _stage_row(runtime, job.creative_job_id, CreativeStageKind.VIDEO_BIBLE)
    assert before["status"] == "Completed"
    assert runtime.service.get_package(job.creative_job_id) is None
    assert evaluate_story_storyboard(VideoBibleDraft.model_validate(legacy))  # not a story

    # Now the new code: default gate on. Nothing about the finished stages may change.
    silent = OllamaDouble([])
    summary = runtime.coordinator(silent.adapter).handler(task)
    assert summary.summary["status"] == "creative_ready" and silent.requests == []
    after = _stage_row(runtime, job.creative_job_id, CreativeStageKind.VIDEO_BIBLE)
    assert after == before  # same immutable input digest, same stored result, same attempts
    package = runtime.service.get_package(job.creative_job_id)
    assert package is not None
    stages = package.manifest["stage_results"]
    assert stages["video_bible.v1"] == json.loads(before["result_json"])
    assert "keyframe_kit.v1" not in stages and KEYFRAME_REVIEW_NOTICE_KEY not in stages
    assert set(stages) == {"idea_ranking.v1", "creative_brief.v1", "script.v1",
                           "video_bible.v1", "shot_plan.v1"}
    assert runtime.repository.get_job(job.creative_job_id).status is (
        CreativeJobStatus.CREATIVE_READY
    )


def test_the_digest_invariant_holds_exactly_for_the_default_rules_key() -> None:
    base = {"director_constraints": {"required_shot_count": 3}, "stage": "video_bible.v1"}
    with_rules = {"director_constraints": {"required_shot_count": 3,
                                           "story_quality_rules": ["x"]},
                  "stage": "video_bible.v1"}
    explicit = {"director_constraints": {"required_shot_count": 3, "story_gate": ["x"]},
                "stage": "video_bible.v1"}
    view = CreativeIntelligenceCoordinator._digest_view
    assert view(with_rules) == base                      # default rules never reach the digest
    assert view(explicit) == explicit                    # explicit-phrase jobs keep theirs
    assert view(base) is base
