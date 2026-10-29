"""A v2 shot plan must stay a pure function of its sealed Story Bible, including after a restart.

Real gate, real Coordinator + SQLite + Ollama adapter transport; model JSON is scripted. These are
text-integrity checks: a PASS is not a visual ACCEPT and authorizes no render.
"""

from __future__ import annotations

import json
from copy import deepcopy
from uuid import uuid4

import pytest
import story_fixture_2026 as fx
from director_fixtures import V1, V2, OllamaDouble, Runtime, open_runtime, stage_outputs

from picotoopet_core.creative.models import (
    CreativeJobStatus,
    CreativeQualityOutcome,
    CreativeScriptResult,
    CreativeStageKind,
)
from picotoopet_core.creative.package import CreativePackageFinalizer
from picotoopet_core.creative.profiles import creative_profile_definition
from picotoopet_core.creative.quality import CreativeQualityGate
from picotoopet_core.creative.source import NormalizedCreativeSourceSet
from picotoopet_core.creative.video_bible import (
    VideoBible,
    VideoBibleDraft,
    derive_shot_plan,
    seal_bible,
    shot_plan_integrity_findings,
)
from picotoopet_core.production.compiler import compile_production_plan

SOURCE = NormalizedCreativeSourceSet(
    project_key="pet-tag-us", result_package_ids=[], result_digests=[], findings=[],
    evidence_ids=[fx.EVIDENCE], source_set_digest="d" * 64,
)
GOAL = (
    "Exactly 3 shots, text-to-video only: no reference image. Each shot 4.0 seconds, total "
    "12 seconds, landscape. A white cat gets a clip-on tag: hook, demo, payoff."
)
SCRIPT = CreativeScriptResult.model_validate(fx.script())


def _bible() -> VideoBible:
    return seal_bible(
        VideoBibleDraft.model_validate(fx.bible()),
        project_key="pet-tag-us", source_set_digest="d" * 64, selected_idea_id="idea-001",
    )


def _gate(plan: dict, *, profile: str = V2, with_bible: bool = True):  # type: ignore[no-untyped-def]
    previous = {"creative_brief.v1": fx.brief(), "script.v1": fx.script()}
    if with_bible:
        previous["video_bible.v1"] = _bible().model_dump(mode="json")
    return CreativeQualityGate().evaluate(
        stage_kind=CreativeStageKind.SHOT_PLAN, profile=creative_profile_definition(profile),
        source_set=SOURCE, previous_stages=previous, raw_result=plan, objective=GOAL,
    )[0]


def _plan() -> dict:
    return deepcopy(derive_shot_plan(_bible(), SCRIPT))


# ── Gate: same ids/orders/durations, different text ────────────────────────────────────


def test_the_derived_plan_of_a_correct_story_passes_unchanged() -> None:
    decision = _gate(_plan())
    assert decision.outcome is CreativeQualityOutcome.PASS
    assert shot_plan_integrity_findings(_bible(), SCRIPT, _plan()) == []


def _set(index: int, field: str, value):  # type: ignore[no-untyped-def]
    def mutate(plan: dict) -> None:
        plan["shots"][index][field] = value
    return mutate


def _replace(index: int, field: str, old: str, new: str):  # type: ignore[no-untyped-def]
    def mutate(plan: dict) -> None:
        text = plan["shots"][index][field]
        assert old in text
        plan["shots"][index][field] = text.replace(old, new)
    return mutate


def _replace_key(index: int, old: str, new: str):  # type: ignore[no-untyped-def]
    def mutate(plan: dict) -> None:
        keys = plan["shots"][index]["continuity_keys"]
        keys[keys.index(old)] = new
    return mutate


@pytest.mark.parametrize(
    ("mutate", "where"),
    [
        (_replace(0, "subject", "teal scarf", "green scarf"), "shot-001.subject"),
        (_replace(1, "subject", "charcoal", "white"), "shot-002.subject"),
        (_set(2, "environment", "a bright kitchen with a fridge"), "shot-003.environment"),
        (_replace(1, "action", "clips the tag onto", "hands the tag to"), "shot-002.action"),
        (_replace(1, "action", "opens on", "opens near"), "shot-002.action"),  # opening state
        (_replace(0, "action", "ends on Mochi's right paw", "ends on Mochi's left paw"),
         "shot-001.action"),  # closing state / handoff
        (_set(2, "framing", "extreme close-up, slow pan left"), "shot-003.framing"),
        (_set(1, "lighting_style", "cold blue night light"), "shot-002.lighting_style"),
        (_replace_key(0, "Mochi and the charcoal tag look identical in every shot",
                      "Mochi changes colour between shots"), "shot-001.continuity_keys"),
        (_set(2, "source_evidence_ids", [fx.EVIDENCE]),  # known id, but not this beat's claim
         "shot-003.source_evidence_ids"),
        (_set(1, "production_notes", "renderer-neutral; video_bible=0000000000000000"),
         "shot-002.production_notes"),
    ],
)
def test_mutated_plan_with_unchanged_ids_orders_and_durations_is_rejected(mutate, where) -> None:
    plan = _plan()
    ids = [(s["shot_id"], s["beat_id"], s["order"], s["duration_seconds"]) for s in plan["shots"]]
    mutate(plan)
    assert ids == [(s["shot_id"], s["beat_id"], s["order"], s["duration_seconds"])
                   for s in plan["shots"]]
    decision = _gate(plan)
    assert decision.outcome is CreativeQualityOutcome.RETRY
    assert decision.reasons == ["SHOT_PLAN_BIBLE_TEXT_MISMATCH"]
    assert where in (decision.correction_instruction or "")


def test_a_plan_with_a_different_shot_count_is_still_rejected() -> None:
    plan = _plan()
    plan["shots"].pop()
    assert _gate(plan).outcome is CreativeQualityOutcome.RETRY


def test_without_a_sealed_bible_the_legacy_gate_is_unchanged() -> None:
    plan = _plan()
    plan["shots"][0]["subject"] = "a completely different animal"
    assert _gate(plan, profile=V1, with_bible=False).outcome is CreativeQualityOutcome.PASS


# ── Real Coordinator: new job, restart reuse ───────────────────────────────────────────


@pytest.fixture
def runtime(tmp_path):  # type: ignore[no-untyped-def]
    rt = open_runtime(tmp_path)
    yield rt
    rt.database.close()


def _job(rt: Runtime):  # type: ignore[no-untyped-def]
    job = rt.service.create_job(
        source_result_package_ids=[rt.result_id], creative_profile=V2,
        creative_objective=GOAL, idempotency_key="integrity",
    )
    task = next(
        item for item in rt.queue.list(limit=50)
        if item.resource_tag == f"creative:{job.creative_job_id}"
    )
    ref = rt.source_ref_for(job.creative_job_id)
    outputs = [stage_outputs(ref)["idea"], {**fx.brief(), "required_source_finding_refs": [ref]},
               fx.script(), fx.bible()]
    return job, task, outputs


def _crash_before_package(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def boom(self, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("process died before the package was written")
    monkeypatch.setattr(CreativePackageFinalizer, "finalize", boom)


def _stored(rt: Runtime, job_id: str, kind: CreativeStageKind) -> dict:
    row = rt.database.fetchone(
        "SELECT result_json FROM creative_stage_runs WHERE creative_job_id=? AND stage_kind=?",
        (job_id, kind.value),
    )
    return json.loads(row["result_json"])


def _write(rt: Runtime, job_id: str, kind: CreativeStageKind, payload: dict) -> None:
    rt.database.execute(
        "UPDATE creative_stage_runs SET result_json=? WHERE creative_job_id=? AND stage_kind=?",
        (json.dumps(payload, ensure_ascii=False, sort_keys=True), job_id, kind.value),
    )


def test_a_correct_new_job_finishes_and_the_compiled_prompt_carries_every_lock(
    runtime: Runtime,
) -> None:
    job, task, outputs = _job(runtime)
    double = OllamaDouble(outputs)
    summary = runtime.coordinator(double.adapter).handler(task)
    assert summary.summary["status"] == "creative_ready"
    package = runtime.service.get_package(job.creative_job_id)
    assert package is not None
    plan = compile_production_plan(str(uuid4()), package.manifest, package.package_digest)
    bible = fx.bible()
    scene = bible["scenes"][0]
    for task_plan, shot in zip(plan.tasks, bible["shots"], strict=True):
        prompt = task_plan.positive_prompt
        for lock in (fx.SUBJECT_PHRASE, fx.PRODUCT_PHRASE, scene["environment_phrase"],
                     scene["lighting_phrase"], shot["opening_state"], shot["visible_action"],
                     shot["closing_state"], *bible["continuity_anchors"]):
            assert lock in prompt


def test_untampered_completed_stages_are_reused_after_a_restart_without_model_calls(
    runtime: Runtime, monkeypatch
) -> None:
    job, task, outputs = _job(runtime)
    with monkeypatch.context() as patch:
        _crash_before_package(patch)
        with pytest.raises(RuntimeError):
            runtime.coordinator(OllamaDouble(outputs).adapter).handler(task)
    assert runtime.service.get_package(job.creative_job_id) is None
    silent = OllamaDouble([])  # any model call raises
    summary = runtime.coordinator(silent.adapter).handler(task)
    assert summary.summary["status"] == "creative_ready" and silent.requests == []


@pytest.mark.parametrize(
    ("field", "old", "new"),
    [("subject", "teal scarf", "green scarf"), ("environment", "living room", "kitchen"),
     ("framing", "medium shot", "wide shot, slow pan left")],
)
def test_tampered_completed_shot_plan_fails_closed_on_restart_and_mints_no_package(
    runtime: Runtime, monkeypatch, field: str, old: str, new: str
) -> None:
    job, task, outputs = _job(runtime)
    with monkeypatch.context() as patch:
        _crash_before_package(patch)
        with pytest.raises(RuntimeError):
            runtime.coordinator(OllamaDouble(outputs).adapter).handler(task)
    stored = _stored(runtime, job.creative_job_id, CreativeStageKind.SHOT_PLAN)
    assert old in stored["shots"][0][field]
    stored["shots"][0][field] = stored["shots"][0][field].replace(old, new)
    _write(runtime, job.creative_job_id, CreativeStageKind.SHOT_PLAN, stored)

    silent = OllamaDouble([])
    for _ in range(2):  # a second run fails identically; nothing re-derives over the evidence
        summary = runtime.coordinator(silent.adapter).handler(task)
        assert summary.summary["status"] == "NeedsHuman"
    record = runtime.repository.get_job(job.creative_job_id)
    assert record.status is CreativeJobStatus.NEEDS_HUMAN
    assert record.failure_code == "CREATIVE_COMPLETED_SHOT_PLAN_BIBLE_MISMATCH"
    assert runtime.service.get_package(job.creative_job_id) is None and silent.requests == []
    assert _stored(runtime, job.creative_job_id, CreativeStageKind.SHOT_PLAN) == stored


def test_tampered_or_foreign_completed_bible_is_refused_on_restart_without_a_package(
    runtime: Runtime, monkeypatch
) -> None:
    job, task, outputs = _job(runtime)
    with monkeypatch.context() as patch:
        _crash_before_package(patch)
        with pytest.raises(RuntimeError):
            runtime.coordinator(OllamaDouble(outputs).adapter).handler(task)
    sealed = _stored(runtime, job.creative_job_id, CreativeStageKind.VIDEO_BIBLE)
    edited = deepcopy(sealed)
    edited["subject"]["identity_phrase"] = edited["subject"]["identity_phrase"].replace(
        "teal", "green"
    )  # content edited, seal digest not recomputed
    foreign = seal_bible(
        VideoBibleDraft.model_validate(fx.bible()),
        project_key="pet-tag-us", source_set_digest="e" * 64, selected_idea_id="idea-001",
    ).model_dump(mode="json")
    for replacement in (edited, foreign):
        _write(runtime, job.creative_job_id, CreativeStageKind.VIDEO_BIBLE, replacement)
        # The shot-plan stage input digest covers the Bible: the existing guard refuses it.
        with pytest.raises(ValueError, match="immutable input conflict"):
            runtime.coordinator(OllamaDouble([]).adapter).handler(task)
        assert runtime.service.get_package(job.creative_job_id) is None


def test_v1_job_replay_is_unchanged(runtime: Runtime) -> None:
    job = runtime.service.create_job(
        source_result_package_ids=[runtime.result_id], creative_profile=V1,
        creative_objective="Create a short product education video.", idempotency_key="v1",
    )
    task = next(i for i in runtime.queue.list(limit=50)
                if i.resource_tag == f"creative:{job.creative_job_id}")
    ref = runtime.source_ref_for(job.creative_job_id)
    parts = stage_outputs(ref)
    plan = {**derive_shot_plan(_bible(), SCRIPT), "creative_profile": V1}
    plan["shots"][0]["subject"] = "free-form text that no Bible ever sealed"
    double = OllamaDouble([parts["idea"], {**fx.brief(), "required_source_finding_refs": [ref]},
                           fx.script(), plan])
    summary = runtime.coordinator(double.adapter).handler(task)
    assert summary.summary["status"] == "creative_ready"
    assert set(runtime.service.get_package(job.creative_job_id).manifest["stage_results"]) == {
        "idea_ranking.v1", "creative_brief.v1", "script.v1", "shot_plan.v1"
    }
