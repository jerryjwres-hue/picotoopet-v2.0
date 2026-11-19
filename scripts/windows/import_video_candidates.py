"""Read completed studio video receipts and register candidates without generating media."""

import argparse
import base64
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import tomllib
from fractions import Fraction
from pathlib import Path, PureWindowsPath
from urllib.parse import urlsplit

if __package__:
    from .media_probe import probe_command, probe_json
else:
    from media_probe import probe_command, probe_json

BOARD = "17_静态首帧板V2"
RUNNER = "run_ltx_flf.py"
ID = re.compile(r"[A-Za-z0-9_-]+")
MAX_CANDIDATES = 128
MAX_THUMBNAIL_BYTES = 300 * 1024
NO_CONSOLE = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _read_object(path):
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} 应为 JSON 对象。")
    return data


def _inside(root, path):
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"路径超出指定目录：{path.name}")
    return resolved


def _worker_path(base, value):
    if not isinstance(value, str) or not value or PureWindowsPath(value).anchor:
        raise ValueError("工作文件须使用项目内的相对路径。")
    return base / value.replace("\\", "/")


def _snapshot(path):
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns


def _identifier(value, limit, label):
    if not isinstance(value, str) or len(value) > limit or not ID.fullmatch(value):
        raise ValueError(f"{label} 须为合法标识。")
    return value


def _read_batch(root, jobs_path, receipt_path, shot_prefix, *, shot_id_limit=80):
    board = _inside(root, root / BOARD)
    done = _inside(root, root / "_queue" / "done")
    receipt_path = _inside(done, done / receipt_path)
    if not receipt_path.name.endswith(".result.json"):
        raise ValueError("请选择 _queue/done 下的 .result.json 回执。")
    task = _identifier(receipt_path.name.removesuffix(".result.json"), 100, "回执任务名")
    request_path = _inside(done, done / (task + ".json"))
    if not receipt_path.is_file() or not request_path.is_file():
        raise ValueError("等待工作器归档完整的 done 回执和原始任务。")
    receipt = _read_object(receipt_path)
    request = _read_object(request_path)
    queued_jobs = _inside(board, _worker_path(board, request.get("jobs")))
    jobs_path = queued_jobs if jobs_path is None else _inside(board, board / jobs_path)
    if (
        receipt.get("task") != task
        or receipt.get("ok") is not True
        or receipt.get("returncode") != 0
        or receipt.get("fails") != []
        or receipt.get("runner") != RUNNER
        or request.get("runner") != RUNNER
        or queued_jobs != jobs_path
    ):
        raise ValueError("回执、归档任务和镜头任务文件须对应同一次完整成功的视频生成。")

    receipt_at = receipt_path.stat().st_mtime_ns
    queued_at = request_path.stat().st_mtime_ns
    if queued_at > receipt_at or jobs_path.stat().st_mtime_ns > queued_at:
        raise ValueError("镜头任务文件或队列记录在该次执行后被修改，无法确认来源。")

    spec = _read_object(jobs_path)
    out_dir = _inside(root, _worker_path(board, spec.get("out")))
    jobs = spec.get("jobs")
    if not isinstance(jobs, list) or not jobs:
        raise ValueError("镜头任务文件没有有效的 jobs。")
    outputs = receipt.get("outputs")
    if not isinstance(outputs, list) or not outputs:
        raise ValueError("成功回执未登记视频文件。")
    received = {_inside(root, _worker_path(root, value)) for value in outputs}
    if len(received) != len(outputs):
        raise ValueError("视频回执含有重复产物。")

    expected, shots = {}, {}
    for job in jobs:
        if not isinstance(job, dict):
            raise ValueError("jobs 中的镜头须为 JSON 对象。")
        job_id = _identifier(job.get("id"), 100, "源镜头 ID")
        if not job_id.startswith(shot_prefix):
            raise ValueError(f"{job_id} 与指定镜头前缀不匹配。")
        shot_id = _identifier(job_id.removeprefix(shot_prefix), shot_id_limit, "镜头 ID")
        seeds = job.get("seeds")
        if (
            shot_id.casefold() in shots
            or not isinstance(seeds, list)
            or not 1 <= len(seeds) <= 48
            or any(type(seed) is not int or not 0 <= seed < 2**63 for seed in seeds)
        ):
            raise ValueError(f"{job_id} 的镜头 ID 重复或种子列表无效。")
        shots[shot_id.casefold()] = (shot_id, job)
        for take, seed in enumerate(seeds, 1):
            path = _inside(root, out_dir / f"{job_id}_v{take}.mp4")
            if path in expected:
                raise ValueError("多个候选指向同一个视频文件。")
            expected[path] = (shot_id, take, seed, f"{task}:{job_id}:v{take}")
    if len(expected) > MAX_CANDIDATES:
        raise ValueError(f"单次导入最多支持 {MAX_CANDIDATES} 个视频候选。")
    if received != expected.keys():
        missing = sorted(file.name for file in expected.keys() - received)
        extra = sorted(file.name for file in received - expected.keys())
        raise ValueError(f"回执与完整镜头清单不一致。缺件：{missing}，额外产物：{extra}")

    candidates, snapshots = [], {}
    for path, (shot_id, take, seed, source_id) in expected.items():
        if not path.is_file():
            raise ValueError(f"回执登记的视频不存在：{path.name}")
        before = _snapshot(path)
        if before[2] == 0 or not queued_at <= before[3] <= receipt_at:
            raise ValueError(f"视频为空、早于该任务或在成功回执之后被改动：{path.name}")
        with path.open("rb") as stream:
            sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
        if _snapshot(path) != before:
            raise ValueError(f"读取时视频有变化：{path.name}")
        candidates.append(
            {
                "kind": "video",
                "path": str(path),
                "bytes": before[2],
                "sha256": sha256,
                "shot_id": shot_id,
                "take": take,
                "seed": seed,
                "source_id": source_id,
            }
        )
        snapshots[path] = before
    return list(shots.values()), candidates, snapshots


def _distinct_pairs(pairs):
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError("重拍映射 JSON 含重复键。")
    return result


def _append_retakes(root, args, shots, candidates, snapshots, jobs_by_source):
    if args.retakes is None:
        return
    with args.retakes.open(encoding="utf-8-sig") as stream:
        retakes = json.load(stream, object_pairs_hook=_distinct_pairs)
    if not isinstance(retakes, list) or len(retakes) > MAX_CANDIDATES:
        raise ValueError(f"重拍映射须为数组，最多 {MAX_CANDIDATES} 条回执。")
    baseline_ids = {shot_id for shot_id, _ in shots}
    done = _inside(root, root / "_queue" / "done")
    seen_receipts = {_inside(done, done / args.receipt)}
    for item in retakes:
        if not isinstance(item, dict) or item.keys() != {"receipt", "shots"}:
            raise ValueError("每条重拍映射须包含 receipt 和 shots。")
        if not isinstance(item["receipt"], str) or not item["receipt"]:
            raise ValueError("重拍 receipt 须为 _queue/done 下的回执路径。")
        receipt = _inside(done, done / item["receipt"])
        if receipt in seen_receipts:
            raise ValueError(f"重复导入同一回执：{receipt.name}")
        seen_receipts.add(receipt)
        mapping = item["shots"]
        if (
            not isinstance(mapping, dict)
            or not mapping
            or any(
                not isinstance(target, str) or target not in baseline_ids
                for target in mapping.values()
            )
        ):
            raise ValueError(f"{receipt.name} 的重拍目标须明确指向基准剧集的镜头。")

        retake_shots, additions, files = _read_batch(
            root,
            None,
            receipt,
            "",
            shot_id_limit=100,
        )
        original_jobs = dict(retake_shots)
        if mapping.keys() != original_jobs.keys():
            raise ValueError(f"{receipt.name} 的所有原镜号都须有且仅有一个映射。")
        if len(candidates) + len(additions) > MAX_CANDIDATES:
            raise ValueError(f"合并重拍后最多支持 {MAX_CANDIDATES} 个视频候选。")
        if snapshots.keys() & files.keys():
            raise ValueError(f"{receipt.name} 与已登记候选指向同一个视频文件。")
        for candidate in additions:
            original_shot = candidate["shot_id"]
            source_id = candidate["source_id"]
            if source_id in jobs_by_source:
                raise ValueError(f"{receipt.name} 含已有候选来源标识。")
            jobs_by_source[source_id] = original_jobs[original_shot]
            candidate["shot_id"] = mapping[original_shot]
        candidates.extend(additions)
        snapshots.update(files)


def _read_episode(path):
    if path.suffix.lower() == ".json":
        return _read_object(path)
    if path.suffix.lower() not in {".yaml", ".yml"}:
        raise ValueError("剧集清单须使用 .yaml、.yml 或 .json。")
    try:
        import yaml
    except ImportError as exc:
        raise ValueError("读取 YAML 需要 PyYAML，也可以使用 JSON 剧集清单。") from exc
    try:
        spec = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    except yaml.YAMLError as exc:
        raise ValueError("剧集 YAML 语法有误。") from exc
    if not isinstance(spec, dict):
        raise ValueError("剧集清单须为对象。")
    return spec


def _source_episode(args, root, shots):
    board = _inside(root, root / BOARD)
    unknown = "未录入"
    sections = []
    formats = set()
    for shot_id, job in shots:
        seconds = job.get("seconds")
        if type(seconds) not in {int, float} or not math.isfinite(seconds) or seconds <= 0:
            raise ValueError(f"{shot_id} 缺少有效时长。请提供完整剧集清单。")
        prompt = job.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError(f"{shot_id} 缺少视频提示词。请提供完整剧集清单。")
        negative = job.get("negative", "")
        if not isinstance(negative, str):
            raise ValueError(f"{shot_id} 的负面提示词无效。")
        section = {
            "shot_id": shot_id,
            "seconds": seconds,
            "beat": unknown,
            "emotion": unknown,
            "camera": {"move": unknown, "lens": unknown, "speed": unknown},
            "video": {"prompt": prompt, "negative": negative, "seeds": job["seeds"]},
            "audio": {"vocal_from": "ltx", "foley": []},
            "transition_out": {"type": "cut", "offset_s": 0},
        }
        for source, target in (("first", "first_frame"), ("last", "last_frame")):
            if source in job or source == "first":
                frame = _inside(root, _worker_path(board, job.get(source)))
                if not frame.is_file():
                    raise ValueError(f"{shot_id} 缺少镜头任务中引用的 {source} 帧。")
                section[target] = {"refs": [str(frame.relative_to(root))], "prompt": unknown}
        sections.append(section)
        width, height, fps = job.get("w"), job.get("h"), job.get("fps", 24)
        if (
            type(width) is not int
            or type(height) is not int
            or type(fps) not in {int, float}
            or not math.isfinite(fps)
        ):
            raise ValueError(f"{shot_id} 缺少有效尺寸或帧率。请提供完整剧集清单。")
        formats.add((width, height, fps))
    sizes = {(w, h) for w, h, _ in formats}
    rates = {fps for _, _, fps in formats}
    if (args.edit_size is None and len(sizes) != 1) or (args.edit_fps is None and len(rates) != 1):
        raise ValueError("候选尺寸或帧率不统一，须显式提供合成尺寸或帧率。")
    size = args.edit_size or list(next(iter(sizes)))
    fps = args.edit_fps if args.edit_fps is not None else next(iter(rates))
    if any(not 2 <= v <= 8192 or v % 2 for v in size) or not 0 < fps <= 240:
        raise ValueError("合成尺寸须为合理的偶数，且帧率应在 0–240 之间。")
    if not -70 <= args.loudness_lufs <= -5:
        raise ValueError("合成响度须在 -70 至 -5 LUFS 之间。")
    episode_id = _identifier(args.episode_id, 100, "剧集 ID")
    return {
        "episode_id": episode_id,
        "title": args.title or episode_id,
        "target_seconds": sum(section["seconds"] for section in sections),
        "characters": [],
        "shots": sections,
        "edit": {"size": size, "fps": fps, "loudness_lufs": args.loudness_lufs},
    }


def _thumbnail(path):
    completed = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-protocol_whitelist",
            "file,pipe",
            "-f",
            "mov",
            "-i",
            str(path),
            "-map",
            "0:v:0",
            "-an",
            "-vf",
            "thumbnail=12,scale=320:320:force_original_aspect_ratio=decrease",
            "-frames:v",
            "1",
            "-f",
            "image2pipe",
            "-c:v",
            "mjpeg",
            "pipe:1",
        ],
        capture_output=True,
        timeout=40,
        check=True,
        creationflags=NO_CONSOLE,
    )
    jpeg = completed.stdout
    if not 4 <= len(jpeg) <= MAX_THUMBNAIL_BYTES or not (
        jpeg.startswith(b"\xff\xd8") and jpeg.endswith(b"\xff\xd9")
    ):
        raise ValueError(f"无法从 {path.name} 读取合规的 JPEG 缩略图。")
    return base64.b64encode(jpeg).decode("ascii")


def _technical_qc(path, job):
    try:
        result = subprocess.run(
            probe_command(path, local_mp4=True),
            capture_output=True,
            timeout=25,
            creationflags=NO_CONSOLE,
        )
    except FileNotFoundError as exc:
        raise ValueError("未找到 FFprobe，可关闭技术质检后重试。") from exc
    info = probe_json(result)
    streams = info.get("streams", [])
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), {})
    try:
        seconds = float(info.get("format", {}).get("duration", ""))
        fps = float(Fraction(video.get("avg_frame_rate", "")))
    except (ValueError, ZeroDivisionError) as exc:
        raise ValueError(f"无法从视频读取时长和帧率：{path.name}") from exc
    if not math.isfinite(seconds) or not math.isfinite(fps) or min(seconds, fps) <= 0:
        raise ValueError(f"视频的时长或帧率无法确认：{path.name}")

    width, height = video.get("width"), video.get("height")
    audio = [stream for stream in streams if stream.get("codec_type") == "audio"]
    expected_fps = job.get("fps", 24)
    expected = (job.get("w"), job.get("h"), expected_fps, job.get("seconds"))
    if any(
        type(value) not in {int, float} or not math.isfinite(value) or value <= 0
        for value in expected
    ):
        raise ValueError(f"原任务缺少明确的尺寸、帧率或时长：{path.name}")
    differences = []
    if (width, height) != expected[:2]:
        differences.append("尺寸与原任务不同")
    if abs(fps - expected_fps) > 0.05:
        differences.append("帧率与原任务不同")
    if abs(seconds - expected[3]) > 8.0 / expected_fps + 0.01:
        differences.append("时长超出 LTX 八帧取整的容差")
    if not audio:
        differences.append("未发现 LTX 音轨")
    return {
        "检查": "FFprobe 技术元数据",
        "结果": "需复核" if differences else "符合任务元数据",
        "实测": {
            "秒": round(seconds, 4),
            "尺寸": [width, height],
            "帧率": round(fps, 3),
            "音轨数": len(audio),
            "视频编码": video.get("codec_name"),
        },
        "任务": {"秒": expected[3], "尺寸": list(expected[:2]), "帧率": expected_fps},
        "差异": differences,
        "导演审片": "待人工判断表演、连续性与声音内容。",
    }


def build_import(args):
    root = args.project_root.resolve(strict=True)
    shots, candidates, snapshots = _read_batch(root, args.jobs, args.receipt, args.shot_prefix)
    base_jobs = dict(shots)
    jobs_by_source = {record["source_id"]: base_jobs[record["shot_id"]] for record in candidates}
    _append_retakes(root, args, shots, candidates, snapshots, jobs_by_source)
    if args.episode:
        episode = _read_episode(args.episode)
        _identifier(episode.get("episode_id"), 100, "剧集 ID")
        episode_shots = episode.get("shots")
        if not isinstance(episode_shots, list):
            raise ValueError("剧集清单中的 shots 须为镜头数组。")
        described = {
            _identifier(item.get("shot_id"), 80, "镜头 ID")
            for item in episode_shots
            if isinstance(item, dict)
        }
        if not all(shot_id in described for shot_id, _ in shots):
            raise ValueError("回执中的镜头未全部出现在指定剧集清单中。")
    else:
        episode = _source_episode(args, root, shots)
    if args.thumbnails:
        if not shutil.which("ffmpeg"):
            raise ValueError("未找到 FFmpeg，可关闭缩略图后重试。")
        for record in candidates:
            record["jpeg_base64"] = _thumbnail(Path(record["path"]))
    if args.probe:
        for record in candidates:
            record["qc"] = _technical_qc(Path(record["path"]), jobs_by_source[record["source_id"]])
    if any(_snapshot(path) != snapshot for path, snapshot in snapshots.items()):
        raise ValueError("准备导入期间视频有变化，请重新核对回执。")
    return {
        "episode": episode,
        "episode_metadata_complete": bool(args.episode),
        "candidates": candidates,
    }


def _core_url(config):
    if config:
        with config.open("rb") as handle:
            url = tomllib.load(handle).get("mac_core_url", "")
    else:
        url = os.environ.get("PICOTOO_MAC_CORE_URL", "")
    if not isinstance(url, str):
        raise ValueError("Mac Core 地址配置无效。")
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("请通过 --config 或 PICOTOO_MAC_CORE_URL 配置 Mac Core 根地址。")
    return url.rstrip("/") + "/api/v1/episodes/import"


def _apply(payload, config):
    try:
        import requests
    except ImportError as exc:
        raise ValueError("提交需要 requests，请先安装。") from exc
    endpoint = _core_url(config)
    token = os.environ.get("PICOTOO_EXECUTOR_TOKEN")
    if not token:
        raise ValueError("请设置 Windows 执行桥环境变量 PICOTOO_EXECUTOR_TOKEN。")
    retry_status = {408, 425, 429, 502, 503, 504}
    with requests.Session() as http:
        http.trust_env = False
        for attempt in range(3):
            try:
                response = http.post(
                    endpoint,
                    headers={"Authorization": f"Bearer {token}"},
                    json=payload,
                    allow_redirects=False,
                    timeout=(5, 45),
                )
            except (requests.Timeout, requests.ConnectionError):
                pass
            else:
                if response.status_code in {200, 201}:
                    reply = response.json()
                    if isinstance(reply, dict):
                        inserted = reply.get("inserted_count")
                        existing = reply.get("existing_count")
                        updated = reply.get("updated_count", 0)
                        conflicts = reply.get("conflict_count", 0)
                        if (
                            reply.get("episode_id") == payload["episode"]["episode_id"]
                            and type(inserted) is int
                            and type(existing) is int
                            and min(inserted, existing) >= 0
                            and inserted + existing == len(payload["candidates"])
                            and type(updated) is int
                            and type(conflicts) is int
                            and min(updated, conflicts) >= 0
                            and updated <= existing
                            and updated + conflicts <= len(payload["candidates"])
                            and response.status_code == (201 if inserted else 200)
                        ):
                            return reply
                    raise ValueError("Mac Core 的确认回执与导入批次不匹配，可重跑相同命令。")
                if response.status_code not in retry_status:
                    raise ValueError(f"Mac Core 拒绝导入（HTTP {response.status_code}）。")
            if attempt < 2:
                time.sleep(1 << attempt)
    raise ValueError("未收到 Mac Core 成功回执。连接恢复后可以重跑相同命令。")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--jobs", type=Path, help="核对任务文件，默认读取归档任务中的路径")
    parser.add_argument("--receipt", type=Path, required=True, help="相对于 _queue/done 的回执")
    parser.add_argument("--shot-prefix", default="", help="可选的源镜头 ID 前缀，例如 V2_")
    parser.add_argument("--retakes", type=Path, help="显式重拍回执和镜号的 JSON 映射")
    episode = parser.add_mutually_exclusive_group(required=True)
    episode.add_argument("--episode", type=Path, help="现有完整剧集 YAML 或 JSON")
    episode.add_argument("--episode-id", help="根据回执中的镜序和时长建立待补全的剧集条目")
    parser.add_argument("--title", help="没有完整剧集清单时使用的标题")
    parser.add_argument("--edit-size", type=int, nargs=2, metavar=("WIDTH", "HEIGHT"))
    parser.add_argument("--edit-fps", type=float)
    parser.add_argument("--loudness-lufs", type=float, default=-14)
    parser.add_argument("--thumbnails", action="store_true", help="通过本机 FFmpeg 提取预览 JPEG")
    parser.add_argument("--probe", action="store_true", help="用本机 FFprobe 核对候选技术元数据")
    output = parser.add_mutually_exclusive_group()
    output.add_argument("--apply", action="store_true", help="显式提交给 Mac Core，默认仅检查")
    output.add_argument("--emit-manifest", action="store_true", help="向 stdout 输出导入清单")
    output.add_argument("--review-page", type=Path, help="生成本地离线审片页")
    parser.add_argument("--cut-plan", type=Path, help="仅离线页，按剪辑清单标出使用的源文件")
    parser.add_argument("--cut-video", type=Path, help="仅离线页，可在本机打开的粗剪视频")
    parser.add_argument("--decisions", type=Path, help="合并离线审片选择文件")
    parser.add_argument("--config", type=Path, help="从 Windows 执行桥 TOML 读取 Mac Core 地址")
    args = parser.parse_args(argv)
    if (args.cut_plan or args.cut_video) and not args.review_page:
        parser.error("--cut-plan 和 --cut-video 需要 --review-page。")
    try:
        payload = build_import(args)
        if args.decisions or args.review_page:
            if __package__:
                from .review_board import apply_decisions, write_review_page
            else:
                from review_board import apply_decisions, write_review_page

            if args.decisions:
                apply_decisions(payload, args.decisions)
                payload["fill_unreviewed"] = True
        if args.apply:
            result = _apply(payload, args.config)
        elif args.emit_manifest:
            result = payload
        elif args.review_page:
            write_review_page(
                payload, args.review_page, project_root=args.project_root,
                cut_plan=args.cut_plan, cut_video=args.cut_video,
            )
            result = {"mode": "review-page", "path": str(args.review_page.resolve())}
        else:
            result = {
                "mode": "dry-run",
                "episode_id": payload["episode"]["episode_id"],
                "episode_metadata_complete": payload["episode_metadata_complete"],
                "candidates": [
                    {key: value for key, value in item.items() if key != "jpeg_base64"}
                    for item in payload["candidates"]
                ],
            }
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"导入失败：{exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
