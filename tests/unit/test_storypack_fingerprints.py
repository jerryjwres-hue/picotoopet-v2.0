"""Shot fingerprints isolate unrelated changes while never granting production rights."""

from copy import deepcopy

from picotoopet_core.domain.storypack import StoryPackV1
from picotoopet_core.domain.storypack_fingerprints import build_shot_fingerprints


def _pack() -> dict:
    # 三镜头：后院 S01 → 家门 S02 → 家门 S03；跨场景关系显式声明。
    return {
        "schema": "picotoo.storypack.v1",
        "episode_id": "E02",
        "title": "Maotai's dinner",
        "output_profile": "p0_landscape",
        "character_ref": "maotai_master_v1",
        "scene_ref": "yard_v1",
        "additional_scene_refs": ["door_v1"],
        "style_ref": "cinema_v1",
        "story": {"goal": "Hear a call", "payoff": "Reach dinner"},
        "shots": [
            {
                "id": "S01", "action": "Play in the yard", "state_in": "Standing",
                "state_out": "Holding ball", "because": "Establish play",
            },
            {
                "id": "S02", "action": "Run to the door", "state_in": "Holding ball",
                "state_out": "At door", "because": "Follow the call",
                "scene_ref": "door_v1", "depends_on": ["S01"], "handoff": "scene_change",
            },
            {
                "id": "S03", "action": "Find dinner", "state_in": "At door",
                "state_out": "Happy", "because": "Story payoff",
                "scene_ref": "door_v1", "depends_on": ["S02"], "handoff": "continuous",
            },
        ],
    }


def _checks() -> list[dict]:
    # 摘要只是一份资产记录；测试不能把记录伪装成主人审批。
    return [
        {
            "ref": ref,
            "recorded_sha256": letter * 64,
            "managed_object_integrity": "CONTENT_VERIFIED_UNAPPROVED",
            "content_integrity_verified": True,
        }
        for ref, letter in [
            ("maotai_master_v1", "a"),
            ("yard_v1", "b"),
            ("door_v1", "c"),
            ("cinema_v1", "d"),
        ]
    ]


def _build(pack, checks=None):
    return build_shot_fingerprints(
        StoryPackV1.model_validate(pack), "e" * 64, _checks() if checks is None else checks
    )


def _keys(result):
    return {shot["shot_id"]: shot["input_sha256"] for shot in result["shots"]}


def test_fingerprints_are_deterministic_and_not_execution_authority():
    a = _build(_pack())
    b = _build(_pack())
    assert a == b
    assert a["schema"] == "picotoo.fingerprint-plan.v1"
    assert len(a["shots"]) == 3
    assert a["can_queue"] is False
    assert a["can_reuse_for_generation"] is False
    assert all(shot["reusable_without_authority"] is False for shot in a["shots"])


def test_shot_edit_invalidates_only_itself_and_transitive_dependents():
    original = _build(_pack())
    changed = _pack()
    changed["shots"][1]["action"] = "Run toward the porch"
    after = _build(changed)
    before_keys, after_keys = _keys(original), _keys(after)
    assert before_keys["S01"] == after_keys["S01"]
    assert before_keys["S02"] != after_keys["S02"]
    assert before_keys["S03"] != after_keys["S03"]


def test_asset_change_propagates_only_to_shots_that_use_or_depend_on_it():
    original = _build(_pack())
    checks = _checks()
    next_checks = deepcopy(checks)
    next_checks[2]["recorded_sha256"] = "f" * 64
    after = _build(_pack(), next_checks)
    assert _keys(original)["S01"] == _keys(after)["S01"]
    assert _keys(original)["S02"] != _keys(after)["S02"]
    assert _keys(original)["S03"] != _keys(after)["S03"]
    assert original["asset_snapshot_sha256"] != after["asset_snapshot_sha256"]


def test_story_change_requires_new_story_review_without_fake_regeneration():
    original = _build(_pack())
    changed = _pack()
    changed["story"]["payoff"] = "Surprise dinner"
    after = build_shot_fingerprints(
        StoryPackV1.model_validate(changed), "f" * 64, _checks()
    )
    assert _keys(original) == _keys(after)
    assert original["story_review_sha256"] != after["story_review_sha256"]


def test_unverified_assets_have_stable_but_never_reusable_keys():
    checks = _checks()
    checks[0]["content_integrity_verified"] = False
    checks[0]["managed_object_integrity"] = "CONTENT_HASH_MISMATCH"
    result = _build(_pack(), checks)
    assert result["shots"][0]["all_managed_bytes_verified"] is False
    assert result["can_reuse_for_generation"] is False
    assert result["can_queue"] is False


def test_case_insensitive_dependency_ids_do_not_crash():
    changed = _pack()
    changed["shots"][1]["depends_on"] = ["s01"]
    changed["shots"][2]["depends_on"] = ["s02"]
    assert len(_build(changed)["shots"]) == 3
