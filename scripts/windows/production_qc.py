"""Run the local QC CLI for each leased candidate and keep its full report."""

import hashlib
import json
import math
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory


def check_candidates(bridge, state, candidates):
    payload = state["task"]["payload"]
    jobs = payload["jobs"]
    source = jobs.get("source_jobs", jobs)
    shot = source.get("shot", {})
    specification = source.get("qc_spec", shot.get("qc_spec", {}))
    if not isinstance(specification, dict):
        raise ValueError("qc_spec 须为对象。")
    spec = {
        **specification,
        "shot_id": payload.get("shot_id") or shot.get("shot_id") or state["stem"],
    }
    spec.setdefault("check_entity_counts", "expect" in spec)
    if "identity_refs" in spec:
        spec["identity_refs"] = {
            key: str(bridge._safe_path(path)) for key, path in spec["identity_refs"].items()
        }
    started = time.monotonic()
    reports = {}
    previews = {}
    for candidate in candidates:
        if candidate["kind"] not in {"image", "video"}:
            continue
        path = bridge._safe_path(candidate["path"])
        digest = bridge._hash(path, state)[0]
        if digest != candidate["sha256"]:
            raise ValueError("质检时源文件哈希已改变。")
        # Keep paths usable with Win32 media libraries on deeply nested project volumes.
        report_key = hashlib.sha256(f"{state['stem']}:{digest}".encode()).hexdigest()[:32]
        folder = bridge.state_dir / "qc" / report_key
        folder.mkdir(exist_ok=True, parents=True)
        spec_path, report_path, preview = (
            folder / name for name in ("spec.json", "report.json", "report.jpg")
        )
        spec_path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
        tool = Path(__file__).resolve().parents[2] / "tools/qc"
        with TemporaryDirectory(dir=folder) as temp:
            fresh = Path(temp) / "report.json"
            jpg = fresh.with_suffix(".jpg")
            run = bridge._media(
                state,
                [
                    sys.executable,
                    "-X",
                    "utf8",
                    "-m",
                    "qc",
                    "check",
                    "--spec",
                    str(spec_path),
                    "--media",
                    str(path),
                    "--out",
                    str(fresh),
                    "--out-jpg",
                    str(jpg),
                ],
                cwd=tool,
            )
            if run.returncode not in (0, 1) or not fresh.is_file() or not jpg.is_file():
                raise ValueError(
                    "本地 QC 工具未生成完整报告。" + run.stderr.decode("utf-8", "replace")[-420:]
                )
            report = json.loads(fresh.read_text(encoding="utf-8"))
            if type(report.get("pass")) is not bool or report["pass"] != (run.returncode == 0):
                raise ValueError("QC 进程与报告结果不一致。")
            fresh.replace(report_path)
            jpg.replace(preview)
        fails = [str(item["detail"]) for item in report["fails"]]
        item = {"report": report, "score": report["score"], "fails": fails, "通过": True}
        if candidate["kind"] == "video":
            metadata = bridge._probe(state, path)
            streams = metadata["streams"]
            video = next((s for s in streams if s["codec_type"] == "video"), {})
            seconds = float(metadata["format"].get("duration") or 0)
            target = shot.get("seconds")
            item.update(
                {
                    "秒数": seconds,
                    "宽": video.get("width"),
                    "高": video.get("height"),
                    "有音轨": any(s["codec_type"] == "audio" for s in streams),
                    "通过": bool(
                        video
                        and math.isfinite(seconds)
                        and seconds > 0
                        and (target is None or abs(seconds - target) < 0.5)
                    ),
                }
            )
            if not item["通过"]:
                fails.append("视频流或时长与分镜不符。")
        item["passed"] = report["pass"] and item["通过"]
        reports[digest] = item
        previews[digest] = preview
    if not reports:
        raise ValueError("质检任务没有图片或视频候选。")
    worst = min(reports, key=lambda d: (reports[d]["passed"], reports[d]["score"]))
    return {
        "ok": True,
        "seconds": time.monotonic() - started,
        "sheet": str(previews[worst]),
        "qc_previews": previews,
        "qc": {
            "passed": all(v["passed"] for v in reports.values()),
            "score": min(v["score"] for v in reports.values()),
            "fails": list(dict.fromkeys(f for v in reports.values() for f in v["fails"])),
            "by_sha256": reports,
        },
    }
