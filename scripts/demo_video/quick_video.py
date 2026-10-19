"""Quick demo: one selected project note -> local Ollama script -> local ComfyUI WebM.

This is an independent demonstration, not a formally released Goal Center final MP4.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any
from uuid import uuid4

MODEL_ID = "gpt-oss:20b"
OLLAMA_URL = "http://127.0.0.1:11434"
COMFY_URL = "http://127.0.0.1:8188"
WORKFLOW_REL = "windows/production/workflows/wan22-ti2v5b-t2v-api-v1.json"
CLASSES = {"UNETLoader", "CLIPLoader", "VAELoader", "ModelSamplingSD3", "CLIPTextEncode",
           "Wan22ImageToVideoLatent", "KSampler", "VAEDecode", "SaveWEBM"}


class DemoError(RuntimeError):
    """User-actionable closed failure; no silent fallback."""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _http_json(url: str, payload: dict | None = None, *, timeout: int = 30) -> dict:
    # Endpoint authority remains on the fixed loopback services.
    if not (url.startswith(OLLAMA_URL + "/") or url.startswith(COMFY_URL + "/")):
        raise DemoError("DEMO_REMOTE_ENDPOINT_FORBIDDEN")
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST" if body else "GET",
                                     headers={"Content-Type": "application/json"} if body else {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read(16 * 1024 * 1024 + 1)
    except (OSError, TimeoutError) as error:
        raise DemoError(f"DEMO_LOCAL_API_UNAVAILABLE:{type(error).__name__}") from error
    if len(data) > 16 * 1024 * 1024:
        raise DemoError("DEMO_API_RESPONSE_TOO_LARGE")
    try:
        result = json.loads(data)
    except ValueError as error:
        raise DemoError("DEMO_API_JSON_INVALID") from error
    if not isinstance(result, dict):
        raise DemoError("DEMO_API_ROOT_INVALID")
    return result


def _text(value: Any, name: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise DemoError(f"DEMO_SCRIPT_FIELD_INVALID:{name}")
    return value.strip()


def prepare(facts_path: Path, out_dir: Path) -> Path:
    """Mac-side selected project note -> portable AI script; does not scan other files."""
    if not facts_path.is_file() or facts_path.is_symlink():
        raise DemoError("DEMO_SOURCE_NOT_FOUND_OR_LINK")
    raw = facts_path.read_bytes()
    if not 12 <= len(raw) <= 16_384:
        raise DemoError("DEMO_SOURCE_SIZE_INVALID")
    facts = raw.decode("utf-8")
    system = (
        "你是 PicotooPet 视频创意助手。只依据用户项目资料制作一段约两秒的概念演示镜头。"
        "不捏造现有功能、成品或数字。只返回 JSON 对象，字段为 title、voiceover、"
        "on_screen_text、positive_prompt，必须都是非空字符串。voiceover 和文字为中文草稿；"
        "positive_prompt 是英文具体的 Wan2.2 单镜头画面描述，有自然运动，"
        "不生成可读文字、UI截图、真实人员身份或 logo。"
    )
    answer = _http_json(OLLAMA_URL + "/api/chat", {
        "model": MODEL_ID, "stream": False, "format": "json",
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": facts}],
        "options": {"temperature": 0.3},
    }, timeout=240)
    try:
        script = json.loads(answer["message"]["content"])
    except (KeyError, ValueError, TypeError) as error:
        raise DemoError("DEMO_AI_SCRIPT_JSON_INVALID") from error
    if not isinstance(script, dict):
        raise DemoError("DEMO_AI_SCRIPT_JSON_INVALID")
    title = _text(script.get("title"), "title", 120)
    voice = _text(script.get("voiceover"), "voiceover", 500)
    onscreen = _text(script.get("on_screen_text"), "on_screen_text", 160)
    prompt = _text(script.get("positive_prompt"), "positive_prompt", 1300)
    package = {
        "schema_version": "demo.video.1", "source_kind": "explicit_local_file",
        "source_sha256": _sha(raw), "ai_model": MODEL_ID, "title": title,
        "shot": {
            "shot_id": "demo-shot-001", "order": 1,
            "voiceover": voice, "on_screen_text": onscreen, "positive_prompt": prompt,
            "workflow_id": "comfy.wan22.ti2v5b.t2v.v1", "width": 832,
            "height": 480, "frame_count": 49, "fps": 24,
            "seed": int(_sha((facts + prompt).encode("utf-8"))[:12], 16),
        },
        "scope": "one silent two-second video; voiceover and text are draft-only",
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "demo-package.json"
    if target.is_symlink():
        raise DemoError("DEMO_OUTPUT_SYMLINK_FORBIDDEN")
    target.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    print(f"AI_SCRIPT_READY={target}")
    return target


def _load_package(path: Path) -> dict:
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 1_000_000:
        raise DemoError("DEMO_PACKAGE_NOT_FOUND_OR_INVALID")
    try:
        package = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError) as error:
        raise DemoError("DEMO_PACKAGE_JSON_INVALID") from error
    if not isinstance(package, dict) or package.get("schema_version") != "demo.video.1":
        raise DemoError("DEMO_PACKAGE_SCHEMA_INVALID")
    shot = package.get("shot")
    if not isinstance(shot, dict) or shot.get("workflow_id") != "comfy.wan22.ti2v5b.t2v.v1":
        raise DemoError("DEMO_WORKFLOW_FORBIDDEN")
    for key, expected in {"width": 832, "height": 480, "frame_count": 49, "fps": 24}.items():
        if type(shot.get(key)) is not int or shot[key] != expected:
            raise DemoError(f"DEMO_PROFILE_INVALID:{key}")
    if type(shot.get("seed")) is not int or not 0 <= shot["seed"] < (1 << 63):
        raise DemoError("DEMO_SEED_INVALID")
    _text(shot.get("positive_prompt"), "positive_prompt", 1300)
    if not isinstance(package.get("source_sha256"), str) or not re.fullmatch(
        r"[0-9a-f]{64}", package["source_sha256"]
    ):
        raise DemoError("DEMO_SOURCE_SHA_INVALID")
    return package


def build_graph(package: dict, repo_root: Path, prefix: str) -> dict:
    """Bind only the seven allowlisted inputs on the repository's frozen workflow."""
    if not re.fullmatch(r"picotoo_demo_[a-f0-9]{12}", prefix):
        raise DemoError("DEMO_OUTPUT_PREFIX_INVALID")
    graph = json.loads((repo_root / WORKFLOW_REL).read_text(encoding="utf-8"))
    if (set(graph) != {str(i) for i in range(1, 11)}
            or {node["class_type"] for node in graph.values()} != CLASSES):
        raise DemoError("DEMO_TEMPLATE_CHANGED")
    for node, key, name in [
        ("1", "unet_name", "wan2.2_ti2v_5B_fp16.safetensors"),
        ("2", "clip_name", "umt5_xxl_fp8_e4m3fn_scaled.safetensors"),
        ("3", "vae_name", "wan2.2_vae.safetensors"),
    ]:
        if graph[node]["inputs"].get(key) != name:
            raise DemoError("DEMO_MODEL_TEMPLATE_CHANGED")
    shot = package["shot"]
    for node, name, placeholder, value in [
        ("5", "text", "__PICOTOO_POSITIVE_PROMPT__", shot["positive_prompt"]),
        ("8", "seed", "__PICOTOO_SEED__", shot["seed"]),
        ("7", "width", "__PICOTOO_WIDTH__", shot["width"]),
        ("7", "height", "__PICOTOO_HEIGHT__", shot["height"]),
        ("7", "length", "__PICOTOO_LENGTH__", shot["frame_count"]),
        ("10", "fps", "__PICOTOO_FPS__", shot["fps"]),
        ("10", "filename_prefix", "__PICOTOO_FILENAME_PREFIX__", prefix),
    ]:
        if graph[node]["inputs"].get(name) != placeholder:
            raise DemoError(f"DEMO_TEMPLATE_SLOT_CHANGED:{node}.{name}")
        graph[node]["inputs"][name] = value
    return graph


def render(package_path: Path, out_dir: Path, *, timeout_seconds: int = 1800,
           repo_root: Path | None = None) -> Path:
    """Windows-side ComfyUI submit / exact prompt polling / safe WebM retrieval."""
    if not 30 <= timeout_seconds <= 7200:
        raise DemoError("DEMO_TIMEOUT_INVALID")
    package = _load_package(package_path)
    root = repo_root or Path(__file__).resolve().parents[2]
    prefix = "picotoo_demo_" + uuid4().hex[:12]
    graph = build_graph(package, root, prefix)
    info = _http_json(COMFY_URL + "/object_info")
    missing = CLASSES - info.keys()
    if missing:
        raise DemoError("DEMO_COMFY_NODES_MISSING:" + ",".join(sorted(missing)))
    for node, key, name in [
        ("UNETLoader", "unet_name", "wan2.2_ti2v_5B_fp16.safetensors"),
        ("CLIPLoader", "clip_name", "umt5_xxl_fp8_e4m3fn_scaled.safetensors"),
        ("VAELoader", "vae_name", "wan2.2_vae.safetensors"),
    ]:
        try:
            options = info[node]["input"]["required"][key][0]
        except (KeyError, TypeError, IndexError):
            raise DemoError(f"DEMO_COMFY_MODEL_OPTIONS_UNKNOWN:{node}") from None
        if name not in options:
            raise DemoError(f"DEMO_COMFY_MODEL_MISSING:{name}")
    response = _http_json(COMFY_URL + "/prompt", {
        "prompt": graph, "client_id": str(uuid4()),
    })
    prompt_id = response.get("prompt_id")
    if not isinstance(prompt_id, str) or not re.fullmatch(r"[0-9a-fA-F-]{8,80}", prompt_id):
        raise DemoError("DEMO_COMFY_PROMPT_ID_INVALID")
    print(f"COMFY_PROMPT_ID={prompt_id}")
    deadline = time.monotonic() + timeout_seconds
    finished = None
    while time.monotonic() < deadline:
        entry = _http_json(COMFY_URL + "/history/" + prompt_id).get(prompt_id)
        if isinstance(entry, dict):
            status = entry.get("status") or {}
            if status.get("status_str") == "error":
                raise DemoError("DEMO_COMFY_RENDER_FAILED")
            if entry.get("outputs"):
                finished = entry
                break
        time.sleep(2)
    if finished is None:
        raise DemoError("DEMO_COMFY_RENDER_TIMEOUT")
    output = finished.get("outputs", {}).get("10", {})
    files = output.get("gifs") or output.get("videos") or []
    if not isinstance(files, list) or len(files) != 1 or not isinstance(files[0], dict):
        raise DemoError("DEMO_COMFY_EXACT_VIDEO_MISSING")
    item = files[0]
    filename = item.get("filename")
    if (not isinstance(filename, str)
            or not re.fullmatch(r"[A-Za-z0-9_.-]{1,150}\.webm", filename)
            or not filename.startswith(prefix)
            or item.get("type") != "output"
            or item.get("subfolder", "") not in ("", ".")):
        raise DemoError("DEMO_COMFY_OUTPUT_PATH_INVALID")
    out_dir.mkdir(parents=True, exist_ok=True)
    video = out_dir / "first-video.webm"
    if video.exists() or video.is_symlink():
        raise DemoError("DEMO_VIDEO_WONT_OVERWRITE")
    query = urllib.parse.urlencode({"filename": filename, "type": "output", "subfolder": ""})
    try:
        with urllib.request.urlopen(COMFY_URL + "/view?" + query, timeout=120) as source:
            digest = hashlib.sha256()
            size = 0
            with video.open("wb") as destination:
                while chunk := source.read(1024 * 1024):
                    size += len(chunk)
                    if size > 512 * 1024 * 1024:
                        raise DemoError("DEMO_VIDEO_TOO_LARGE")
                    digest.update(chunk)
                    destination.write(chunk)
    except BaseException:
        video.unlink(missing_ok=True)
        raise
    if video.read_bytes()[:4] != bytes.fromhex("1a45dfa3"):
        video.unlink(missing_ok=True)
        raise DemoError("DEMO_OUTPUT_NOT_WEBM")
    receipt = {
        "schema_version": "demo.receipt.1", "prompt_id": prompt_id,
        "source_sha256": package["source_sha256"], "sha256": digest.hexdigest(),
        "bytes": size, "filename": video.name, "scope": "local silent WebM demo",
    }
    (out_dir / "demo-receipt.json").write_text(
        json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(f"FIRST_VIDEO_READY={video}")
    print(f"FIRST_VIDEO_SHA256={digest.hexdigest()}")
    return video


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare", help="Mac: selected note -> local AI script")
    prep.add_argument("--facts", required=True, type=Path)
    prep.add_argument("--out", type=Path, default=Path("video-demo"))
    rend = sub.add_parser("render", help="Windows: handoff -> local ComfyUI WebM")
    rend.add_argument("--package", required=True, type=Path)
    rend.add_argument("--out", type=Path, default=Path("video-demo"))
    rend.add_argument("--timeout-seconds", type=int, default=1800)
    both = sub.add_parser("all", help="Single host with both local Ollama and ComfyUI")
    both.add_argument("--facts", required=True, type=Path)
    both.add_argument("--out", type=Path, default=Path("video-demo"))
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            prepare(args.facts, args.out)
        elif args.command == "render":
            render(args.package, args.out, timeout_seconds=args.timeout_seconds)
        else:
            package = prepare(args.facts, args.out)
            render(package, args.out)
        return 0
    except (DemoError, OSError, ValueError, UnicodeError) as error:
        print(f"DEMO_FAILED={error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
