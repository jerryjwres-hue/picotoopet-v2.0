import subprocess

import numpy as np
import pytest
from edit.production import assemble_cut, local_media
from edit.raster_caption import caption_font


def test_missing_drawtext_uses_timed_raster_overlay(tmp_path):
    clip = tmp_path / "black.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=black:s=192x160:r=24:d=1",
            "-c:v",
            "libx264",
            str(clip),
        ],
        check=True,
    )
    render_commands = []

    def without_drawtext(cmd, cwd):
        if "-filters" in cmd:
            return subprocess.CompletedProcess(cmd, 0, b" ... overlay VV->V\n", b"")
        render_commands.append(cmd)
        return local_media(cmd, cwd)

    out = tmp_path / "overlay.mp4"
    plan = {
        "size": [192, 160],
        "shots": [
            {
                "video": clip.name,
                "caption": {"text": "Dinner: 50%", "start": 0.2, "end": 0.7, "y": 0.4},
            }
        ],
    }
    assemble_cut(plan, out, resolve=lambda ref: tmp_path / ref, media=without_drawtext)
    assert any("overlay=x=" in str(cmd) for cmd in render_commands)
    frames = subprocess.check_output(
        [
            "ffmpeg",
            "-loglevel",
            "error",
            "-i",
            str(out),
            "-an",
            "-pix_fmt",
            "gray",
            "-f",
            "rawvideo",
            "-",
        ]
    )
    frames = np.frombuffer(frames, np.uint8).reshape(-1, 160, 192)
    assert len(frames) == 24
    assert frames[2].max() < 10 and frames[21].max() < 10
    assert frames[12, 55:90].max() > 200
    assert frames[12, :35].max() < 10 and frames[12, 110:].max() < 10


def test_missing_glyph_has_actionable_error():
    with pytest.raises(ValueError, match="font.*U\\+10FFFF"):
        caption_font(chr(0x10FFFF), 28)


def test_cjk_font_covers_distinct_characters_or_reports_missing_font():
    try:
        font = caption_font("晚餐", 28)
    except ValueError as exc:
        assert "No installed caption font covers the text" in str(exc)
        return
    glyphs = [bytes(font.getmask(char)) for char in "晚餐" + chr(0x10FFFF)]
    assert len(set(glyphs)) == 3
