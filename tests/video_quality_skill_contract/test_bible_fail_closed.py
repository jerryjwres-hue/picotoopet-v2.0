"""Mutation tests: each rule must fire on exactly the defect it names.

Mutations start from a clean golden fixture, so a firing code is attributable to the change.
"""

from __future__ import annotations

import pytest
from conftest_helpers import load, mutated, rebuild, run_lint, stages
from pydantic import ValidationError
from video_bible_reference import (
    BibleClaim,
    CameraMovement,
    ReferenceAsset,
    Severity,
    VideoBible,
    compute_digest,
)

from picotoopet_core.creative.models import CreativeQualityOutcome, CreativeStageKind
from picotoopet_core.creative.profiles import creative_profile_definition
from picotoopet_core.creative.quality import CreativeQualityGate
from picotoopet_core.creative.source import NormalizedCreativeSourceSet
from picotoopet_core.production.compiler import compile_production_plan

G1 = "g1-pawtrack-park"
G2 = "g2-autobowl-kitchen"
JOB = "11111111-1111-4111-8111-111111111111"


def _shot(fixture: dict, shot_id: str) -> dict:
    return next(s for s in stages(fixture)["shot_plan.v1"]["shots"] if s["shot_id"] == shot_id)


def _bshot(raw: dict, shot_id: str) -> dict:
    return next(s for s in raw["shots"] if s["shot_id"] == shot_id)


def _assert(report, code: str, severity: Severity | None = None) -> None:
    assert code in report.codes, report.codes
    if severity is not None:
        assert any(f.code == code and f.severity is severity for f in report.findings)


# ── frozen identity ────────────────────────────────────────────────────────────────────


def test_digest_is_content_bound_and_order_independent() -> None:
    raw = load(G1)["video_bible"]
    reordered = dict(reversed(list(raw.items())))
    assert VideoBible.model_validate(raw).bible_digest == VideoBible.model_validate(
        reordered
    ).bible_digest


def test_any_content_change_invalidates_the_old_digest() -> None:
    raw = mutated(load(G1))["video_bible"]
    raw["subject"]["coat_or_appearance"] = "dark brown coat"
    with pytest.raises(ValidationError, match="bible_digest"):
        VideoBible.model_validate(raw)
    assert rebuild(raw).bible_digest != load(G1)["video_bible"]["bible_digest"]


@pytest.mark.parametrize("extra", ["seed", "workflow_id", "comfy_workflow", "negative_prompt"])
def test_bible_cannot_carry_executor_authority(extra: str) -> None:
    raw = mutated(load(G1))["video_bible"]
    raw[extra] = "anything"
    with pytest.raises(ValidationError):
        VideoBible.model_validate(raw)


def test_negative_concepts_are_a_closed_advisory_vocabulary() -> None:
    raw = mutated(load(G1))["video_bible"]
    raw["negative_concepts"] = ["ultra sharp 8k masterpiece"]
    with pytest.raises(ValidationError):
        VideoBible.model_validate(raw)


# ── reference assets: digest + rights only, never a path, never unverified ─────────────


@pytest.mark.parametrize(
    "bad",
    [
        {"reference_id": "r1", "sha256": "a" * 64, "rights_source": "USER_SUPPLIED",
         "verified": False},
        {"reference_id": "r1", "sha256": "assets/biscuit.png", "rights_source": "USER_SUPPLIED",
         "verified": True},
        {"reference_id": "r1", "sha256": "a" * 64, "rights_source": "SCRAPED", "verified": True},
        {"reference_id": "r1", "sha256": "a" * 64, "rights_source": "LICENSED", "verified": True,
         "path": "C:\\Users\\a\\dog.png"},
    ],
)
def test_reference_asset_rejects_unverified_paths_and_unknown_rights(bad: dict) -> None:
    with pytest.raises(ValidationError):
        ReferenceAsset.model_validate(bad)


def test_reference_shot_needs_both_a_bible_reference_and_a_core_trusted_asset() -> None:
    fixture = mutated(load("g4-ripplesip-reference-missing"))
    assert "REFERENCE_UNAVAILABLE" in run_lint(fixture).codes

    raw = fixture["video_bible"]
    raw["reference"] = {
        "reference_id": "ripplesip-product-photo", "sha256": "a" * 64,
        "rights_source": "USER_SUPPLIED", "verified": True,
    }
    raw["unverified_fields"] = []
    bible = rebuild(raw)
    # A verified-looking Bible alone is not authority: Core must also hold the trusted asset.
    assert "REFERENCE_UNAVAILABLE" in run_lint(fixture, bible=bible).codes
    cleared = run_lint(fixture, bible=bible, trusted_assets={"shot-002": "core-asset-ref"})
    assert "REFERENCE_UNAVAILABLE" not in cleared.codes


def test_core_still_refuses_to_downgrade_a_reference_shot_to_text_to_video() -> None:
    fixture = load("g4-ripplesip-reference-missing")
    plan = compile_production_plan(JOB, fixture["creative_package_manifest"], "e" * 64)
    second = next(t for t in plan.tasks if t.shot_id == "shot-002")
    assert second.execution_disposition.value == "NeedsHuman"
    assert second.trusted_input_asset_ref is None


# ── untrusted claims fail closed ───────────────────────────────────────────────────────


def test_claim_with_unknown_evidence_is_blocked() -> None:
    fixture = mutated(load(G1))
    raw = fixture["video_bible"]
    raw["product"]["claims"][0]["evidence_ids"] = ["ev:invented:9"]
    report = run_lint(fixture, bible=rebuild(raw))
    _assert(report, "CLAIM_UNKNOWN_EVIDENCE", Severity.BLOCKED)
    assert report.verdict == "BLOCKED"


def test_unverified_claim_may_never_be_spoken() -> None:
    fixture = mutated(load(G1))
    raw = fixture["video_bible"]
    raw["product"]["claims"][0]["verified"] = False
    raw["product"]["claims"][0]["evidence_ids"] = []
    report = run_lint(fixture, bible=rebuild(raw))
    _assert(report, "CLAIM_UNVERIFIED_IN_VOICEOVER", Severity.BLOCKED)


def test_verified_claim_without_evidence_cannot_be_constructed() -> None:
    with pytest.raises(ValidationError):
        BibleClaim(claim_id="c", text="lasts a week", evidence_ids=[], verified=True)


def test_voiceover_without_evidence_needs_review() -> None:
    fixture = mutated(load(G1))
    for beat in stages(fixture)["script.v1"]["beats"]:
        if beat["voiceover"]:
            beat["claim_source_evidence_ids"] = []
    _assert(run_lint(fixture), "VOICEOVER_UNCITED", Severity.REVIEW)


# ── forbidden payloads and fabricated paths ────────────────────────────────────────────


@pytest.mark.parametrize(
    ("value", "code"),
    [
        ("see https://example.invalid/dog", "BIBLE_FORBIDDEN_PAYLOAD"),
        ("a dog from C:\\Users\\a\\dog.png", "BIBLE_PATH_LIKE"),
        ("a dog like assets/biscuit.png", "BIBLE_PATH_LIKE"),
        ("a dog like biscuit.jpg", "BIBLE_PATH_LIKE"),
        ("use ComfyWorkflow node 12", "BIBLE_FORBIDDEN_PAYLOAD"),
    ],
)
def test_urls_paths_and_workflow_text_in_a_bible_are_blocked(value: str, code: str) -> None:
    fixture = mutated(load(G1))
    raw = fixture["video_bible"]
    raw["scenes"][0]["palette"] = [value]
    report = run_lint(fixture, bible=rebuild(raw))
    _assert(report, code, Severity.BLOCKED)
    assert report.verdict == "BLOCKED"


def test_path_like_text_in_the_shot_plan_is_blocked_too() -> None:
    fixture = mutated(load(G1))
    _shot(fixture, "shot-001")["environment"] += " matching refs/porch.png"
    _assert(run_lint(fixture), "BIBLE_PATH_LIKE", Severity.BLOCKED)


# ── binding and structure ──────────────────────────────────────────────────────────────


def test_source_set_binding_mismatch_is_blocked() -> None:
    fixture = mutated(load(G1))
    raw = fixture["video_bible"]
    raw["source_set_digest"] = "f" * 64
    report = run_lint(fixture, bible=rebuild(raw))
    _assert(report, "BIBLE_SOURCE_BINDING_MISMATCH", Severity.BLOCKED)


def test_dropping_a_shot_from_the_plan_is_a_shot_set_mismatch() -> None:
    fixture = mutated(load(G1))
    del stages(fixture)["shot_plan.v1"]["shots"][-1]
    _assert(run_lint(fixture), "SHOT_SET_MISMATCH", Severity.BLOCKED)


def test_arc_must_equal_the_approved_script_beats() -> None:
    fixture = mutated(load(G1))
    raw = fixture["video_bible"]
    raw["arc"] = raw["arc"][:-1]
    _assert(run_lint(fixture, bible=rebuild(raw)), "ARC_MISMATCH", Severity.BLOCKED)


# ── drift the Creative stage must repair (RETRY_CREATIVE) ──────────────────────────────


def test_subject_identity_drift_in_one_shot_is_retried() -> None:
    fixture = mutated(load(G1))
    _shot(fixture, "shot-003")["subject"] = "a brown dog"
    report = run_lint(fixture)
    _assert(report, "SHOT_FIELD_DRIFT", Severity.RETRY_CREATIVE)
    assert report.verdict == "RETRY_CREATIVE"
    assert [f.shot_id for f in report.findings if f.code == "SHOT_FIELD_DRIFT"] == ["shot-003"]


def test_missing_continuity_anchor_is_retried() -> None:
    fixture = mutated(load(G1))
    _shot(fixture, "shot-002")["continuity_keys"].pop()
    _assert(run_lint(fixture), "CONTINUITY_ANCHOR_MISSING", Severity.RETRY_CREATIVE)


def test_global_notes_must_reach_the_brief_because_core_only_compiles_that_field() -> None:
    fixture = mutated(load(G1))
    stages(fixture)["creative_brief.v1"]["continuity_notes"] = []
    _assert(run_lint(fixture), "BRIEF_CONTINUITY_NOTES_MISSING", Severity.RETRY_CREATIVE)


def test_broken_continuous_handoff_is_retried() -> None:
    fixture = mutated(load(G2))
    raw = fixture["video_bible"]
    _bshot(raw, "shot-002")["opening_state"] = "Mochi sits near the window"
    _assert(run_lint(fixture, bible=rebuild(raw)), "HANDOFF_BROKEN", Severity.RETRY_CREATIVE)


def test_camera_movement_outside_the_bible_rules_is_retried() -> None:
    fixture = mutated(load(G1))
    raw = fixture["video_bible"]
    raw["camera_rules"]["allowed_movements"] = [CameraMovement.STATIC.value]
    _assert(run_lint(fixture, bible=rebuild(raw)), "CAMERA_RULE_VIOLATION", Severity.RETRY_CREATIVE)


def test_text_in_frame_contradicts_the_no_text_logo_policy() -> None:
    fixture = mutated(load(G1))
    raw = fixture["video_bible"]
    _bshot(raw, "shot-002")["risk_flags"] = ["TEXT_IN_FRAME"]
    _assert(run_lint(fixture, bible=rebuild(raw)), "TEXT_IN_FRAME_CONTRADICTION")


# ── duration: unsupported is flagged, never silently truncated ─────────────────────────


def _lengthen(fixture: dict, shot_id: str, seconds: float) -> VideoBible:
    old = _shot(fixture, shot_id)["duration_seconds"]
    _shot(fixture, shot_id)["duration_seconds"] = seconds
    raw = fixture["video_bible"]
    _bshot(raw, shot_id)["duration_seconds"] = seconds
    script = stages(fixture)["script.v1"]
    beat_id = _shot(fixture, shot_id)["beat_id"]
    for beat in script["beats"]:
        if beat["beat_id"] == beat_id:
            beat["duration_seconds"] += seconds - old
    script["target_duration_seconds"] += seconds - old
    return rebuild(raw)


def test_seven_second_shot_is_flagged_end_to_end() -> None:
    fixture = mutated(load(G1))
    bible = _lengthen(fixture, "shot-003", 7.0)
    report = run_lint(fixture, bible=bible)
    _assert(report, "SHOT_DURATION_UNRENDERABLE", Severity.RETRY_CREATIVE)

    # The Creative gate agrees and asks for a split with the same beat and evidence.
    parts = stages(fixture)
    source = NormalizedCreativeSourceSet(
        project_key="goal-g1", result_package_ids=["r1"], result_digests=["c" * 64],
        findings=[], evidence_ids=sorted(fixture["source_evidence"]),
        source_set_digest=fixture["creative_package_manifest"]["source_set_digest"],
    )
    decision, _ = CreativeQualityGate().evaluate(
        stage_kind=CreativeStageKind.SHOT_PLAN,
        profile=creative_profile_definition("creative.content_plan.v1"),
        source_set=source,
        previous_stages={
            "script.v1": parts["script.v1"],
            "creative_brief.v1": parts["creative_brief.v1"],
        },
        raw_result=parts["shot_plan.v1"],
    )
    assert decision.outcome is CreativeQualityOutcome.RETRY
    assert decision.reasons == ["CREATIVE_SHOT_DURATION_UNRENDERABLE"]

    # And Core never truncates it: the planned duration is kept and a human is required.
    plan = compile_production_plan(JOB, fixture["creative_package_manifest"], "e" * 64)
    long = next(t for t in plan.tasks if t.shot_id == "shot-003")
    assert long.execution_disposition.value == "NeedsHuman" and long.target_duration_ms == 7000


def test_renderable_but_short_shot_is_only_a_review_note() -> None:
    fixture = mutated(load(G1))
    report = run_lint(fixture, bible=_lengthen(fixture, "shot-001", 2.5))
    _assert(report, "SHOT_DURATION_OFF_BAND", Severity.REVIEW)
    assert report.verdict == "REVIEW"


def test_multi_step_action_is_an_advisory_review() -> None:
    fixture = mutated(load(G1))
    raw = fixture["video_bible"]
    action = "Biscuit sits then jumps then runs"
    _bshot(raw, "shot-001")["visible_action"] = action
    plan_shot = _shot(fixture, "shot-001")
    plan_shot["action"] = plan_shot["action"].replace(
        "Biscuit tilts his head and wags his tail slowly", action
    )
    report = run_lint(fixture, bible=rebuild(raw))
    _assert(report, "ACTION_MULTI_STEP", Severity.REVIEW)
    assert report.verdict == "REVIEW"


def test_computed_digest_ignores_the_digest_field_itself() -> None:
    bible = VideoBible.model_validate(load(G1)["video_bible"])
    assert compute_digest(bible) == compute_digest(bible.model_copy(update={"bible_digest": None}))


@pytest.mark.xfail(
    strict=True,
    reason=(
        "G006 finding: CreativeQualityGate.contains_forbidden_output lowercases json.dumps() "
        "output, where a Windows path appears with doubled backslashes, so its 'c:\\users\\' "
        "marker can never match. Only the Bible lint's own path rule catches it today."
    ),
)
def test_core_gate_flags_a_windows_user_path() -> None:
    assert CreativeQualityGate.contains_forbidden_output({"x": "from C:\\Users\\a\\dog"})
