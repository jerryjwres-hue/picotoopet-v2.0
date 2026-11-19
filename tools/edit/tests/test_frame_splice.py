"""Decoded-frame checks for short-cut chains and incomplete FFmpeg outputs."""

import subprocess

import numpy as np
import pytest
from edit.production import assemble_cut, local_media


def solid_clip(directory, index):
    name = f"{index}.mp4"
    shade = index * 22
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=c=0x{shade:02x}{shade:02x}{shade:02x}:s=64x96:r=24:d=4",
            "-c:v",
            "libx264",
            str(directory / name),
        ],
        check=True,
    )
    return name


def frame_levels(path):
    data = subprocess.check_output(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-an",
            "-vf",
            "scale=1:1,format=gray",
            "-f",
            "rawvideo",
            "-",
        ]
    )
    return np.frombuffer(data, np.uint8).astype(int)


def test_ten_subframe_cuts_keep_every_shot(tmp_path):
    spans = [
        (0, 3.70),
        (0, 2.93),
        (0, 2.65),
        (0, 2.92),
        (0, 2.35),
        (0, 3.19),
        (0.08, 1.54),
        (0, 3.83),
        (0, 2.44),
        (0, 3.87),
    ]
    shots = [
        {"video": solid_clip(tmp_path, i), "in": start, "out": end, "transition_out": "cut"}
        for i, (start, end) in enumerate(spans)
    ]
    out = tmp_path / "cut.mp4"
    assemble_cut({"size": [64, 96], "fps": 24, "shots": shots}, out, resolve=lambda p: tmp_path / p)
    levels = frame_levels(out)
    assert len(levels) == 696
    changes = np.where(np.diff(levels) > 12)[0] + 1
    # Planned starts at 3.66, 6.55, 9.16, 12.04, 14.35, 17.50, 18.92, 22.71 and 25.11s.
    assert changes.tolist() == [88, 157, 220, 289, 344, 420, 454, 545, 603]
    assert abs(levels[-1] - 198) < 3


def test_truncated_transition_recovers_and_truncated_mux_preserves_output(tmp_path):
    shots = [
        {"video": solid_clip(tmp_path, i), "out": 0.9, "transition_out": "dip"} for i in [1, 7]
    ]
    out = tmp_path / "cut.mp4"
    plan = {"size": [64, 96], "fps": 24, "shots": shots}
    rebuilt = []

    def truncate_splice(command, cwd):
        if command[-1] == "video.mp4" and command[0] == "ffmpeg":
            command = [*command[:-1], "-t", "0.25", command[-1]]
        if command[-1] == "aligned.mp4":
            rebuilt.append(True)
        return local_media(command, cwd)

    assemble_cut(plan, out, resolve=lambda p: tmp_path / p, media=truncate_splice)
    levels = frame_levels(out)
    assert rebuilt and len(levels) == 36 and levels[-1] > 140
    mux_modes, uncut_frames = [], []

    def early_shortest(command, cwd):
        if command[-1] == "output.mp4" and command[0] == "ffmpeg":
            mux_modes.append("-shortest" in command)
            if mux_modes[-1]:
                command = [*command[:-1], "-t", "0.25", command[-1]]
        result = local_media(command, cwd)
        if command[0] == "ffmpeg" and command[-1] == "video.mp4":
            uncut_frames.append(len(frame_levels(cwd / "video.mp4")))
        return result

    assemble_cut(plan, out, resolve=lambda p: tmp_path / p, media=early_shortest)
    assert mux_modes == [True, False] and uncut_frames == [len(frame_levels(out))]
    previous = out.read_bytes()

    def truncate_mux(command, cwd):
        if command[-1] == "output.mp4" and command[0] == "ffmpeg":
            command = [*command[:-1], "-t", "0.25", command[-1]]
        return local_media(command, cwd)

    with pytest.raises(ValueError, match="Output video does not match"):
        assemble_cut(plan, out, resolve=lambda p: tmp_path / p, media=truncate_mux)
    assert out.read_bytes() == previous
