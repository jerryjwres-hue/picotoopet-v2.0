#!/usr/bin/env python3
"""Stand-alone fixture oracle; NOT a C010A implementation or product QA PASS.

Usage: python verify_media_fixtures.py --fixtures <directory>
Reports UNVERIFIED (exit 2) if FFmpeg/ffprobe are not accessible.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path

PROFILES = {"video.landscape.v1": (832, 480), "video.vertical.v1": (480, 832),
            "video.square.v1": (640, 640)}


def sha256(path: Path) -> str:
    hashed = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1048576), b""):
            hashed.update(block)
    return hashed.hexdigest()


def execute(name: str, args: list[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run([name, "-hide_banner", "-v", "error", *args],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=45, check=False)


def probe(path: Path) -> dict:
    result = execute("ffprobe", ["-show_entries",
        "format=format_name,duration:stream=index,codec_type,codec_name,profile,pix_fmt,width,height,"
        "r_frame_rate,avg_frame_rate,duration,sample_rate,channels:stream_disposition=attached_pic",
        "-show_chapters", "-of", "json", str(path)])
    if result.returncode:
        raise ValueError("CONTAINER_INVALID")
    try:
        return json.loads(result.stdout)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("CONTAINER_INVALID") from exc


def decode(path: Path, narrated: bool) -> bool:
    arguments = ["-nostdin", "-xerror", "-i", str(path), "-map", "0:v:0"]
    if narrated:
        arguments += ["-map", "0:a:0"]
    arguments += ["-f", "null", "-"]
    return execute("ffmpeg", arguments).returncode == 0


def oracle(case: dict, root: Path) -> str:
    file = root / case["file"]
    if file.name != case["file"] or not file.is_file() or file.is_symlink():
        return "ARTIFACT_INVALID"
    if file.stat().st_size != case["bytes"] or sha256(file) != case["sha256"]:
        return "HASH_MISMATCH"
    try:
        data = probe(file)
    except ValueError:
        return "CONTAINER_INVALID"
    fmt = data.get("format", {})
    if "mp4" not in fmt.get("format_name", "").split(",") and "mov" not in fmt.get("format_name", "").split(","):
        return "CONTAINER_INVALID"
    streams = data.get("streams")
    if not isinstance(streams, list) or not streams:
        return "CONTAINER_INVALID"
    videos = [stream for stream in streams if stream.get("codec_type") == "video"]
    audios = [stream for stream in streams if stream.get("codec_type") == "audio"]
    if len(videos) != 1:
        return "VIDEO_STREAM_INVALID"
    if not case["narration_required"] and audios:
        return "AUDIO_STREAM_INVALID"
    if len(streams) != (2 if case["narration_required"] else 1):
        if case["narration_required"] and len(streams) == 1:
            return "AUDIO_STREAM_INVALID"
        return "UNEXPECTED_STREAM"
    if videos[0].get("index") != 0 or videos[0].get("disposition", {}).get("attached_pic") == 1:
        return "VIDEO_STREAM_INVALID"
    video = videos[0]
    if video.get("codec_name") != "h264" or video.get("pix_fmt") != "yuv420p":
        return "VIDEO_STREAM_INVALID"
    if case["profile"] not in PROFILES:
        return "OUTPUT_PROFILE_MISMATCH"
    w, h = PROFILES[case["profile"]]
    try:
        fps = Fraction(video["avg_frame_rate"])
    except (KeyError, ValueError, ZeroDivisionError):
        return "OUTPUT_PROFILE_MISMATCH"
    if (video.get("width"), video.get("height")) != (w, h) or fps != 24:
        return "OUTPUT_PROFILE_MISMATCH"
    if case["narration_required"]:
        if len(audios) != 1 or audios[0].get("index") != 1:
            return "AUDIO_STREAM_INVALID"
        audio = audios[0]
        if (audio.get("codec_name"), audio.get("profile"), str(audio.get("sample_rate")),
            audio.get("channels")) != ("aac", "LC", "48000", 1):
            return "AUDIO_STREAM_INVALID"
    elif audios:
        return "AUDIO_STREAM_INVALID"
    try:
        format_ms = Fraction(fmt["duration"]) * 1000
        video_ms = Fraction(video["duration"]) * 1000
    except (KeyError, ValueError, ZeroDivisionError):
        return "RUNTIME_MISMATCH"
    target = case["target_runtime_ms"]
    if abs(format_ms - target) > 100 or abs(video_ms - target) > Fraction(1000, 24):
        return "RUNTIME_MISMATCH"
    if audios:
        try:
            if abs(Fraction(audios[0]["duration"]) * 1000 - target) > 100:
                return "RUNTIME_MISMATCH"
        except (KeyError, ValueError, ZeroDivisionError):
            return "RUNTIME_MISMATCH"
    if data.get("chapters"):
        return "UNEXPECTED_STREAM"
    if not decode(file, case["narration_required"]):
        return "DECODE_FAILED"
    return "PASS"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, required=True)
    args = parser.parse_args()
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        print("UNVERIFIED: ffmpeg or ffprobe unavailable")
        return 2
    root = args.fixtures.resolve()
    manifest = json.loads((root / "fixture-index.json").read_text(encoding="utf-8"))
    if manifest.get("schema") != "fixture-index.v1":
        raise ValueError("unsupported fixture index")
    failures = 0
    for case in manifest["cases"]:
        actual = oracle(case, root)
        expected = case["expected"]
        matched = (actual in {"CONTAINER_INVALID", "DECODE_FAILED"}) if expected == "UNREADABLE" else actual == expected
        label = "PASS" if matched else "FAIL"
        print(f"{label} {case['id']}: expected={expected} actual={actual}")
        failures += not matched
    print(f"FIXTURE_ORACLE={'PASS' if failures == 0 else 'FAIL'} cases={len(manifest['cases'])} failures={failures}")
    print("PRODUCT_C010A_INTEGRATION=BLOCKED (no frozen callable QA/receipt API in audited base)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
