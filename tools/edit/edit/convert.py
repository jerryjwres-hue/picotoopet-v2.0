"""Normalize cut_v2 plans into a portable, explicitly timed production edit plan."""

import json
import math
import os
import subprocess
import tempfile
from pathlib import Path

from .production import as_list, cut_transition, number

FORMAT = "edit.production.v1"


def convert_plan(source, root, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination or (destination.exists() and source.samefile(destination)):
        raise ValueError("Use a separate output file to preserve the source plan")
    raw = json.loads(source.read_text(encoding="utf-8-sig"))
    if raw.get("format") not in (None, FORMAT):
        raise ValueError("Unrecognized source edit format")
    asset_root = Path(root).resolve() if root else (source.parent / raw["root"]).resolve()
    if not asset_root.is_dir():
        raise ValueError("Asset root is missing")

    def asset(ref):
        path = (asset_root / ref).resolve(strict=True)
        if not path.is_relative_to(asset_root) or not path.is_file():
            raise ValueError("Asset must be a file within the project root")
        return path.relative_to(asset_root).as_posix()

    def audio_track(item, default_gain):
        item = dict(item)
        item["file"] = asset(item["file"])
        item["gain_db"] = number(item.pop("db", item.get("gain_db", default_gain)))
        return item

    try:
        root_ref = Path(os.path.relpath(asset_root, destination.parent)).as_posix()
    except ValueError:  # Windows paths on different volumes have no relative form.
        root_ref = asset_root.as_posix()
    plan = {
        **raw,
        "format": FORMAT,
        "root": root_ref,
        "size": raw.get("size", [1080, 1920]),
        "fps": number(raw.get("fps", 24), 0.001),
        "loudness_lufs": number(raw.get("loudness_lufs", -14)),
        "shots": [],
        "music": [],
        "sfx": [],
    }
    if raw.get("font"):
        plan["font"] = asset(raw["font"])
    starts, durations, overlaps, ids, media_durations = [], [], [], set(), {}
    for index, original in enumerate(raw["shots"]):
        shot = dict(original)
        shot_id = shot.get("shot_id", f"S{index + 1:02}")
        if not isinstance(shot_id, str) or not shot_id or shot_id in ids:
            raise ValueError(f"Invalid or duplicate shot ID at index {index}")
        ids.add(shot_id)
        clip = asset(shot["video"])
        if clip not in media_durations:
            result = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "csv=p=0",
                    str(asset_root / clip),
                ],
                capture_output=True,
            )
            if result.returncode:
                raise ValueError(f"Cannot read duration of {clip}")
            media_durations[clip] = number(result.stdout, 0)
        a = number(shot.get("in", 0), 0)
        b = min(media_durations[clip], number(shot.get("out", media_durations[clip]), 0))
        speed = number(shot.get("speed", 1), 0.001)
        length = (b - a) / speed
        ramp = min(length, number(shot.get("ramp_seconds", 0), 0))
        length -= ramp * (1 - math.log(2))
        if length < 1 / plan["fps"]:
            raise ValueError(f"Shot {shot_id} is shorter than one frame")
        start = (
            starts[-1] + durations[-1] - min(overlaps[-1], durations[-1] / 2, length / 2)
            if index
            else 0
        )
        starts.append(start)
        durations.append(length)
        kind, overlap = cut_transition(shot.get("transition_out", "cut"))
        overlaps.append(overlap)
        direction = kind.removeprefix("whip_") if kind.startswith("whip_") else None
        transition = {"type": "whip" if direction else kind, "dur": overlap}
        if direction:
            transition["dir"] = direction
        shot.update(
            shot_id=shot_id,
            video=clip,
            speed=speed,
            transition_out=transition,
            audio_offset=number(shot.get("audio_offset", 0)),
            ltx_db=number(shot.get("ltx_db", 0)),
            vocal=shot.get("vocal", True),
            foley=[audio_track(f, -3) for f in as_list(shot.get("foley"))],
        )
        shot["in"], shot["out"] = a, b
        if shot.get("caption"):
            cap = shot["caption"]
            shot["caption"] = {
                **cap,
                "start": number(cap.get("start", 0.2), 0),
                "end": number(cap.get("end", length), 0),
                "y": number(cap.get("y", 0.2), 0),
            }
        if shot.get("punch_in"):
            pi = shot["punch_in"]
            shot["punch_in"] = {
                **pi,
                "t": number(pi["t"], 0),
                "scale": number(pi["scale"], 1),
                "dur": number(pi.get("dur", 0.25), 0.001),
            }
        plan["shots"].append(shot)
    if not starts:
        raise ValueError("At least one shot is required")
    total = starts[-1] + durations[-1]
    for original in as_list(raw.get("music")):
        cue = audio_track(original, -14)
        if "shot" in cue:
            i = cue["shot"]
            if type(i) is not int or not 0 <= i < len(starts):
                raise ValueError(f"Invalid music cue shot index: {i}")
            cue["offset"] = number(cue.get("offset", 0))
            at = starts[i] + cue["offset"]
        else:
            at = number(cue.get("at", 0))
            cue["at"] = at
        cue.update(
            dur=number(cue.get("dur", total - at), 0),
            fade_in=number(cue.get("fade_in", 0.3), 0),
            fade_out=number(cue.get("fade_out", 0.8), 0),
        )
        cue["in"] = number(cue.get("in", 0), 0)
        plan["music"].append(cue)
    for original in raw.get("sfx", []):
        cue = audio_track(original, 0)
        cue["at"] = number(cue["at"], 0)
        plan["sfx"].append(cue)

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=destination.parent, delete=False
    ) as stream:
        pending = Path(stream.name)
        try:
            json.dump(plan, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
        except BaseException:
            stream.close()
            pending.unlink(missing_ok=True)
            raise
    try:
        pending.replace(destination)
    finally:
        pending.unlink(missing_ok=True)
    return plan
