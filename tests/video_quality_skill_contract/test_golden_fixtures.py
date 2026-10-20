"""Golden synthetic pet-product fixtures against the REAL Core contracts.

Everything here is structural: typed mapping, frozen identity, renderable timing and
fail-closed claims. No test renders, decodes or looks at a picture, so none of them can say a
video is good. Every report keeps ``visual_qa == "UNVERIFIED"``.
"""

from __future__ import annotations

import re

import pytest
from conftest_helpers import FIXTURE_IDS, load, run_lint, stages
from video_bible_reference import (
    PREFERRED_SHOT_SECONDS,
    Featured,
    VideoBible,
    expand_shot_fields,
    expected_core_prompt,
)

from picotoopet_core.creative.models import (
    CreativeBriefResult,
    CreativeQualityOutcome,
    CreativeScriptResult,
    CreativeStageKind,
    ShotPlanResult,
)
from picotoopet_core.creative.profiles import creative_profile_definition
from picotoopet_core.creative.quality import CreativeQualityGate
from picotoopet_core.creative.source import NormalizedCreativeSourceSet
from picotoopet_core.production.compiler import compile_production_plan

HYPE = re.compile(r"8k|4k|masterpiece|cinematic|ultra|best quality|trending|hyper", re.I)
EXPECTED_BLOCKED = {"g4-ripplesip-reference-missing"}


def test_there_are_three_to_five_golden_fixtures() -> None:
    assert 3 <= len(FIXTURE_IDS) <= 5


@pytest.mark.parametrize("fixture_id", FIXTURE_IDS)
def test_fixture_is_labelled_synthetic_and_carries_no_media_or_urls(fixture_id: str) -> None:
    fixture = load(fixture_id)
    assert fixture["fixture_kind"] == "SYNTHETIC"
    assert "not a measurement" in fixture["note"]
    text = str(fixture).lower()
    assert "http://" not in text and "https://" not in text
    assert not re.search(r"\.(png|jpe?g|webp|mp4|mov|webm)\b", text)
    assert "trusted_local_assets" not in fixture["creative_package_manifest"]


@pytest.mark.parametrize("fixture_id", FIXTURE_IDS)
def test_stage_outputs_validate_against_the_real_core_models(fixture_id: str) -> None:
    parts = stages(load(fixture_id))
    CreativeBriefResult.model_validate(parts["creative_brief.v1"])
    CreativeScriptResult.model_validate(parts["script.v1"])
    ShotPlanResult.model_validate(parts["shot_plan.v1"])


@pytest.mark.parametrize("fixture_id", FIXTURE_IDS)
def test_creative_gate_passes_script_and_shot_plan(fixture_id: str) -> None:
    fixture = load(fixture_id)
    parts = stages(fixture)
    source = NormalizedCreativeSourceSet(
        project_key=fixture["creative_package_manifest"]["project_key"],
        result_package_ids=["r1"], result_digests=["c" * 64], findings=[],
        evidence_ids=sorted(fixture["source_evidence"]),
        source_set_digest=fixture["creative_package_manifest"]["source_set_digest"],
    )
    profile = creative_profile_definition("creative.content_plan.v1")
    gate = CreativeQualityGate()
    for kind, key, previous in (
        (CreativeStageKind.SCRIPT, "script.v1", {}),
        (
            CreativeStageKind.SHOT_PLAN,
            "shot_plan.v1",
            {"script.v1": parts["script.v1"], "creative_brief.v1": parts["creative_brief.v1"]},
        ),
    ):
        decision, _ = gate.evaluate(
            stage_kind=kind, profile=profile, source_set=source,
            previous_stages=previous, raw_result=parts[key],
        )
        assert decision.outcome is CreativeQualityOutcome.PASS, (kind, decision.reasons)


@pytest.mark.parametrize("fixture_id", FIXTURE_IDS)
def test_bible_is_a_sealed_frozen_sidecar_bound_to_the_source_set(fixture_id: str) -> None:
    fixture = load(fixture_id)
    bible = VideoBible.model_validate(fixture["video_bible"])
    assert bible.bible_digest is not None
    assert bible.source_set_digest == fixture["creative_package_manifest"]["source_set_digest"]
    with pytest.raises(Exception, match="frozen"):
        bible.bible_id = "other"  # type: ignore[misc]


@pytest.mark.parametrize("fixture_id", FIXTURE_IDS)
def test_expected_lint_verdict_is_pinned_and_never_a_visual_pass(fixture_id: str) -> None:
    fixture = load(fixture_id)
    report = run_lint(fixture)
    assert report.verdict == fixture["expected"]["verdict"]
    assert report.codes == fixture["expected"]["finding_codes"]
    assert list(report.human_review_focus) == fixture["expected"]["human_review_focus"]
    assert report.visual_qa == fixture["expected"]["visual_qa"] == "UNVERIFIED"
    assert (report.verdict == "BLOCKED") == (fixture_id in EXPECTED_BLOCKED)


@pytest.mark.parametrize("fixture_id", FIXTURE_IDS)
def test_shot_plan_text_is_exactly_the_deterministic_bible_expansion(fixture_id: str) -> None:
    fixture = load(fixture_id)
    bible = VideoBible.model_validate(fixture["video_bible"])
    for bshot, shot in zip(bible.shots, stages(fixture)["shot_plan.v1"]["shots"], strict=True):
        for name, value in expand_shot_fields(bible, bshot).items():
            assert shot[name] == value, f"{shot['shot_id']}.{name}"


@pytest.mark.parametrize("fixture_id", FIXTURE_IDS)
def test_core_compiler_output_matches_the_frozen_expectation(fixture_id: str) -> None:
    fixture = load(fixture_id)
    manifest = fixture["creative_package_manifest"]
    plan = compile_production_plan(fixture["expected"]["production_job_id"], manifest, "e" * 64)
    expected = fixture["expected"]["tasks"]
    assert [t.shot_id for t in plan.tasks] == [e["shot_id"] for e in expected]
    for task, want in zip(plan.tasks, expected, strict=True):
        assert task.execution_disposition.value == want["execution_disposition"]
        assert task.workflow_id == want["workflow_id"]
        assert task.frame_count == want["frame_count"]
        assert task.target_duration_ms == want["target_duration_ms"]
        assert task.positive_prompt == want["positive_prompt"]
        assert len(task.positive_prompt) <= 5000
        assert not HYPE.search(task.positive_prompt)


@pytest.mark.parametrize("fixture_id", FIXTURE_IDS)
def test_prompt_restatement_equals_the_real_compiler(fixture_id: str) -> None:
    fixture = load(fixture_id)
    parts = stages(fixture)
    notes = parts["creative_brief.v1"]["continuity_notes"]
    shots, tasks = parts["shot_plan.v1"]["shots"], fixture["expected"]["tasks"]
    for shot, want in zip(shots, tasks, strict=True):
        assert expected_core_prompt(shot, notes) == want["positive_prompt"]


@pytest.mark.parametrize("fixture_id", FIXTURE_IDS)
def test_executable_shots_are_renderable_and_inside_the_preferred_band(fixture_id: str) -> None:
    fixture = load(fixture_id)
    low, high = PREFERRED_SHOT_SECONDS
    for task in fixture["expected"]["tasks"]:
        if task["execution_disposition"] != "Executable":
            continue
        assert task["frame_count"] % 4 == 1 and task["frame_count"] <= 121
        assert low <= task["target_duration_ms"] / 1000 <= high


@pytest.mark.parametrize("fixture_id", FIXTURE_IDS)
def test_identity_phrases_reach_every_featured_shot_prompt(fixture_id: str) -> None:
    """Text-level continuity only: says nothing about whether the pixels stay consistent."""

    fixture = load(fixture_id)
    bible = VideoBible.model_validate(fixture["video_bible"])
    for bshot, want in zip(bible.shots, fixture["expected"]["tasks"], strict=True):
        prompt = want["positive_prompt"]
        if Featured.SUBJECT in bshot.featured:
            assert bible.subject.identity_phrase in prompt, bshot.shot_id
        if Featured.PRODUCT in bshot.featured:
            assert bible.product.identity_phrase in prompt, bshot.shot_id
        for anchor in bible.continuity_anchors:
            assert anchor in prompt, f"{bshot.shot_id} lost anchor {anchor!r}"
        for note in bible.global_continuity_notes:
            assert note in prompt, f"{bshot.shot_id} lost note {note!r}"


@pytest.mark.parametrize("fixture_id", FIXTURE_IDS)
def test_spoken_claims_cite_known_synthetic_evidence_only(fixture_id: str) -> None:
    fixture = load(fixture_id)
    known = set(fixture["source_evidence"])
    for beat in stages(fixture)["script.v1"]["beats"]:
        assert set(beat["claim_source_evidence_ids"]) <= known
        if beat["voiceover"]:
            assert beat["claim_source_evidence_ids"], beat["beat_id"]
    bible = VideoBible.model_validate(fixture["video_bible"])
    assert all(claim.verified for claim in bible.product.claims)


def test_g4_reference_shot_is_needs_human_and_nothing_is_downgraded_to_text() -> None:
    fixture = load("g4-ripplesip-reference-missing")
    blocked = [t for t in fixture["expected"]["tasks"] if t["shot_id"] == "shot-002"][0]
    assert blocked["execution_disposition"] == "NeedsHuman" and blocked["workflow_id"] is None
    assert fixture["video_bible"]["reference"] is None
    assert "reference" in fixture["video_bible"]["unverified_fields"]
