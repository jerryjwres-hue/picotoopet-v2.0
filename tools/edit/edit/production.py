"""FFmpeg backend for production cut plans and reviewed executor inputs.

Timing and mixing follow the original cut_v2 edit. All intermediate media live in
an isolated working directory. The executor supplies its lease-aware process runner.
"""

import json
import math
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

TRANSITIONS = {
    "hard": (None, 0),
    "cut": ("fade", 0.04),
    "match": ("fade", 0.16),
    "whip_left": ("slideleft", 0.18),
    "whip_right": ("slideright", 0.18),
    "whip_up": ("slideup", 0.18),
    "whip_down": ("slidedown", 0.18),
    "dip": ("fadeblack", 0.30),
    "zoom": ("zoomin", 0.25),
}


def number(value, minimum=None):
    n = float(value)
    if not math.isfinite(n) or (minimum is not None and n < minimum):
        raise ValueError(f"Invalid edit parameter: {value!r}")
    return n


def local_media(cmd, cwd):
    return subprocess.run(cmd, cwd=cwd, capture_output=True)


def as_list(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def splice_video(ff, shots, starts, edges, fps):
    inputs = []
    graph = []
    has_concat = any(effect is None for effect, _ in edges)
    last = "in0" if has_concat else "0:v"
    for i in range(len(shots)):
        inputs += ["-i", f"v{i}.mp4"]
        if has_concat:
            graph.append(f"[{i}:v]settb=expr=1/{fps}[in{i}]")
        if i:
            effect, overlap = edges[i - 1]
            op = (
                f"xfade=transition={effect}:duration={overlap:.6f}:offset={starts[i]:.3f}"
                if effect
                else "concat=n=2:v=1:a=0"
            )
            # concat changes the timebase to AVTB; normalize after each splice.
            incoming = f"in{i}" if has_concat else f"{i}:v"
            timebase = f",settb=expr=1/{fps}" if has_concat else ""
            graph.append(f"[{last}][{incoming}]{op}{timebase}[x{i}]")
            last = f"x{i}"
    video = "v0.mp4"
    if len(shots) > 1:
        ff(
            *inputs,
            "-filter_complex",
            ";".join(graph),
            "-map",
            f"[{last}]",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "video.mp4",
        )
        video = "video.mp4"
    return video


def mix_audio(ff, plan, shots, starts, total, resolve):
    inputs, graph, labels = [], [], []

    def delayed(t):
        if t < 0:
            return f"atrim=start={-t},asetpts=PTS-STARTPTS"
        return f"adelay={int(t * 1000)}:all=1"

    for i, shot in enumerate(shots):
        inputs += ["-i", f"a{i}.wav"]
        start = starts[i] + number(shot.get("audio_offset", 0))
        graph.append(f"[{i}:a]{delayed(start)}[s{i}]")
        labels.append(f"[s{i}]")
    for fx in plan.get("sfx", []):
        j = len(labels)
        inputs += ["-i", resolve(fx["file"])]
        graph.append(
            f"[{j}:a]aresample=48000,aformat=channel_layouts=stereo,"
            f"volume={number(fx.get('db', 0))}dB,"
            f"{delayed(number(fx['at'], 0))}[s{j}]"
        )
        labels.append(f"[s{j}]")
    graph.append(
        f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0,"
        f"apad=whole_dur={total:.6f},atrim=0:{total:.6f}[fx]"
    )
    mixed = "fx"
    cues = as_list(plan.get("music"))
    if cues:
        for k, cue in enumerate(cues):
            inputs += ["-i", resolve(cue["file"])]
            at = (
                starts[cue["shot"]] + number(cue.get("offset", 0))
                if "shot" in cue
                else number(cue.get("at", 0))
            )
            d = number(cue.get("dur", total - at), 0)
            ci = number(cue.get("in", 0), 0)
            fi, fo = number(cue.get("fade_in", 0.3), 0), number(cue.get("fade_out", 0.8), 0)
            graph.append(
                f"[{len(labels) + k}:a]atrim={ci}:{ci + d:.3f},asetpts=PTS-STARTPTS,"
                "aresample=48000,aformat=channel_layouts=stereo,"
                f"volume={number(cue.get('db', -14))}dB,"
                f"afade=t=in:d={fi},afade=t=out:st={max(0, d - fo):.3f}:d={fo},"
                f"{delayed(at)}[m{k}]"
            )
        music_labels = "".join(f"[m{k}]" for k in range(len(cues)))
        graph += [
            f"{music_labels}amix=inputs={len(cues)}:normalize=0[mu]",
            "[fx]asplit=2[f1][f2]",
            "[mu][f2]sidechaincompress=threshold=0.05:ratio=6:attack=20:release=300[duck]",
            "[f1][duck]amix=inputs=2:normalize=0[mix]",
        ]
        mixed = "mix"
    finite = "aeval='if(isnan(val(ch))+isinf(val(ch)),0,val(ch))':c=same"
    target = number(plan.get("loudness_lufs", -14))
    graph.append(f"[{mixed}]atrim=0:{total:.3f},loudnorm=I={target}:TP=-1.5:LRA=11,{finite}[out]")
    ff(
        *inputs,
        "-filter_complex",
        ";".join(graph),
        "-map",
        "[out]",
        "-ar",
        "48000",
        "audio.wav",
    )


def assemble_cut(plan, output, *, resolve, media=local_media, edl=None, strip=None):
    """Render a cut_v2 dictionary. resolve maps asset references to local paths."""
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent, prefix="cut_") as temp:
        work = Path(temp)

        def run(cmd):
            result = media(cmd, work)
            if result.returncode:
                detail = result.stderr.decode("utf-8", errors="replace")[-1800:]
                raise ValueError(f"{cmd[0]} failed: {detail}")
            return result.stdout

        def ff(*args):
            run(
                [
                    "ffmpeg",
                    "-nostdin",
                    "-v",
                    "error",
                    "-y",
                    "-filter_complex_threads",
                    "2",
                    "-filter_threads",
                    "2",
                    *map(str, args),
                ]
            )

        def probe(path):
            return json.loads(
                run(
                    [
                        "ffprobe",
                        "-v",
                        "error",
                        "-show_entries",
                        "stream=codec_type:format=duration",
                        "-of",
                        "json",
                        str(path),
                    ]
                )
            )

        width, height = [int(number(x, 2)) for x in plan.get("size", [1080, 1920])]
        fps = number(plan.get("fps", 24), 0.001)
        font = plan.get("font")
        if font:
            shutil.copyfile(resolve(font), work / "caption.ttf")
        elif os.name == "nt":
            fallback = Path(os.environ["WINDIR"]) / "Fonts" / "arialbd.ttf"
            if fallback.is_file():
                shutil.copyfile(fallback, work / "caption.ttf")
        fontarg = "fontfile=caption.ttf" if (work / "caption.ttf").exists() else "font=Sans"

        starts, durations, edges = [], [], []
        shots = plan["shots"]
        if not shots:
            raise ValueError("At least one shot is required")
        for i, shot in enumerate(shots):
            path = resolve(shot["video"])
            info = probe(path)
            duration = number(info["format"]["duration"], 0)
            a = number(shot.get("in", 0), 0)
            b = min(duration, number(shot.get("out", duration), 0))
            speed = number(shot.get("speed", 1), 0.001)
            length = (b - a) / speed
            ramp = min(length, number(shot.get("ramp_seconds", 0), 0))
            ramp_start = length - ramp
            if ramp:
                # Speed increases linearly with source time from 1x to 2x.
                # Integrating inverse speed gives the output timestamp.
                length = ramp_start + ramp * math.log(2)
            tail = number(shot.get("audio_tail", 0), 0)
            if length < 1 / fps:
                raise ValueError(f"Shot {i + 1} is shorter than one frame")
            if i:
                kind = shots[i - 1].get("transition_out", "cut")
                if kind not in TRANSITIONS:
                    raise ValueError(f"Unsupported outgoing transition: {kind}")
                effect, overlap = TRANSITIONS[kind]
                overlap = min(overlap, length / 2, durations[-1] / 2)
                starts.append(starts[-1] + durations[-1] - overlap)
                edges.append((effect, overlap))
            else:
                starts.append(0.0)
            durations.append(length)
            filters = [f"trim={a}:{b}", "setpts=PTS-STARTPTS"]
            if speed != 1:
                filters.append(f"setpts=PTS/{speed}")
            if ramp:
                filters.append(
                    f"setpts='if(lt(T,{ramp_start}),T,{ramp_start}+"
                    f"{ramp}*log(1+(T-{ramp_start})/{ramp}))/TB'"
                )
            if plan.get("fit") == "contain":
                filters.extend(
                    [
                        f"scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2",
                        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
                    ]
                )
            else:
                filters.append(f"scale={width}:{height}:flags=lanczos")
            filters += ["setsar=1", f"fps={fps}"]
            if shot.get("punch_in"):
                pi = shot["punch_in"]
                t, scale, d = (
                    number(pi["t"], 0),
                    number(pi["scale"], 1),
                    number(pi.get("dur", 0.25), 0.001),
                )
                e = f"(1+({scale}-1)*min(1,max(0,(t-{t})/{d})))"
                filters += [
                    f"scale=w='trunc({width}*{e}/2)*2':h='trunc({height}*{e}/2)*2':eval=frame:flags=bicubic",
                    f"crop={width}:{height}",
                    "setsar=1",
                ]
            if shot.get("caption"):
                cap = shot["caption"]
                (work / f"c{i}.txt").write_text(cap["text"], encoding="utf-8")
                st, en = number(cap.get("start", 0.2), 0), number(cap.get("end", length), 0)
                y = number(cap.get("y", 0.20), 0)
                filters.append(
                    f"drawtext={fontarg}:textfile=c{i}.txt:expansion=none:"
                    f"fontsize={max(10, round(width * 64 / 1080))}"
                    f":fontcolor=white:borderw={max(1, round(width * 7 / 1080))}"
                    ":bordercolor=black@0.85:x=(w-text_w)/2"
                    f":y='h*{y}-20*max(0,1-(t-{st})/0.18)':enable='between(t,{st},{en})':alpha='min(1,(t-{st})/0.15)'"
                )
            ff(
                "-i",
                path,
                "-vf",
                ",".join(filters + ["format=yuv420p"]),
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "16",
                f"v{i}.mp4",
            )

            has_audio = any(s["codec_type"] == "audio" for s in info["streams"])
            inputs = (
                ["-i", path]
                if has_audio and shot.get("vocal", True)
                else ["-f", "lavfi", "-t", str(b), "-i", "anullsrc=r=48000:cl=stereo"]
            )
            tracks = as_list(shot.get("foley"))
            gains = [number(shot.get("ltx_db", 0))]
            for track in tracks:
                inputs += ["-i", resolve(track["file"])]
                gains.append(number(track.get("db", -3)))
            graph = []
            for j, gain in enumerate(gains):
                fx = [f"atrim={a}:{b + tail * speed}", "asetpts=PTS-STARTPTS"]
                remaining = speed
                while remaining < 0.5 or remaining > 2:
                    step = 0.5 if remaining < 0.5 else 2
                    fx.append(f"atempo={step}")
                    remaining /= step
                if remaining != 1:
                    fx.append(f"atempo={remaining}")
                if ramp:
                    # Change tempo on source-time boundaries every output frame.
                    count = max(2, math.ceil(ramp * fps))
                    commands = ";".join(
                        f"{ramp_start + ramp * k / count:.6f} atempo@ramp tempo {1 + k / count:.6f}"
                        for k in range(count + 1)
                    )
                    fx += [f"asendcmd=c='{commands}'", "atempo@ramp=1"]
                fx += ["aresample=48000", "aformat=channel_layouts=stereo", f"volume={gain}dB"]
                if j == 0:
                    fx += [
                        "afade=t=in:d=0.03",
                        f"afade=t=out:st={max(0, length + tail - 0.05):.3f}:d=0.05",
                    ]
                graph.append(f"[{j}:a]{','.join(fx)}[a{j}]")
            labels = "".join(f"[a{j}]" for j in range(len(gains)))
            graph.append(
                f"{labels}amix=inputs={len(gains)}:normalize=0,"
                f"apad=whole_dur={length + tail:.6f},atrim=0:{length + tail:.6f}[o]"
            )
            ff(*inputs, "-filter_complex", ";".join(graph), "-map", "[o]", f"a{i}.wav")

        total = starts[-1] + durations[-1]
        video = splice_video(ff, shots, starts, edges, fps)
        mix_audio(ff, plan, shots, starts, total, resolve)
        ff(
            "-i",
            video,
            "-i",
            "audio.wav",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-aac_coder",
            "fast",
            "-b:a",
            "192k",
            "-shortest",
            "-movflags",
            "+faststart",
            "output.mp4",
        )
        rows = [
            {
                "shot_id": shot.get("shot_id", f"S{i + 1:02}"),
                "start": starts[i],
                "duration": durations[i],
                "transition_out": shot.get("transition_out", "cut"),
            }
            for i, shot in enumerate(shots)
        ]
        if edl:
            Path(edl).write_text(
                "".join(
                    f"{r['shot_id']}\t{r['start']:.2f}\t{r['duration']:.2f}\t{r['transition_out']}\n"
                    for r in rows
                ),
                encoding="utf-8",
            )
        if strip:
            ff(
                "-i",
                "output.mp4",
                "-vf",
                f"fps={len(rows)}/{total},scale=160:-2,tile={len(rows)}x1",
                "-frames:v",
                "1",
                "-update",
                "1",
                Path(strip).resolve(),
            )
        (work / "output.mp4").replace(output)
        return rows


def executor_plan(jobs, resolve, digest):
    """Bind the reviewed video and audio assets to the production cut format."""
    plan = {**jobs["edit"], "fit": "contain", "shots": [], "music": []}

    def checked(ref):
        path = resolve(ref["file"])
        if not path.is_file():
            raise ValueError("An edit asset is missing: " + path.name)
        if ref.get("sha256") and digest(path) != ref["sha256"]:
            raise ValueError("Reviewed asset digest changed: " + path.name)
        return {**ref, "file": str(path), "db": ref.get("db", ref.get("gain_db", 0))}

    lead = 0
    for i, item in enumerate(jobs["shots"]):
        source = checked({"file": item["path"], "sha256": item["sha256"]})
        audio = item["audio"]
        shot = {
            "shot_id": item["shot_id"],
            "video": source["file"],
            "out": item["seconds"],
            "audio_offset": lead,
            "vocal": audio.get("vocal_from") != "none",
        }
        if item.get("caption"):
            shot["caption"] = {"text": item["caption"], "start": 0, "end": item["seconds"]}
        tr = item["transition_out"]
        kind, offset = tr["type"], number(tr["offset_s"])
        lead = 0
        if kind in {"j_cut", "l_cut"}:
            if kind == "j_cut":
                lead = -abs(offset)
            else:
                shot["audio_tail"] = abs(offset)
            kind = "hard"
        elif kind == "speed_ramp":
            shot["ramp_seconds"] = abs(offset) or 0.25
            kind = "hard"
        elif kind == "cut":
            kind = "hard"
        elif kind == "whip":
            kind = "whip_" + tr.get("dir", "left")
        if kind not in TRANSITIONS:
            raise ValueError(f"Unsupported outgoing transition: {kind}")
        shot["transition_out"] = kind
        if offset and tr["type"] in {"cut", "match", "whip"}:
            lead = offset
        # Foley strings in the episode describe sounds to generate. The mixer
        # uses the rendered tracks returned for the selected take.
        tracks = item.get("foley_tracks") or [
            x for x in audio.get("foley", []) if isinstance(x, dict) and "file" in x
        ]
        shot["foley"] = [checked(x) for x in tracks]
        for cue in as_list(audio.get("music_cue")):
            if isinstance(cue, str):
                cue = {"file": cue}
            if "file" not in cue:
                raise ValueError("Music cue requires a rendered audio file")
            plan["music"].append({"shot": i, **checked(cue)})
        plan["shots"].append(shot)
    return plan


def assemble_job(jobs, output, *, resolve, digest, media):
    plan = executor_plan(jobs, resolve, digest)
    return assemble_cut(plan, output, resolve=resolve, media=media)
