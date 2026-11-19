"""Read-only Blockout export QA for PicotooPet. No GPU, Core writes, or MCP calls.

Blockout's MCP drives an already-running editor, but has no confirmed export tool.
Use Deliver > Export shot package first, then validate the output with this CLI.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

_MAX_METADATA = 512 * 1024               # 最大元数据读取 512 KiB。
_MAX_MEDIA = 2 * 1024 * 1024 * 1024       # 单条预演媒体最多校验 2 GiB。
_CHUNK = 1024 * 1024                     # SHA-256 流式读写，不加载整个 MP4。


class ProbeUnavailable(RuntimeError):
    """The independent video probe could not run."""


class PackageInvalid(ValueError):
    """The export contains malformed or untrusted media/metadata."""


def _safe_file(root: Path, item: Path) -> Path:
    """Reject links or paths outside the selected package before opening any input."""
    if item.is_symlink() or not item.is_file() or not item.resolve().is_relative_to(root):
        raise PackageInvalid("UNSAFE_OR_MISSING_FILE")
    return item


def _sha256(path: Path) -> str:
    """Hash bounded input bytes, never writing back into the Blockout export."""
    if path.stat().st_size > _MAX_MEDIA:
        raise PackageInvalid("FILE_EXCEEDS_READ_BUDGET")
    digest = hashlib.sha256()
    consumed = 0
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            consumed += len(chunk)
            if consumed > _MAX_MEDIA:
                raise PackageInvalid("FILE_EXCEEDS_READ_BUDGET")
            digest.update(chunk)
    return digest.hexdigest()


def _metadata(root: Path) -> dict:
    path = _safe_file(root, root / "metadata.json")
    if path.stat().st_size > _MAX_METADATA:
        raise PackageInvalid("METADATA_TOO_LARGE")
    try:
        meta = json.loads(path.read_text(encoding="utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PackageInvalid("METADATA_INVALID_JSON") from exc
    if not isinstance(meta, dict):
        raise PackageInvalid("METADATA_NOT_OBJECT")
    generator, shot = meta.get("generator"), meta.get("shot")
    if not isinstance(generator, dict) or generator.get("app") != "Blockout":
        raise PackageInvalid("NOT_BLOCKOUT_METADATA")
    if generator.get("schema") != 1:
        raise PackageInvalid("UNKNOWN_BLOCKOUT_METADATA_SCHEMA")
    if not isinstance(shot, dict):
        raise PackageInvalid("SHOT_METADATA_MISSING")
    duration, fps = shot.get("duration"), shot.get("fps")
    if (
        type(duration) not in (float, int)
        or type(fps) not in (float, int)
        or not math.isfinite(duration)
        or not math.isfinite(fps)
        or duration <= 0
        or fps <= 0
        or fps > 240
    ):
        raise PackageInvalid("SHOT_TIMING_INVALID")
    if not isinstance(meta.get("cameraMarks"), list):
        raise PackageInvalid("CAMERA_MARKS_INVALID")
    if not isinstance(meta.get("subjects"), list):
        raise PackageInvalid("SUBJECT_TRACKS_INVALID")
    return meta


def _probe(path: Path, *, ffprobe: str = "ffprobe") -> dict:
    """Use ffprobe in argv mode; never execute Blockout prompt or workflow JSON."""
    try:
        run = subprocess.run(
            [
                ffprobe, "-v", "error", "-show_streams", "-show_format",
                "-of", "json", str(path),
            ],
            shell=False,
            capture_output=True,
            text=True,
            timeout=35,
            check=False,
        )
    except (FileNotFoundError, PermissionError, subprocess.TimeoutExpired) as exc:
        raise ProbeUnavailable("FFPROBE_UNAVAILABLE") from exc
    if run.returncode:
        raise PackageInvalid("VIDEO_PROBE_FAILED")
    try:
        data = json.loads(run.stdout)
        video = next(s for s in data["streams"] if s["codec_type"] == "video")
        fps = float(Fraction(video["avg_frame_rate"]))
        duration = float(data.get("format", {}).get("duration") or video["duration"])
        width, height = int(video["width"]), int(video["height"])
    except (ValueError, TypeError, KeyError, IndexError, StopIteration, ZeroDivisionError) as exc:
        raise PackageInvalid("VIDEO_STREAM_INVALID") from exc
    if not all(math.isfinite(v) and v > 0 for v in (fps, duration, width, height)):
        raise PackageInvalid("VIDEO_STREAM_INVALID")
    return {"fps": fps, "duration": duration, "width": width, "height": height}


def _matching_media(root: Path, suffix: str) -> Path | None:
    matches = sorted(root.glob(f"*_{suffix}.mp4"))
    if len(matches) > 1:
        raise PackageInvalid("AMBIGUOUS_MEDIA_PASS")
    return _safe_file(root, matches[0]) if matches else None


def validate_package(
    folder: Path,
    *,
    ffprobe: str = "ffprobe",
    expected_seconds: float | None = None,
    expected_fps: float | None = None,
    probe=None,
) -> dict:
    """Verify one previously exported package; never alter it or queue a task."""
    root = Path(folder)
    result = {
        "package": root.name,
        "status": "FAIL",
        "errors": [],
        "warnings": [],
        "files": {},
        "shot": None,
        "camera_marks": None,
        "actor_track_sha256": None,
        "camera_sha256": None,
        "scene_layout_verified": False,     # Blockout metadata does not include the layout.
        "authorized_for_generation": False,
    }
    if root.is_symlink() or not root.is_dir():
        result["errors"].append("PACKAGE_DIRECTORY_UNAVAILABLE")
        return result
    root = root.resolve()
    try:
        meta = _metadata(root)
        shot = meta["shot"]
        result["shot"] = {
            "name": shot.get("name"),
            "duration": shot["duration"],
            "fps": shot["fps"],
            "profile_id": (meta.get("profile") or {}).get("id"),
        }
        result["camera_marks"] = len(meta["cameraMarks"])
        if not meta["cameraMarks"]:
            result["warnings"].append("CAMERA_MARKS_MISSING")
        if not meta["subjects"]:
            result["warnings"].append("SUBJECT_TRACKS_MISSING")
        else:
            tracks = sorted(
                (
                    {"name": t.get("name"), "asset": t.get("asset"), "marks": t.get("marks")}
                    for t in meta["subjects"]
                    if isinstance(t, dict) and isinstance(t.get("marks"), list)
                    and len(t["marks"]) > 0
                ),
                key=lambda t: str(t["name"]),
            )
            if len(tracks) == len(meta["subjects"]):
                raw = json.dumps(tracks, sort_keys=True, separators=(",", ":"), allow_nan=False)
                result["actor_track_sha256"] = hashlib.sha256(raw.encode()).hexdigest()
            else:
                # 任何角色缺少路径，均不能声称多机位共享了完整表演。
                result["warnings"].append("ACTOR_MOTION_NOT_PROVEN")
        raw_camera = json.dumps(
            meta["cameraMarks"], sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        result["camera_sha256"] = hashlib.sha256(raw_camera.encode()).hexdigest()
        ref = _matching_media(root, "reference")
        if ref is None:
            raise PackageInvalid("REFERENCE_VIDEO_MISSING")
        depth = _matching_media(root, "depth")
        if depth is None:
            result["warnings"].append("DEPTH_VIDEO_MISSING")
        for stem, media in (("reference", ref), ("depth", depth)):
            if media is None:
                continue
            _safe_file(root, media)
            result["files"][stem] = {"filename": media.name, "sha256": _sha256(media)}
        for name in ("prompt.txt", "README.txt"):
            _safe_file(root, root / name)
        # Blockout's workflow is strictly advisory: do not open, import or execute it.
        result["workflow_compatibility_verified"] = False
        still_dir = root / "stills"
        if still_dir.is_symlink():
            raise PackageInvalid("STILLS_SYMLINK_BLOCKED")
        if not still_dir.is_dir():
            result["warnings"].append("STILLS_DIRECTORY_MISSING")
        else:
            names = [p.name for p in still_dir.iterdir() if p.is_file() and not p.is_symlink()]
            for required in ("first", "last", "topdown"):
                if not any(n.endswith(".png") and required in n for n in names):
                    result["warnings"].append(f"STILL_{required.upper()}_MISSING")
        runner = probe or (lambda media: _probe(media, ffprobe=ffprobe))
        primary = runner(ref)
        result["files"]["reference"]["probe"] = primary
        tolerance = max(1.0 / shot["fps"], 0.1)
        if abs(primary["duration"] - shot["duration"]) > tolerance:
            result["errors"].append("REFERENCE_DURATION_MISMATCH")
        if abs(primary["fps"] - shot["fps"]) > 0.01:
            result["errors"].append("REFERENCE_FPS_MISMATCH")
        if expected_seconds is not None and abs(shot["duration"] - expected_seconds) > 0.01:
            result["errors"].append("SHOT_DURATION_NOT_EXPECTED")
        if expected_fps is not None and abs(shot["fps"] - expected_fps) > 0.01:
            result["errors"].append("SHOT_FPS_NOT_EXPECTED")
        if depth is not None:
            depth_info = runner(depth)
            result["files"]["depth"]["probe"] = depth_info
            if (
                abs(depth_info["duration"] - primary["duration"]) > tolerance
                or abs(depth_info["fps"] - primary["fps"]) > 0.01
                or (depth_info["width"], depth_info["height"])
                != (primary["width"], primary["height"])
            ):
                result["errors"].append("DEPTH_PASS_NOT_ALIGNED")
        if meta.get("warnings"):
            result["warnings"].append("BLOCKOUT_MOTION_SANITY_WARNINGS")
    except ProbeUnavailable as exc:
        result["errors"].append(str(exc))
        result["status"] = "UNAVAILABLE"
        return result
    except (OSError, PackageInvalid, ValueError, TypeError) as exc:
        result["errors"].append(
            str(exc) if isinstance(exc, PackageInvalid) else "PACKAGE_READ_FAILED"
        )
    result["status"] = (
        "FAIL" if result["errors"] else "WARN" if result["warnings"] else "PASS"
    )
    return result


def compare_coverage(packages: list[dict]) -> dict:
    """Check reused actor trajectories and distinct cameras, NOT 3D scene geometry."""
    usable = all(p["status"] in ("PASS", "WARN") for p in packages)
    tracks = [p.get("actor_track_sha256") for p in packages]
    cameras = [p.get("camera_sha256") for p in packages]
    timing = [
        (p["shot"].get("duration"), p["shot"].get("fps"))
        for p in packages if isinstance(p.get("shot"), dict)
    ]
    timing_matches = bool(usable and len(timing) == len(packages)
                          and len(set(timing)) == 1)
    return {
        "package_count": len(packages),
        "timing_matches": timing_matches,
        "actor_paths_match": bool(timing_matches and tracks and all(tracks)
                                  and len(set(tracks)) == 1),
        "camera_views_differ": bool(usable and all(cameras)
                                   and len(set(cameras)) == len(packages)),
        # Scene entity transforms are not exported in metadata.json; compare in Blockout.
        "same_scene_layout_proven": False,
        "requires_visual_scene_review": True,
        "authorized_for_generation": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only Blockout shot package QA")
    parser.add_argument("packages", nargs="+", type=Path, help="Blockout Deliver export folders")
    parser.add_argument("--ffprobe", default="ffprobe", help="Local ffprobe executable")
    parser.add_argument("--seconds", type=float, help="Expected shot duration (e.g. 4)")
    parser.add_argument("--fps", type=float, help="Expected fps (e.g. 24)")
    args = parser.parse_args(argv)
    if args.seconds is not None and (not math.isfinite(args.seconds) or args.seconds <= 0):
        parser.error("--seconds must be a positive finite number")
    if args.fps is not None and (not math.isfinite(args.fps) or args.fps <= 0):
        parser.error("--fps must be a positive finite number")
    results = [
        validate_package(
            path, ffprobe=args.ffprobe,
            expected_seconds=args.seconds, expected_fps=args.fps,
        )
        for path in args.packages
    ]
    output = {
        "schema": "picotoo.blockout-check.v1",
        "packages": results,
        "coverage": compare_coverage(results) if len(results) > 1 else None,
        "note": "READ_ONLY_PREVIS_NO_GPU_OR_QC_AUTHORITY",
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    if any(p["status"] == "FAIL" for p in results):
        return 2
    if any(p["status"] == "UNAVAILABLE" for p in results):
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
