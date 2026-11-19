import copy

import pytest
import yaml

from picotoopet_core.cli import main


@pytest.fixture
def direction_inputs(tmp_path):
    def shot(shot_id):
        return {
            "shot_id": shot_id,
            "seconds": 2.5,
            "beat": "看球",
            "emotion": "好奇",
            "camera": {"move": "已有调度", "lens": 40, "speed": 1},
            "first_frame": {"refs": ["stills/a.png"], "prompt": "old frame"},
            "last_frame": {"refs": ["stills/b.png"], "prompt": "old tail"},
            "video": {"prompt": "Old default dog prompt.", "negative": "flicker", "seeds": [7]},
            "audio": {"vocal_from": "ltx", "foley": ["ball"]},
            "transition_out": {"type": "cut", "offset_s": 0},
        }

    episode = {
        "episode_id": "fixture",
        "title": "玩具测试",
        "characters": [],
        "target_seconds": 7.5,
        "shots": [shot(s) for s in ("S01", "S02", "S03")],
        "edit": {"fps": 24, "size": [544, 960], "loudness_lufs": -14},
    }
    direction = {
        "identities": {"pup": "A dark Malamute with white paws and a pink-striped nose"},
        "shots": {
            "S01": {
                "subjects": ["pup"],
                "scene": "A small red ball on a wooden floor",
                "intent": "Reveal the paw before the eyes",
                "action": {
                    "trigger": "The ball reaches the paw",
                    "behavior": "He taps it once",
                    "landing": "His paw stays on the floor",
                },
                "camera": {
                    "opening": "A low close-up of paw and ball",
                    "trigger": "On contact",
                    "move": "缓慢推近",
                    "landing": "Eyes centered with paw still in view",
                },
            },
            "S02": {
                "subjects": [],
                "scene": "A steel bowl on an empty table",
                "action": {
                    "trigger": "A shaft of light reaches the rim",
                    "behavior": "Steam rises",
                    "landing": "The bowl fills the frame",
                },
                "camera": {
                    "opening": "A medium view of the bowl",
                    "trigger": "As steam rises",
                    "move": "zoom in",
                    "landing": "A tight shot of the rim",
                },
            },
        },
    }
    source, directions, output = (
        tmp_path / name for name in ("in.yaml", "directions.yaml", "out.yaml")
    )
    source.write_text(yaml.safe_dump(episode, allow_unicode=True), encoding="utf-8")
    directions.write_text(yaml.safe_dump(direction, allow_unicode=True), encoding="utf-8")
    return source, directions, output, direction


def _direct(source, directions, *options):
    return main(["episode", "direct", str(source), "--directions", str(directions), *options])


def test_direct_updates_only_requested_video_prompts_and_is_idempotent(direction_inputs, capsys):
    source, directions, output, _ = direction_inputs
    original = source.read_bytes()
    assert _direct(source, directions, "--output", str(output)) == 0
    rendered = output.read_bytes()
    assert source.read_bytes() == original
    original_episode, result = map(yaml.safe_load, (original, rendered))
    edited_dog, empty, untouched = result["shots"]
    dog_prompt = edited_dog["video"]["prompt"]
    assert "Malamute" in dog_prompt and "slow dolly in" in dog_prompt
    assert dog_prompt.index("reaches the paw") < dog_prompt.index("taps it once")
    empty_prompt = empty["video"]["prompt"]
    assert (
        "zoom in" in empty_prompt and "Malamute" not in empty_prompt and "dog" not in empty_prompt
    )
    for fact in ("negative", "seeds"):
        assert edited_dog["video"][fact] == original_episode["shots"][0]["video"][fact]
    assert edited_dog["camera"] == original_episode["shots"][0]["camera"]
    assert edited_dog["first_frame"] == original_episode["shots"][0]["first_frame"]
    assert edited_dog["last_frame"] == original_episode["shots"][0]["last_frame"]
    assert untouched["video"]["prompt"] == original_episode["shots"][2]["video"]["prompt"]
    assert _direct(source, directions, "--output", str(output)) == 0
    assert output.read_bytes() == rendered
    second = output.with_name("next.yaml")
    assert _direct(output, directions, "--output", str(second)) == 0
    assert second.read_bytes() == rendered
    assert main(["episode", "validate", str(second)]) == 0
    capsys.readouterr()
    assert _direct(source, directions, "--preview") == 0
    assert yaml.safe_load(capsys.readouterr().out) == result


@pytest.mark.parametrize(
    "error", ["unknown-shot", "unknown-subject", "default-actors", "chinese-action"]
)
def test_bad_direction_is_rejected_before_output(direction_inputs, capsys, error):
    source, directions, output, config = direction_inputs
    config = copy.deepcopy(config)
    if error == "unknown-shot":
        config["shots"]["Z99"] = config["shots"].pop("S01")
    elif error == "unknown-subject":
        config["shots"]["S01"]["subjects"] = ["missing"]
    elif error == "default-actors":
        config["default_subjects"] = ["pup"]
    else:
        config["shots"]["S01"]["action"]["behavior"] = "用爪碰球"
    directions.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")
    assert _direct(source, directions, "--output", str(output)) == 2
    assert not output.exists()
    assert "导演编译失败" in capsys.readouterr().err


def test_different_output_and_source_are_never_overwritten(direction_inputs):
    source, directions, output, _ = direction_inputs
    original = source.read_bytes()
    output.write_bytes(b"keep existing file")
    assert _direct(source, directions, "--output", str(source)) == 2
    assert _direct(source, directions, "--output", str(output)) == 2
    assert source.read_bytes() == original
    assert output.read_bytes() == b"keep existing file"


def test_duplicate_yaml_shot_cannot_override_previous_directions(direction_inputs, capsys):
    source, directions, output, _ = direction_inputs
    with directions.open("a", encoding="utf-8") as stream:
        stream.write("\n  S01: {}\n")
    assert _direct(source, directions, "--output", str(output)) == 2
    assert not output.exists()
    assert "重复字段" in capsys.readouterr().err
