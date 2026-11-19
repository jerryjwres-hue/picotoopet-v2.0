"""Real CPU-only MP4/ffprobe smoke; this is NOT a Blockout on-device test."""

import json
import shutil
import subprocess

import pytest
from PIL import Image

from scripts.windows.blockout_previs_verify import validate_package


@pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="Independent local ffmpeg/ffprobe binaries unavailable",
)
def test_blockout_package_validator_reads_real_synthetic_mp4(tmp_path):
    # 创建一秒真实视频流，验证 ffprobe 路线，不需要用户 Windows GPU。
    folder = tmp_path / "export-ffprobe"
    folder.mkdir()
    reference = folder / "S01_reference.mp4"
    subprocess.run(
        [
            "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=black:s=128x96:r=24",
            "-t", "1", "-an", "-c:v", "mpeg4", "-q:v", "3",
            "-y", str(reference),
        ],
        check=True,
        timeout=35,
    )
    shutil.copyfile(reference, folder / "S01_depth.mp4")
    (folder / "metadata.json").write_text(
        json.dumps(
            {
                "generator": {"app": "Blockout", "schema": 1},
                "profile": {"id": "test-only", "name": "Synthetic fixture"},
                "shot": {"name": "S01", "duration": 1, "fps": 24},
                "cameraMarks": [{"time": 0, "position": {"x": 0, "y": 2, "z": 5}}],
                "subjects": [{
                    "name": "MAOTAI", "asset": "animal.dog",
                    "marks": [{"time": 0, "position": {"x": 0, "z": 0}}],
                }],
                "warnings": [],
            }
        ),
        encoding="utf-8",
    )
    (folder / "prompt.txt").write_text("Synthetic movement fixture", encoding="utf-8")
    (folder / "README.txt").write_text("Synthetic Blockout format", encoding="utf-8")
    stills = folder / "stills"
    stills.mkdir()
    for suffix in ("first", "last", "topdown"):
        Image.new("RGB", (16, 16), "black").save(stills / f"S01_{suffix}.png")

    # 独立 ffprobe 真实解码流参数；深度仅用于时基同步，不伪称深度内容有效。
    result = validate_package(folder, expected_seconds=1, expected_fps=24)
    assert result["status"] == "PASS", result
    assert result["files"]["reference"]["probe"]["fps"] == 24
    assert result["files"]["reference"]["probe"]["duration"] == pytest.approx(1.0, abs=0.05)
    assert result["files"]["depth"]["probe"]["width"] == 128
    assert result["files"]["depth"]["probe"]["height"] == 96
    assert result["workflow_compatibility_verified"] is False
    assert result["authorized_for_generation"] is False
