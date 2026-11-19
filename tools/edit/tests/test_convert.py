import json

from edit.cli import main


def test_convert_then_assemble_relocated_plan(
    tmp_path, mock_video_clip_generator, mock_audio_generator
):
    clip = mock_video_clip_generator("shot.mp4", size=(96, 160), duration_sec=2)
    tone = mock_audio_generator("tone.wav")
    raw = {
        "root": "/retired/location",
        "size": [96, 160],
        "shots": [
            {
                "shot_id": "S10",
                "video": clip.name,
                "in": 0.25,
                "transition_out": "whip_up",
                "foley": {"file": tone.name, "db": -2},
                "caption": {"text": "First!"},
            },
            {"shot_id": "S02", "video": clip.name, "speed": 2, "audio_offset": -0.2},
        ],
        "music": [{"file": tone.name, "shot": 1, "offset": 0.1}],
        "sfx": [{"file": tone.name, "at": 0.1}],
    }
    source = tmp_path / "original.json"
    source.write_text(json.dumps(raw))
    original = source.read_bytes()
    out = tmp_path / "nested" / "edit_plan.json"
    assert main(["convert", "--plan", str(source), "--root", str(tmp_path), "--out", str(out)]) == 0
    assert source.read_bytes() == original
    result = json.loads(out.read_text())
    assert result["format"] == "edit.production.v1" and result["root"] == ".."
    assert [s["shot_id"] for s in result["shots"]] == ["S10", "S02"]
    first, last = result["shots"]
    assert first["foley"] == [{"file": "tone.wav", "gain_db": -2}]
    assert first["transition_out"] == {"type": "whip", "dir": "up", "dur": 0.18}
    assert first["caption"]["end"] == 1.75
    assert first["out"] == 2 and last["in"] == 0 and last["speed"] == 2
    assert abs(result["music"][0]["dur"] - 0.9) < 0.00001
    assert result["sfx"][0]["gain_db"] == 0
    assert main(["assemble", "--plan", str(out), "--out", str(tmp_path / "out.mp4")]) == 0
    assert (tmp_path / "edl.txt").read_text().splitlines() == [
        "S10\t0.00\t1.75\twhip_up",
        "S02\t1.57\t1.00\tcut",
    ]
    assert (
        main(["convert", "--plan", str(source), "--root", str(tmp_path), "--out", str(source)]) == 1
    )
    assert source.read_bytes() == original


def test_convert_rejects_escape_and_invalid_cue(tmp_path, mock_video_clip_generator):
    media = tmp_path / "assets"
    media.mkdir()
    clip = mock_video_clip_generator("clip.mp4", size=(96, 160))
    source = tmp_path / "source.json"
    out = tmp_path / "existing.json"
    out.write_text("previous")
    raw = {"shots": [{"video": "../clip.mp4"}]}
    source.write_text(json.dumps(raw))
    args = ["convert", "--plan", str(source), "--root", str(media), "--out", str(out)]
    assert main(args) == 1
    assert out.read_text() == "previous"
    clip.rename(media / clip.name)
    raw["shots"][0]["video"] = clip.name
    raw["music"] = [{"file": clip.name, "shot": -1}]
    source.write_text(json.dumps(raw))
    assert main(args) == 1
    assert out.read_text() == "previous"
