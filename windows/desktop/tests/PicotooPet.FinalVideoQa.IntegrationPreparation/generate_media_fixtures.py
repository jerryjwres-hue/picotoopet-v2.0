#!/usr/bin/env python3
"""Create synthetic C010 media QA fixtures; never constructs C010A production objects.

Usage: python generate_media_fixtures.py --output <disposable-directory>
Only write into an empty directory. Requires FFmpeg and ffprobe on PATH.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

PROFILES = {"landscape": (832, 480), "vertical": (480, 832), "square": (640, 640)}


def sha256(path: Path) -> str:
    hash_ = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1048576), b""):
            hash_.update(block)
    return hash_.hexdigest()


def run(executable: str, arguments: list[str]) -> None:
    result = subprocess.run([executable, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", *arguments],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=120)
    if result.returncode:
        raise RuntimeError(f"fixture generation tool failed: {executable} exit={result.returncode}")


def video(output: Path, width: int, height: int, fps: int = 24, frames: int = 48,
          codec: str = "libx264", pixel_format: str = "yuv420p") -> None:
    run("ffmpeg", ["-f", "lavfi", "-i", f"testsrc2=size={width}x{height}:rate={fps}",
                   "-frames:v", str(frames), "-an", "-c:v", codec, "-preset", "ultrafast"]
        + (["-pix_fmt", pixel_format] if codec == "libx264" else [])
        + ["-movflags", "+faststart", output.as_posix()])


def audio(output: Path, visual: Path, *, rate: int = 48000, channels: int = 1,
          count: int = 1, audio_codec: str = "aac") -> None:
    args = ["-i", visual.as_posix()]
    for i in range(count):
        args += ["-f", "lavfi", "-i", f"sine=frequency={440 + i * 220}:sample_rate={rate}:duration=2"]
    args += ["-map", "0:v:0"]
    for i in range(count):
        args += ["-map", f"{i+1}:a:0"]
    args += ["-c:v", "copy", "-c:a", audio_codec, "-ar", str(rate), "-ac", str(channels),
             "-movflags", "+faststart", output.as_posix()]
    run("ffmpeg", args)


def subtitles(output: Path, visual: Path, srt: Path) -> None:
    run("ffmpeg", ["-i", visual.as_posix(), "-i", srt.as_posix(),
                   "-map", "0:v:0", "-map", "1:s:0", "-c:v", "copy", "-c:s", "mov_text",
                   "-movflags", "+faststart", output.as_posix()])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        print("UNVERIFIED: ffmpeg/ffprobe unavailable", file=sys.stderr)
        return 2
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        parser.error("--output must be an empty disposable directory; nothing is overwritten")
    output.mkdir(parents=True, exist_ok=True)
    cases = []

    def register(id_: str, file: Path, expected: str, *, narration_required: bool = False,
                 profile: str = "landscape", target_ms: int = 2000, digest_before_mutation: str | None = None):
        cases.append({"id": id_, "file": file.name, "profile": f"video.{profile}.v1",
                      "target_runtime_ms": target_ms, "narration_required": narration_required,
                      "expected": expected, "bytes": file.stat().st_size,
                      "sha256": digest_before_mutation or sha256(file)})

    for profile, (width, height) in PROFILES.items():
        visual = output / f"valid_{profile}_visual.mp4"
        narrated = output / f"valid_{profile}_narrated.mp4"
        video(visual, width, height)
        audio(narrated, visual)
        register(f"FVQ-M-{profile.upper()}-VISUAL", visual, "PASS", profile=profile)
        register(f"FVQ-M-{profile.upper()}-NARRATED", narrated, "PASS", narration_required=True, profile=profile)

    visual = output / "valid_landscape_visual.mp4"
    narrated = output / "valid_landscape_narrated.mp4"
    register("FVQ-N-MISSING-AUDIO", visual, "AUDIO_STREAM_INVALID", narration_required=True)
    register("FVQ-N-UNWANTED-AUDIO", narrated, "AUDIO_STREAM_INVALID", narration_required=False)

    wrong_codec = output / "wrong_video_codec.mp4"
    video(wrong_codec, 832, 480, codec="mpeg4")
    register("FVQ-N-VIDEO-CODEC", wrong_codec, "VIDEO_STREAM_INVALID")

    wrong_pix = output / "wrong_pixel_format.mp4"
    video(wrong_pix, 832, 480, pixel_format="yuv444p")
    register("FVQ-N-PIXEL-FORMAT", wrong_pix, "VIDEO_STREAM_INVALID")

    wrong_size = output / "wrong_dimensions.mp4"
    video(wrong_size, 830, 480)
    register("FVQ-N-GEOMETRY", wrong_size, "OUTPUT_PROFILE_MISMATCH")

    wrong_fps = output / "wrong_fps.mp4"
    video(wrong_fps, 832, 480, fps=25, frames=50)
    register("FVQ-N-FPS", wrong_fps, "OUTPUT_PROFILE_MISMATCH")

    wrong_length = output / "wrong_runtime.mp4"
    video(wrong_length, 832, 480, frames=72)
    register("FVQ-N-RUNTIME", wrong_length, "RUNTIME_MISMATCH")

    wrong_channels = output / "wrong_audio_channels.mp4"
    audio(wrong_channels, visual, channels=2)
    register("FVQ-N-AUDIO-CHANNELS", wrong_channels, "AUDIO_STREAM_INVALID", narration_required=True)

    wrong_rate = output / "wrong_audio_rate.mp4"
    audio(wrong_rate, visual, rate=44100)
    register("FVQ-N-AUDIO-RATE", wrong_rate, "AUDIO_STREAM_INVALID", narration_required=True)

    extra_audio = output / "extra_audio_stream.mp4"
    audio(extra_audio, visual, count=2)
    register("FVQ-N-EXTRA-AUDIO", extra_audio, "UNEXPECTED_STREAM", narration_required=True)

    srt = output / "fixture-only.srt"
    srt.write_text("1\n00:00:00,200 --> 00:00:01,000\nsynthetic fixture\n", encoding="utf-8")
    unexpected_subtitle = output / "subtitle_stream.mp4"
    subtitles(unexpected_subtitle, visual, srt)
    register("FVQ-N-SUBTITLE", unexpected_subtitle, "UNEXPECTED_STREAM")

    invalid = output / "invalid_container.mp4"
    invalid.write_bytes(b"not a media file: synthetic C010 QA fixture\n")
    register("FVQ-N-INVALID-CONTAINER", invalid, "CONTAINER_INVALID")

    truncated = output / "truncated.mp4"
    raw = narrated.read_bytes()
    truncated.write_bytes(raw[:len(raw) // 2])
    register("FVQ-N-TRUNCATED", truncated, "UNREADABLE", narration_required=True)

    tampered = output / "tampered_same_size.mp4"
    shutil.copyfile(visual, tampered)
    original_digest = sha256(tampered)
    with tampered.open("r+b") as stream:
        stream.seek(-4, 2)
        old = stream.read(1)
        stream.seek(-4, 2)
        stream.write(bytes([old[0] ^ 0xFF]))
    register("FVQ-N-SHA-TAMPER", tampered, "HASH_MISMATCH", digest_before_mutation=original_digest)

    manifest = {"schema": "fixture-index.v1", "origin": "synthetic-standalone-not-C009-artifacts",
                "target_fps": 24, "cases": cases}
    (output / "fixture-index.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"FIXTURES_GENERATED={len(cases)}")
    print(f"OUTPUT={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
