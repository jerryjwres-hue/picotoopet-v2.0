"""Issue #214: keyframe still prompts carry the shared visual locks; per-shot state stays per shot.

Pure source-level checks of ``build_keyframe_kit``. They prove prompt *mapping*, determinism and
bounds only. They say nothing about how a generated picture looks.
"""

from __future__ import annotations

import json
import re
from copy import deepcopy

import pytest
import story_fixture_2026 as fx

from picotoopet_core.creative.models import CreativeBriefResult, CreativeScriptResult
from picotoopet_core.creative.video_bible import (
    PROMPT_BUDGET_CHARS,
    STILL_PROMPT_TARGET_CHARS,
    KeyframeGateOutcome,
    KeyframeKit,
    KeyframeKitError,
    KeyframeSubmission,
    VideoBibleDraft,
    _kit_digest,
    build_keyframe_kit,
    evaluate_keyframe_submissions,
    seal_bible,
)

SCRIPT = CreativeScriptResult.model_validate(fx.script())
PROFILE = CreativeBriefResult.model_validate(fx.brief()).output_profile_id.value


def _kit(data: dict | None = None) -> KeyframeKit:
    bible = seal_bible(
        VideoBibleDraft.model_validate(data or fx.bible()),
        project_key="pet-tag-us", source_set_digest="d" * 64, selected_idea_id="idea-001",
    )
    return build_keyframe_kit(bible, SCRIPT, output_profile_id=PROFILE)


def _prompts(kit: KeyframeKit) -> list[str]:
    return [item.still_prompt for item in kit.keyframes]


def test_three_stills_share_every_lock_and_keep_their_own_state_and_framing() -> None:
    data = fx.bible()
    kit = _kit(data)
    scene = data["scenes"][0]
    prompts = _prompts(kit)
    for prompt, shot in zip(prompts, data["shots"], strict=True):
        assert fx.SUBJECT_PHRASE in prompt                     # protagonist and scarf
        assert scene["environment_phrase"] in prompt           # table/lamp/sofa layout
        assert scene["lighting_phrase"] in prompt
        assert ", ".join(scene["palette"]) in prompt
        assert "screen direction left to right" in prompt
        assert "rests on a visible surface, nothing floats" in prompt
        assert "exactly one cat" in prompt
        assert f"state: {shot['opening_state']}" in prompt     # per-shot, verbatim
        assert f"framing: {shot['camera_framing']}" in prompt
    assert len(set(prompts)) == 3
    assert [item.camera_framing for item in kit.keyframes] == [
        "medium shot", "close-up", "wide shot"]


def test_product_is_described_by_geometry_not_by_a_later_story_state() -> None:
    data = fx.bible()
    first, second, third = _prompts(_kit(data))
    for prompt in (first, second, third):
        assert "small round matte-charcoal tag" in prompt
        assert "no text or logo" in prompt
    # The product identity phrase says "clipped to the teal scarf"; shot 1 opens with the tag on
    # the floor, so that phrase must not leak into the still as a contradiction.
    assert "clipped to the teal scarf" not in first.replace(
        data["shots"][0]["opening_state"], "")
    assert "the charcoal tag lies on the floor" in first
    assert "clipped to the teal scarf under Mochi's chin" in second + third


def _dog_bible() -> dict:
    text = json.dumps(fx.bible())
    for old, new in ((r"white short-haired cat", "cream short-haired dog"),
                     (r"Mochi", "Biscuit"), (r"\bcat\b", "dog"), (r"scarf", "collar")):
        text = re.sub(old, new, text)
    return json.loads(text)


def test_dog_with_collar_gets_the_same_lock_pattern() -> None:
    kit = _kit(_dog_bible())
    for prompt in _prompts(kit):
        assert "cream short-haired dog" in prompt and "teal collar" in prompt
        assert "exactly one dog" in prompt
        assert not re.search(r"\bcat\b", prompt)


def test_off_frame_subject_or_product_is_declared_absent_and_never_described() -> None:
    data = fx.bible()
    data["shots"][1]["featured"] = ["PRODUCT"]
    product_only = _prompts(_kit(data))[1]
    assert "no cat visible in this frame" in product_only
    assert fx.SUBJECT_PHRASE not in product_only and "exactly one cat" not in product_only
    assert "small round matte-charcoal tag" in product_only

    data = fx.bible()
    data["shots"][0]["featured"] = ["SUBJECT"]
    subject_only = _prompts(_kit(data))[0]
    assert "pet tag not visible in this frame" in subject_only
    assert "matte-charcoal" not in subject_only and fx.SUBJECT_PHRASE in subject_only


def test_unrelated_extra_subject_in_a_bible_is_rejected_before_any_prompt_exists() -> None:
    data = fx.bible()
    data["shots"][0]["opening_state"] += ", and another cat watches from the sofa"
    with pytest.raises(KeyframeKitError):
        _kit(data)


def test_prompt_is_bounded_even_for_maximum_size_bible_fields() -> None:
    data = fx.bible()
    data["subject"]["identity_phrase"] = fx.SUBJECT_PHRASE + " " + "x" * (240 - len(fx.SUBJECT_PHRASE) - 1)
    data["scenes"][0]["environment_phrase"] = data["scenes"][0]["environment_phrase"][:20] + " e" * 140
    data["scenes"][0]["lighting_phrase"] = "l " * 98 + "end"
    prompts = _prompts(_kit(data))
    assert max(map(len, prompts)) <= PROMPT_BUDGET_CHARS
    assert all(len(p) <= STILL_PROMPT_TARGET_CHARS or "palette:" not in p for p in prompts)
    assert all("state:" in p and "framing:" in p for p in prompts)  # required clauses survive


def test_build_is_deterministic_and_digests_are_stable_and_content_bound() -> None:
    first, second = _kit(), _kit()
    assert first == second and first.kit_digest == second.kit_digest
    assert KeyframeKit.model_validate(first.model_dump(mode="json")) == first
    # Locks, Bible binding and kit id are byte-identical to the pre-change base (recorded there).
    assert first.locks.locks_digest == (
        "21ac70c111341140c3cdafe4488f7a4243c922b955d31068469a3259b7b7cc17")
    assert first.bible_digest == (
        "0814fe24ad51a5d2de2c2395caac1b248f4139b3ad768f46005d2f9f56c75498")
    assert first.kit_id == "kk-0936c2b5de06e12e"
    changed = fx.bible()
    changed["shots"][2]["camera_framing"] = "medium wide shot"
    assert _kit(changed).kit_digest != first.kit_digest


def test_previously_persisted_old_format_kit_still_validates_and_gates_unchanged() -> None:
    """Persisted kits are read, never rebuilt: an old-format prompt must keep validating."""

    raw = _kit().model_dump(mode="json")
    for item, shot in zip(raw["keyframes"], fx.bible()["shots"], strict=True):
        item["still_prompt"] = (
            f"still frame, {fx.SUBJECT_PHRASE}, {shot['opening_state']}, "
            f"tidy living room, warm lamp glow, {shot['camera_framing']}"
        )
    body = {k: v for k, v in raw.items() if k != "kit_digest"}
    raw["kit_digest"] = _kit_digest(body)
    old = KeyframeKit.model_validate(raw)
    assert old.kit_digest != _kit().kit_digest
    submissions = [
        KeyframeSubmission(
            keyframe_id=item.keyframe_id, locks_digest=old.locks.locks_digest, width=fx.WIDTH,
            height=fx.HEIGHT, human_approved=True, image_sha256=f"{i:064x}",
        )
        for i, item in enumerate(old.keyframes, start=1)
    ]
    decision = evaluate_keyframe_submissions(old, submissions)
    assert decision.outcome is KeyframeGateOutcome.AWAITING_CORE_PROVENANCE
    assert decision.send_allowed is False


def test_input_bible_data_is_not_mutated_by_building_a_kit() -> None:
    data = fx.bible()
    before = deepcopy(data)
    _kit(data)
    assert data == before
