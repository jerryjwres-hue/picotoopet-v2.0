"""Build a private offline screening page and bind its notes to original candidates."""

import hashlib
import json
import os
import tempfile
from pathlib import Path, PureWindowsPath


def _identity(row):
    return row["shot_id"], row["take"], row["sha256"], row.get("source_id")


def _local_video_uri(value):
    win = PureWindowsPath(value)
    path = win if win.drive else Path(value)
    if (
        not path.is_absolute()
        or value.startswith(("//", "\\\\"))
        or path.suffix.lower() not in {".mp4", ".mov", ".m4v", ".webm", ".mkv"}
    ):
        raise ValueError("只能打开本机的绝对视频路径。")
    return path.as_uri()


def apply_decisions(manifest, path):
    path = Path(path)
    if path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError("审片记录超过 4 MiB。")
    record = json.loads(path.read_text(encoding="utf-8-sig"))
    if (
        not isinstance(record, dict)
        or type(record.get("version")) is not int
        or record["version"] != 1
        or record.get("episode_id") != manifest["episode"]["episode_id"]
        or not isinstance(record.get("decisions"), list)
    ):
        raise ValueError("审片记录的版本、剧集或决定列表不匹配。")
    index = {_identity(c): c for c in manifest["candidates"] if c["kind"] == "video"}
    seen = set()
    picks = set()
    updates = []
    for row in record["decisions"]:
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("shot_id"), str)
            or type(row.get("take")) is not int
            or not isinstance(row.get("sha256"), str)
            or not isinstance(row.get("source_id"), (str, type(None)))
        ):
            raise ValueError("候选记录缺少镜号、条次、来源或文件指纹。")
        key = _identity(row)
        if key not in index or key in seen:
            raise ValueError(f"{key[0]} 第 {key[1]} 条的来源或指纹不匹配，或被重复记录。")
        seen.add(key)
        decision, note = row.get("decision"), row.get("note")
        if (
            decision not in (None, "pick", "reject")
            or not isinstance(note, str)
            or len(note) > 2000
        ):
            raise ValueError("决定或备注无效。")
        if decision == "pick":
            if key[0] in picks:
                raise ValueError(f"{key[0]} 有多条选用视频。")
            picks.add(key[0])
        updates.append((index[key], decision, note))
    for candidate, decision, note in updates:
        candidate.update(decision=decision, note=note)


def _from_project(root, path):
    local = (root / path).resolve()
    if not local.is_relative_to(root):
        raise ValueError("剪辑参考路径超出本机项目目录。")
    return local


def _cut_sources(project_root, plan_path):
    plan = _from_project(project_root, plan_path)
    if plan.stat().st_size > 4 * 1024 * 1024:
        raise ValueError("剪辑清单超过 4 MiB。")
    data = json.loads(plan.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict) or not isinstance(data.get("shots"), list):
        raise ValueError("剪辑清单须有 shots 数组。")
    clips = set()
    for shot in data["shots"]:
        value = shot.get("video") if isinstance(shot, dict) else None
        if not isinstance(value, str) or not value or PureWindowsPath(value).anchor:
            raise ValueError("每个剪辑片段须含项目相对路径 video。")
        clips.add(_from_project(project_root, value.replace("\\", "/")))
    return clips


def write_review_page(manifest, path, *, project_root=None, cut_plan=None, cut_video=None):
    path = Path(path)
    if path.suffix.lower() != ".html":
        raise ValueError("审片页文件须使用 .html 后缀。")
    episode = manifest["episode"]
    root = Path(project_root).resolve() if project_root is not None else None
    if (cut_plan or cut_video) and root is None:
        raise ValueError("剪辑参考需要本机项目根目录。")
    cut_sources = _cut_sources(root, cut_plan) if cut_plan else set()
    cut_uri = None
    if cut_video:
        cut_file = _from_project(root, cut_video)
        if not cut_file.is_file():
            raise ValueError("找不到指定的粗剪视频。")
        cut_uri = _local_video_uri(str(cut_file))
    candidates = []
    for candidate in manifest["candidates"]:
        if candidate["kind"] != "video":
            continue
        item = {
            k: candidate.get(k)
            for k in (
                "shot_id",
                "take",
                "sha256",
                "source_id",
                "seed",
                "decision",
                "note",
            )
        }
        item["uri"] = _local_video_uri(candidate["path"])
        if "decision" in candidate or "note" in candidate:
            entry = json.dumps([item["decision"], item["note"]], ensure_ascii=True)
            item["import_revision"] = hashlib.sha256(entry.encode("ascii")).hexdigest()
        if item["seed"] is not None:
            item["seed"] = str(item["seed"])
        item["in_cut"] = Path(candidate["path"]).resolve() in cut_sources
        item["fps"] = candidate.get("qc", {}).get("实测", {}).get("帧率") or episode["edit"]["fps"]
        candidates.append(item)
    if not candidates:
        raise ValueError("清单中没有视频。")
    batch = json.dumps([_identity(c) for c in candidates], ensure_ascii=True)
    page_data = {
        "episode_id": episode["episode_id"],
        "title": episode["title"],
        "fps": episode["edit"]["fps"],
        "shots": [s["shot_id"] for s in episode["shots"]],
        "candidates": candidates,
        "batch": hashlib.sha256(batch.encode("ascii")).hexdigest(),
        "cut_uri": cut_uri,
    }
    template = Path(__file__).with_name("review_board.html").read_text(encoding="utf-8")
    data = json.dumps(page_data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    html = template.replace("<!--BATCH_JSON-->", data)
    with tempfile.NamedTemporaryFile(
        dir=path.parent, prefix=".review-", suffix=".tmp", delete=False
    ) as out:
        tmp = Path(out.name)
    try:
        tmp.write_text(html, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
