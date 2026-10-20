"""Model adapters are non-interchangeable; only Wan2.2 T2V is executable by Core today."""

from __future__ import annotations

import pytest
from conftest_helpers import FIXTURE_IDS, load, stages
from video_bible_reference import (
    ADAPTERS,
    AdapterStatus,
    NegativeConcept,
    VideoBible,
    normalize_instruction,
    prompt_review,
)

from picotoopet_core.production.profile import (
    ALLOWED_WORKFLOW_IDS,
    I2V_WORKFLOW_ID,
    T2V_WORKFLOW_ID,
)


def test_this_work_does_not_widen_the_allowed_workflow_set() -> None:
    assert {T2V_WORKFLOW_ID, I2V_WORKFLOW_ID} == ALLOWED_WORKFLOW_IDS


def test_adapter_registry_is_closed_and_evaluation_models_have_no_workflow() -> None:
    assert set(ADAPTERS) == {
        "wan22_ti2v5b_t2v", "wan22_ti2v5b_i2v", "wan21_vace", "hunyuanvideo_15", "ltx_video",
    }
    for adapter in ADAPTERS.values():
        if adapter.status is AdapterStatus.EVALUATION_ONLY:
            assert adapter.workflow_id is None and adapter.executable_by_core is False
        else:
            assert adapter.workflow_id in ALLOWED_WORKFLOW_IDS
    assert [a.adapter_id for a in ADAPTERS.values() if a.executable_by_core] == [
        "wan22_ti2v5b_t2v"
    ]
    assert ADAPTERS["wan22_ti2v5b_i2v"].status is AdapterStatus.FUTURE_GATED


@pytest.mark.parametrize("adapter_id", ["wan21_vace", "hunyuanvideo_15", "ltx_video"])
def test_evaluation_only_models_never_produce_an_executable_review(adapter_id: str) -> None:
    fixture = load(FIXTURE_IDS[0])
    bible = VideoBible.model_validate(fixture["video_bible"])
    shot = stages(fixture)["shot_plan.v1"]["shots"][0]
    with pytest.raises(ValueError, match="ADAPTER_EVALUATION_ONLY"):
        prompt_review(bible, shot, [], adapter_id)


@pytest.mark.parametrize("fixture_id", FIXTURE_IDS)
def test_t2v_review_equals_the_core_prompt_and_needs_no_new_approval(fixture_id: str) -> None:
    fixture = load(fixture_id)
    bible = VideoBible.model_validate(fixture["video_bible"])
    parts = stages(fixture)
    notes = parts["creative_brief.v1"]["continuity_notes"]
    shots, tasks = parts["shot_plan.v1"]["shots"], fixture["expected"]["tasks"]
    for shot, want in zip(shots, tasks, strict=True):
        review = prompt_review(bible, shot, notes, "wan22_ti2v5b_t2v")
        assert review.positive_prompt == want["positive_prompt"]
        assert review.target_workflow_id == T2V_WORKFLOW_ID
        assert review.requires_approval is False
        assert review.reference_asset_sha256 is None
        assert review.visual_qa == "UNVERIFIED"
        assert set(review.suggested_negative_concepts) <= set(NegativeConcept)


def test_i2v_review_needs_a_verified_reference_and_always_approval() -> None:
    fixture = load("g4-ripplesip-reference-missing")
    shot = stages(fixture)["shot_plan.v1"]["shots"][1]
    bible = VideoBible.model_validate(fixture["video_bible"])
    with pytest.raises(ValueError, match="REFERENCE_UNAVAILABLE"):
        prompt_review(bible, shot, [], "wan22_ti2v5b_i2v")

    raw = fixture["video_bible"] | {"bible_digest": None, "reference": {
        "reference_id": "ripplesip-product-photo", "sha256": "a" * 64,
        "rights_source": "USER_SUPPLIED", "verified": True}}
    review = prompt_review(VideoBible.model_validate(raw), shot, [], "wan22_ti2v5b_i2v")
    assert review.requires_approval is True
    assert review.reference_asset_sha256 == "a" * 64
    assert review.target_workflow_id == I2V_WORKFLOW_ID


def test_normalization_is_deterministic_and_idempotent() -> None:
    messy = "  Biscuit\u3000runs\r\nacross\tthe  grass\u200b  "
    once = normalize_instruction(messy)
    assert once == "Biscuit runs across the grass"
    assert normalize_instruction(once) == once
    assert normalize_instruction("ＡＢＣ　１２３") == "ABC 123"
    with pytest.raises(ValueError, match="EMPTY_INSTRUCTION"):
        normalize_instruction(" \u200b\n")


def test_equivalent_whitespace_variants_yield_identical_reviews() -> None:
    fixture = load(FIXTURE_IDS[0])
    bible = VideoBible.model_validate(fixture["video_bible"])
    shot = dict(stages(fixture)["shot_plan.v1"]["shots"][0])
    variant = dict(shot, action=shot["action"].replace(" ", "  "))
    a = prompt_review(bible, shot, [], "wan22_ti2v5b_t2v")
    b = prompt_review(bible, variant, [], "wan22_ti2v5b_t2v")
    assert a.positive_prompt == b.positive_prompt
