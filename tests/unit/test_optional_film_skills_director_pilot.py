"""Offline contract test: film-skill director notes reuse the existing compiler."""

from __future__ import annotations

import copy
from pathlib import Path

import yaml

from picotoopet_core.domain.directing import direct_episode, load_directions
from picotoopet_core.domain.episode import Episode, load_episode
from picotoopet_core.domain.storypack import StoryPackV1

_ROOT = Path(__file__).resolve().parents[2]
_STORYPACK = _ROOT / "examples" / "storypack-maotai-v1.json"
_DIRECTIONS = _ROOT / "examples" / "maotai_optional_film_skills_directions.yaml"


def _synthetic_episode(pack: StoryPackV1) -> Episode:
    """Supply test-only, fully shaped Episode values; never create a real job."""
    shots = []
    for index, shot in enumerate(pack.shots):
        shots.append(
            {
                "shot_id": shot.id,
                "seconds": 4.0,
                "beat": shot.action,
                "emotion": "curious",
                "camera": {"move": "locked-off camera", "lens": 35.0, "speed": 1.0},
                "first_frame": {
                    "refs": [f"synthetic/reference-{index}.png"],
                    "prompt": "Synthetic unit-test still, not an approved production MASTER.",
                },
                "last_frame": None,
                "video": {
                    "prompt": "Existing baseline prompt.",
                    "negative": "unwanted background drift",
                    "seeds": [index + 10],
                },
                "audio": {"vocal_from": "none", "foley": []},
                "transition_out": {"type": "cut", "offset_s": 0.0},
                "caption": None,
            }
        )
    return Episode.model_validate(
        {
            "episode_id": pack.episode_id,
            "title": pack.title,
            "target_seconds": float(len(shots) * 4),
            "characters": [],
            "shots": shots,
            "edit": {"fps": 24.0, "size": [832, 480], "loudness_lufs": -14.0},
        }
    )


def test_optional_skill_notes_reuse_existing_three_shot_director_contract():
    # 样例的镜号/主体必须与 StoryPack 声明完全一致。
    pack = StoryPackV1.model_validate_json(_STORYPACK.read_bytes())
    directions = load_directions(_DIRECTIONS.read_bytes())
    assert len(pack.shots) == len(directions.shots) == 3
    assert list(directions.shots) == [shot.id for shot in pack.shots]
    declared = {pack.character_ref, *pack.supporting_character_refs}
    assert set(directions.identities) == declared
    for shot in pack.shots:
        cast = [pack.character_ref] if shot.cast_refs is None else shot.cast_refs
        assert directions.shots[shot.id].subjects == cast

    episode = _synthetic_episode(pack)
    before = episode.model_dump(mode="json")
    compiled = direct_episode(episode, directions)
    again = direct_episode(episode, directions)
    assert compiled == again

    # 唯一允许改变的字段是显式列出的 video.prompt。
    output = load_episode(compiled.encode("utf-8"), as_yaml=True)
    after = output.model_dump(mode="json")
    for initial, result in zip(before["shots"], after["shots"], strict=True):
        shot_id = initial["shot_id"]
        assert result["video"]["prompt"] != initial["video"]["prompt"]
        assert "Action cue:" in result["video"]["prompt"]
        assert "Camera cue:" in result["video"]["prompt"]
        assert "Final frame:" in result["video"]["prompt"]
        restored = copy.deepcopy(result)
        restored["video"]["prompt"] = initial["video"]["prompt"]
        assert restored == initial, shot_id
    before["shots"] = after["shots"]
    assert after["edit"] == before["edit"]
    assert after["target_seconds"] == 12.0
    assert all("@" not in shot["video"]["prompt"] for shot in after["shots"])
    assert all("higgsfield" not in shot["video"]["prompt"].lower() for shot in after["shots"])


def test_optional_skill_example_cannot_silently_introduce_new_cast():
    # 此处复核既有 StoryPack 声明，不把 directions 的文本描述当作已批准素材。
    pack = StoryPackV1.model_validate_json(_STORYPACK.read_bytes())
    directions = load_directions(_DIRECTIONS.read_bytes())
    allowed = {pack.character_ref, *pack.supporting_character_refs}
    unknown = {"not_declared_character"} - allowed
    assert unknown
    assert all(
        set(shot.subjects).issubset(allowed)
        for shot in directions.shots.values()
    )
    assert "not_declared_character" not in directions.identities
