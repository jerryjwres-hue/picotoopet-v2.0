from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any


_TOOL_DIRECTORY = str(Path(__file__).resolve().parent)
if _TOOL_DIRECTORY not in sys.path:
    sys.path.insert(0, _TOOL_DIRECTORY)

from maotai_manifest_contract import parse_manifest  # noqa: E402
from maotai_png_validation import validate_structural_art_quality  # noqa: E402
from validate_maotai_v2_assets import (  # noqa: E402
    stage_asset_directory,
    validate_asset_directory,
)


_REQUIRED_BINDINGS = (
    "positive",
    "negative",
    "width",
    "height",
    "seed",
    "filename_prefix",
)
_REQUIRED_AUTO_TITLES = (
    "MAOTAI_SAMPLER",
    "MAOTAI_CANVAS",
    "MAOTAI_POSITIVE",
    "MAOTAI_NEGATIVE",
    "MAOTAI_SAVE",
)
_OPTIONAL_AUTO_TITLES = (
    "MAOTAI_REFERENCE",
    "MAOTAI_RMBG",
)
_LOOPBACK_HOSTS              = {"127.0.0.1", "localhost", "::1"}
_PNG_SIGNATURE               = b"\x89PNG\r\n\x1a\n"
_DEFAULT_REFERENCE_SUBFOLDER = "maotai-v2-references"
_DEFAULT_MAX_REFERENCE_BYTES = 32 * 1024 * 1024
_MAX_ZIP_COMPRESSION_RATIO   = 200.0


def normalize_server_url(server_url: str) -> str:
    """只接受本机 HTTP ComfyUI；生产工具永远不把工作流发送到局域网或公网。"""
    parsed = urllib.parse.urlparse(server_url)
    if parsed.scheme.lower() != "http":
        raise ValueError("ComfyUI server must use local http loopback access")
    if parsed.hostname is None or parsed.hostname.lower() not in _LOOPBACK_HOSTS:
        raise ValueError("ComfyUI server must be a local loopback host")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("ComfyUI loopback URL must not contain credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("ComfyUI loopback URL must not contain query or fragment")
    if parsed.path not in ("", "/"):
        raise ValueError("ComfyUI loopback URL must not contain a base path")
    return server_url.rstrip("/")


def load_bindings(path: Path | str) -> dict[str, Any]:
    """读取显式 node/input 绑定；显式文件用于兼容旧工作流或非标准节点标题。"""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("ComfyUI bindings JSON must be an object")
    _validate_required_bindings(payload)
    return payload


def build_bindings_from_workflow(workflow: dict[str, Any]) -> dict[str, Any]:
    """按固定 MAOTAI_* 节点标题自动绑定 API workflow，避免用户手工查询 ComfyUI node ID。"""
    title_to_node: dict[str, tuple[str, dict[str, Any]]] = {}
    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            continue
        metadata = node.get("_meta")
        title    = metadata.get("title") if isinstance(metadata, dict) else None
        if not isinstance(title, str) or title not in (*_REQUIRED_AUTO_TITLES, *_OPTIONAL_AUTO_TITLES):
            continue
        if title in title_to_node:
            raise ValueError(f"duplicate ComfyUI auto-bind title: {title}")
        title_to_node[title] = (str(node_id), node)

    missing_titles = [title for title in _REQUIRED_AUTO_TITLES if title not in title_to_node]
    if missing_titles:
        raise ValueError("missing required ComfyUI auto-bind title(s): " + ", ".join(missing_titles))

    sampler_id, sampler_node   = title_to_node["MAOTAI_SAMPLER"]
    canvas_id, canvas_node     = title_to_node["MAOTAI_CANVAS"]
    positive_id, positive_node = title_to_node["MAOTAI_POSITIVE"]
    negative_id, negative_node = title_to_node["MAOTAI_NEGATIVE"]
    save_id, save_node         = title_to_node["MAOTAI_SAVE"]

    _require_node_input(workflow, sampler_id, "seed", "MAOTAI_SAMPLER")
    _require_node_input(workflow, canvas_id, "width", "MAOTAI_CANVAS")
    _require_node_input(workflow, canvas_id, "height", "MAOTAI_CANVAS")
    _require_node_input(workflow, positive_id, "text", "MAOTAI_POSITIVE")
    _require_node_input(workflow, negative_id, "text", "MAOTAI_NEGATIVE")
    _require_node_input(workflow, save_id, "filename_prefix", "MAOTAI_SAVE")

    bindings: dict[str, Any] = {
        "positive": {"node": positive_id, "input": "text"},
        "negative": {"node": negative_id, "input": "text"},
        "width": {"node": canvas_id, "input": "width"},
        "height": {"node": canvas_id, "input": "height"},
        "seed": {"node": sampler_id, "input": "seed"},
        "filename_prefix": {"node": save_id, "input": "filename_prefix"},
    }

    reference = title_to_node.get("MAOTAI_REFERENCE")
    if reference is not None:
        reference_id, _ = reference
        _require_node_input(workflow, reference_id, "image", "MAOTAI_REFERENCE")
        bindings["reference_image"] = {"node": reference_id, "input": "image"}

    rmbg = title_to_node.get("MAOTAI_RMBG")
    if rmbg is not None:
        rmbg_id, _ = rmbg
        bindings["rmbg"] = {
            "node": rmbg_id,
            "background_input": "background",
            "model_input": "model",
            "model": "BiRefNet-general",
        }

    _validate_required_bindings(bindings)
    return bindings


def workflow_upstream_node_ids(
    workflow: dict[str, Any],
    start_node_id: str,
) -> set[str]:
    """沿 ComfyUI API 的 [node_id, output_index] 连接反向遍历，并拒绝悬空依赖。"""
    start = str(start_node_id)
    if start not in workflow:
        raise ValueError(f"ComfyUI workflow start node is missing: {start}")

    visited: set[str] = set()
    pending           = [start]
    while pending:
        node_id = pending.pop()
        if node_id in visited:
            continue
        node = workflow.get(node_id)
        if not isinstance(node, dict):
            raise ValueError(f"ComfyUI workflow node is invalid: {node_id}")
        visited.add(node_id)

        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        for value in inputs.values():
            linked_node = _linked_node_id(value)
            if linked_node is None:
                continue
            if linked_node not in workflow:
                raise ValueError(
                    f"ComfyUI workflow contains dangling link: {node_id} -> {linked_node}"
                )
            if linked_node not in visited:
                pending.append(linked_node)

    visited.discard(start)
    return visited


def validate_maotai_workflow_graph(
    workflow: dict[str, Any],
    bindings: dict[str, Any],
) -> None:
    """确认保存路径真正消费参考图、提示、采样、画布和 RMBG，而不只存在同名孤岛节点。"""
    _validate_required_bindings(bindings)
    save_binding = bindings["filename_prefix"]
    save_node_id = str(save_binding["node"])
    upstream     = workflow_upstream_node_ids(workflow, save_node_id)

    for binding_name in ("positive", "negative", "width", "height", "seed"):
        node_id = str(bindings[binding_name]["node"])
        if node_id not in upstream:
            raise ValueError(
                f"ComfyUI {binding_name} binding node is not upstream of MAOTAI_SAVE: {node_id}"
            )

    reference = bindings.get("reference_image")
    if isinstance(reference, dict):
        node_id = str(reference.get("node", ""))
        if not node_id or node_id not in upstream:
            raise ValueError(
                f"ComfyUI MAOTAI_REFERENCE node is not upstream of MAOTAI_SAVE: {node_id}"
            )

    rmbg = bindings.get("rmbg")
    if isinstance(rmbg, dict):
        node_id = str(rmbg.get("node", ""))
        if not node_id or node_id not in upstream:
            raise ValueError(
                f"ComfyUI MAOTAI_RMBG node is not upstream of MAOTAI_SAVE: {node_id}"
            )


def validate_comfyui_workflow_node_types(
    object_info: dict[str, Any],
    workflow: dict[str, Any],
) -> None:
    """在上传参考图或排队 prompt 前确认 workflow 的所有 node class 已在当前 ComfyUI 注册。"""
    if not isinstance(object_info, dict):
        raise ValueError("ComfyUI object_info response must be an object")

    missing: list[str] = []
    for node in workflow.values():
        if not isinstance(node, dict):
            continue
        class_type = node.get("class_type")
        if isinstance(class_type, str) and class_type not in object_info:
            missing.append(class_type)

    if missing:
        raise ValueError(
            "ComfyUI workflow references unregistered node class(es): "
            + ", ".join(sorted(set(missing)))
        )


def apply_job_to_workflow(
    workflow: dict[str, Any],
    bindings: dict[str, Any],
    job: dict[str, Any],
    *,
    seed: int,
    filename_prefix: str,
    reference_inputs: dict[str, str] | None = None,
) -> dict[str, Any]:
    """把单个 manifest job 注入 workflow；每个 job 只产生一个目标部件。"""
    _validate_required_bindings(bindings)
    rendered = copy.deepcopy(workflow)

    output = job.get("output")
    if not isinstance(output, dict):
        raise ValueError("art job output must be an object")
    width  = output.get("width_px")
    height = output.get("height_px")
    if not isinstance(width, int) or width <= 0:
        raise ValueError("art job output width_px must be a positive integer")
    if not isinstance(height, int) or height <= 0:
        raise ValueError("art job output height_px must be a positive integer")

    positive = job.get("positive_prompt")
    negative = job.get("negative_prompt")
    if not isinstance(positive, str) or not positive:
        raise ValueError("art job positive_prompt must be a non-empty string")
    if not isinstance(negative, str) or not negative:
        raise ValueError("art job negative_prompt must be a non-empty string")

    _set_binding(rendered, bindings["positive"], positive, "positive")
    _set_binding(rendered, bindings["negative"], negative, "negative")
    _set_binding(rendered, bindings["width"], width, "width")
    _set_binding(rendered, bindings["height"], height, "height")
    _set_binding(rendered, bindings["seed"], seed, "seed")
    _set_binding(rendered, bindings["filename_prefix"], filename_prefix, "filename_prefix")

    reference_binding = bindings.get("reference_image")
    if isinstance(reference_binding, dict):
        reference = job.get("primary_reference")
        if not isinstance(reference, str) or not reference:
            raise ValueError("art job primary_reference is missing")
        if reference_inputs is None or reference not in reference_inputs:
            raise ValueError(f"reference input was not uploaded before prompt queue: {reference}")
        _set_binding(
            rendered,
            reference_binding,
            reference_inputs[reference],
            "reference_image",
        )

    if "rmbg" in bindings:
        _apply_rmbg_binding(rendered, bindings["rmbg"])
    return rendered


def deterministic_seed(base_seed: int, seed_family: str) -> int:
    """同一 seed family 固定共享 seed；左右对称件和 torso 变体保持身份一致。"""
    digest = hashlib.sha256(seed_family.encode("utf-8")).digest()
    offset = int.from_bytes(digest[:4], "big")
    return (int(base_seed) + offset) % (2**63 - 1)


def select_single_png_output(history: dict[str, Any]) -> dict[str, str]:
    """严格选择唯一 PNG；多图或非 PNG 输出 fail closed，避免错配到 manifest。"""
    outputs = history.get("outputs")
    if not isinstance(outputs, dict):
        raise ValueError("ComfyUI history is missing outputs")

    candidates: list[dict[str, str]] = []
    for node_output in outputs.values():
        if not isinstance(node_output, dict):
            continue
        images = node_output.get("images")
        if not isinstance(images, list):
            continue
        for image in images:
            if not isinstance(image, dict):
                continue
            filename = image.get("filename")
            subfolder = image.get("subfolder", "")
            image_type = image.get("type", "output")
            if (
                isinstance(filename, str)
                and filename.lower().endswith(".png")
                and isinstance(subfolder, str)
                and isinstance(image_type, str)
            ):
                candidates.append(
                    {
                        "filename": filename,
                        "subfolder": subfolder,
                        "type": image_type,
                    }
                )

    if len(candidates) != 1:
        raise ValueError(f"ComfyUI prompt must produce exactly one PNG output, got {len(candidates)}")
    return candidates[0]


def prepare_reference_uploads(
    plan: dict[str, Any],
    reference_root: Path | str,
    client: "ComfyUiLocalClient",
    *,
    subfolder: str = _DEFAULT_REFERENCE_SUBFOLDER,
) -> dict[str, str]:
    """验证并上传 art plan 实际使用的参考图；返回可直接写入 LoadImage.image 的值。"""
    root       = Path(reference_root).resolve()
    normalized = _normalize_reference_subfolder(subfolder)
    uploaded: dict[str, str] = {}
    for reference in _required_primary_references(plan):
        path = (root / reference).resolve()
        try:
            path.relative_to(root)
        except ValueError as error:
            raise ValueError(f"reference path escapes reference root: {reference}") from error
        _validate_reference_png(path)
        uploaded[reference] = client.upload_input_image(
            path,
            subfolder=normalized,
        )
    return uploaded


def materialize_reference_zip(
    plan: dict[str, Any],
    archive_path: Path | str,
    destination_root: Path | str,
    *,
    max_reference_bytes: int = _DEFAULT_MAX_REFERENCE_BYTES,
) -> Path:
    """只从 ZIP 提取 plan 真正使用的参考 PNG，并拒绝路径穿越、重复与压缩炸弹。"""
    if max_reference_bytes <= 0:
        raise ValueError("max_reference_bytes must be positive")

    archive     = Path(archive_path)
    destination = Path(destination_root).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    required    = _required_primary_references(plan)
    found: dict[str, zipfile.ZipInfo] = {}

    with zipfile.ZipFile(archive, "r") as bundle:
        for info in bundle.infolist():
            if info.is_dir():
                continue
            member_path = _validate_zip_member_path(info.filename)
            basename    = member_path.name
            if basename not in required:
                continue
            if basename in found:
                raise ValueError(f"duplicate reference in archive: {basename}")
            _validate_zip_reference_info(
                info,
                basename,
                max_reference_bytes=max_reference_bytes,
            )
            found[basename] = info

        missing = [reference for reference in required if reference not in found]
        if missing:
            raise ValueError("reference archive is missing required PNG(s): " + ", ".join(missing))

        for reference in required:
            info       = found[reference]
            output     = (destination / reference).resolve()
            try:
                output.relative_to(destination)
            except ValueError as error:
                raise ValueError(f"reference output escapes destination: {reference}") from error
            payload = bundle.read(info)
            if len(payload) > max_reference_bytes:
                raise ValueError(f"reference size exceeds limit after extract: {reference}")
            output.write_bytes(payload)
            _validate_reference_png(output)

    return destination


class ComfyUiLocalClient:
    """最小本机 ComfyUI API client；只允许 loopback，不依赖第三方 HTTP 包。"""

    def __init__(
        self,
        server_url: str,
        *,
        request_timeout_seconds: float = 30.0,
    ) -> None:
        self.server_url             = normalize_server_url(server_url)
        self.request_timeout_seconds = request_timeout_seconds

    def object_info(self) -> dict[str, Any]:
        payload = self._request_json("GET", "/object_info")
        if not isinstance(payload, dict):
            raise ValueError("ComfyUI /object_info response must be an object")
        return payload

    def upload_input_image(
        self,
        image_path: Path | str,
        *,
        subfolder: str = _DEFAULT_REFERENCE_SUBFOLDER,
    ) -> str:
        """用 ComfyUI 官方 `/upload/image` multipart 入口上传参考图，并返回 LoadImage 可消费的名称。"""
        path       = Path(image_path)
        file_name  = _validate_reference_png(path)
        normalized = _normalize_reference_subfolder(subfolder)
        boundary   = f"----PicotooPetMaotai{uuid.uuid4().hex}"
        body       = _encode_multipart_form_data(
            boundary,
            fields={
                "type": "input",
                "subfolder": normalized,
                "overwrite": "true",
            },
            file_field="image",
            file_name=file_name,
            file_bytes=path.read_bytes(),
        )
        payload = self._request_multipart_json(
            "/upload/image",
            body,
            f"multipart/form-data; boundary={boundary}",
        )
        uploaded_name = payload.get("name")
        uploaded_sub  = payload.get("subfolder", normalized)
        if not isinstance(uploaded_name, str) or not uploaded_name:
            raise ValueError("ComfyUI upload response is missing image name")
        if not isinstance(uploaded_sub, str):
            raise ValueError("ComfyUI upload response has invalid subfolder")
        uploaded_sub = _normalize_reference_subfolder(uploaded_sub)
        if uploaded_sub:
            return f"{uploaded_sub}/{uploaded_name}"
        return uploaded_name

    def queue_prompt(self, workflow: dict[str, Any]) -> str:
        payload = self._request_json("POST", "/prompt", {"prompt": workflow})
        prompt_id = payload.get("prompt_id")
        if not isinstance(prompt_id, str) or not prompt_id:
            raise ValueError("ComfyUI /prompt did not return prompt_id")
        return prompt_id

    def wait_for_history(
        self,
        prompt_id: str,
        *,
        timeout_seconds: float,
        poll_interval_seconds: float = 0.35,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            payload = self._request_json("GET", f"/history/{urllib.parse.quote(prompt_id)}")
            entry   = payload.get(prompt_id)
            if isinstance(entry, dict):
                status = entry.get("status")
                if isinstance(status, dict) and status.get("status_str") == "error":
                    raise RuntimeError(f"ComfyUI prompt failed: {prompt_id}")
                outputs = entry.get("outputs")
                if isinstance(outputs, dict) and outputs:
                    return entry
            time.sleep(poll_interval_seconds)
        raise TimeoutError(f"ComfyUI prompt timed out: {prompt_id}")

    def download_output(self, output: dict[str, str]) -> bytes:
        query = urllib.parse.urlencode(output)
        return self._request_bytes("GET", f"/view?{query}")

    def _request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        data    = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"

        request = urllib.request.Request(
            f"{self.server_url}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        with urllib.request.urlopen(  # noqa: S310 - URL is restricted to loopback above.
            request,
            timeout=self.request_timeout_seconds,
        ) as response:
            return json.loads(response.read().decode("utf-8"))

    def _request_multipart_json(
        self,
        path: str,
        body: bytes,
        content_type: str,
    ) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self.server_url}{path}",
            data=body,
            headers={
                "Accept": "application/json",
                "Content-Type": content_type,
            },
            method="POST",
        )
        with urllib.request.urlopen(  # noqa: S310 - URL is restricted to loopback above.
            request,
            timeout=self.request_timeout_seconds,
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("ComfyUI multipart response must be an object")
        return payload

    def _request_bytes(self, method: str, path: str) -> bytes:
        request = urllib.request.Request(
            f"{self.server_url}{path}",
            headers={"Accept": "image/png"},
            method=method,
        )
        with urllib.request.urlopen(  # noqa: S310 - URL is restricted to loopback above.
            request,
            timeout=self.request_timeout_seconds,
        ) as response:
            return response.read()


def run_art_plan(
    plan_path: Path | str,
    workflow_path: Path | str,
    bindings_path: Path | str | None,
    incoming_root: Path | str,
    *,
    server_url: str = "http://127.0.0.1:8188",
    base_seed: int = 230815,
    prompt_timeout_seconds: float = 900.0,
    reference_root: Path | str | None = None,
    reference_zip: Path | str | None = None,
    reference_subfolder: str = _DEFAULT_REFERENCE_SUBFOLDER,
    stage: bool = False,
    destination_root: Path | str | None = None,
) -> dict[str, Any]:
    """串行生成完整 manifest 集合；全部输出验证通过前绝不触碰正式 V2 目录。"""
    if reference_root is not None and reference_zip is not None:
        raise ValueError("reference directory and reference ZIP are mutually exclusive")

    plan     = _load_json_object(plan_path, "art plan")
    workflow = _load_json_object(workflow_path, "ComfyUI workflow")
    bindings = (
        load_bindings(bindings_path)
        if bindings_path is not None
        else build_bindings_from_workflow(workflow)
    )
    incoming = Path(incoming_root)
    jobs     = plan.get("jobs")
    if not isinstance(jobs, list) or not jobs:
        raise ValueError("art plan must contain non-empty jobs")

    # Graph preflight        : reject disconnected reference/RMBG/generation nodes before filesystem or HTTP side effects.
    validate_maotai_workflow_graph(workflow, bindings)

    incoming.mkdir(parents=True, exist_ok=True)
    existing_pngs = sorted(path.name for path in incoming.glob("*.png"))
    if existing_pngs:
        raise ValueError(
            "incoming directory must not contain stale PNGs before a production run: "
            + ", ".join(existing_pngs[:5])
        )

    manifest_path = _manifest_from_plan(plan)
    descriptors   = parse_manifest(manifest_path)
    client        = ComfyUiLocalClient(server_url)
    object_info   = client.object_info()
    validate_comfyui_workflow_node_types(object_info, workflow)
    _verify_optional_rmbg(object_info, workflow, bindings)
    reference_inputs = _prepare_reference_inputs(
        plan,
        bindings,
        client,
        reference_root=reference_root,
        reference_zip=reference_zip,
        reference_subfolder=reference_subfolder,
    )

    generated: list[str] = []
    for job in jobs:
        if not isinstance(job, dict):
            raise ValueError("each art job must be an object")
        target_file = job.get("target_file")
        seed_family = job.get("seed_family")
        if not isinstance(target_file, str) or not target_file.endswith(".png"):
            raise ValueError("art job target_file must be a PNG basename")
        if Path(target_file).name != target_file:
            raise ValueError(f"art job target_file must be a basename: {target_file}")
        if not isinstance(seed_family, str) or not seed_family:
            raise ValueError(f"art job seed_family missing: {target_file}")

        seed     = deterministic_seed(base_seed, seed_family)
        prefix   = f"maotai-v2/{Path(target_file).stem}"
        rendered = apply_job_to_workflow(
            workflow,
            bindings,
            job,
            seed=seed,
            filename_prefix=prefix,
            reference_inputs=reference_inputs,
        )
        prompt_id = client.queue_prompt(rendered)
        history   = client.wait_for_history(
            prompt_id,
            timeout_seconds=prompt_timeout_seconds,
        )
        output    = select_single_png_output(history)
        png_bytes = client.download_output(output)
        if not png_bytes.startswith(_PNG_SIGNATURE):
            raise ValueError(f"ComfyUI returned a non-PNG payload for {target_file}")

        candidate_path = incoming / f".{target_file}.candidate"
        final_path     = incoming / target_file
        candidate_path.write_bytes(png_bytes)
        try:
            _validate_generated_structural_output(
                candidate_path,
                target_file,
                job,
                descriptors,
            )
            candidate_path.replace(final_path)
        finally:
            if candidate_path.exists():
                candidate_path.unlink()
        generated.append(target_file)

    report = validate_asset_directory(incoming, manifest_path)
    if not report.ok:
        raise ValueError("generated Maotai v2 assets failed validation: " + "; ".join(report.errors))

    if stage:
        destination = Path(destination_root) if destination_root is not None else _default_asset_root()
        staged      = stage_asset_directory(incoming, destination, manifest_path)
        if not staged.ok:
            raise ValueError("Maotai v2 staging failed: " + "; ".join(staged.errors))

    return {
        "ok": True,
        "generated": generated,
        "asset_count": report.asset_count,
        "staged": stage,
    }


def _validate_generated_structural_output(
    path: Path,
    target_file: str,
    job: dict[str, Any],
    descriptors: dict[str, Any],
) -> None:
    descriptor = descriptors.get(target_file)
    if descriptor is None:
        raise ValueError(f"art job target is missing from manifest: {target_file}")

    quality = job.get("structural_quality")
    if quality is None:
        return
    if not isinstance(quality, dict):
        raise ValueError(f"art job structural_quality must be an object: {target_file}")

    errors = validate_structural_art_quality(path, descriptor, quality)
    if errors:
        raise ValueError(
            "generated Maotai v2 structural art failed organic silhouette gate: "
            + "; ".join(errors)
        )


def _prepare_reference_inputs(
    plan: dict[str, Any],
    bindings: dict[str, Any],
    client: ComfyUiLocalClient,
    *,
    reference_root: Path | str | None,
    reference_zip: Path | str | None,
    reference_subfolder: str,
) -> dict[str, str] | None:
    """把目录或 handoff ZIP 统一收敛到已上传的 ComfyUI LoadImage 值。"""
    if "reference_image" not in bindings:
        return None
    if reference_root is not None:
        return prepare_reference_uploads(
            plan,
            reference_root,
            client,
            subfolder=reference_subfolder,
        )
    if reference_zip is None:
        return None

    with tempfile.TemporaryDirectory(prefix="picotoopet-maotai-v2-refs-") as temporary:
        materialized = materialize_reference_zip(
            plan,
            reference_zip,
            Path(temporary),
        )
        return prepare_reference_uploads(
            plan,
            materialized,
            client,
            subfolder=reference_subfolder,
        )


def _required_primary_references(plan: dict[str, Any]) -> list[str]:
    jobs = plan.get("jobs")
    if not isinstance(jobs, list) or not jobs:
        raise ValueError("art plan must contain non-empty jobs before reference processing")

    references: list[str] = []
    seen: set[str]        = set()
    for job in jobs:
        if not isinstance(job, dict):
            raise ValueError("each art job must be an object before reference processing")
        reference = job.get("primary_reference")
        if not isinstance(reference, str) or not reference:
            raise ValueError("art job primary_reference is missing")
        if Path(reference).name != reference or "/" in reference or "\\" in reference:
            raise ValueError(f"primary_reference must be a basename: {reference!r}")
        if reference not in seen:
            references.append(reference)
            seen.add(reference)
    return references


def _validate_zip_member_path(member_name: str) -> PurePosixPath:
    normalized = member_name.replace("\\", "/")
    path       = PurePosixPath(normalized)
    if (
        not normalized
        or normalized.startswith("/")
        or ":" in path.parts[0]
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError(f"unsafe archive path: {member_name!r}")
    return path


def _validate_zip_reference_info(
    info: zipfile.ZipInfo,
    reference: str,
    *,
    max_reference_bytes: int,
) -> None:
    if info.flag_bits & 0x1:
        raise ValueError(f"encrypted reference archive entry is not allowed: {reference}")
    if info.file_size > max_reference_bytes:
        raise ValueError(
            f"reference size exceeds limit: {reference} ({info.file_size} bytes)"
        )
    if info.compress_size > 0 and info.file_size > 0:
        ratio = info.file_size / info.compress_size
        if ratio > _MAX_ZIP_COMPRESSION_RATIO:
            raise ValueError(
                f"reference compression ratio exceeds safety limit: {reference}"
            )


def _validate_reference_png(path: Path) -> str:
    if not path.is_file():
        raise ValueError(f"reference PNG is missing: {path}")
    file_name = path.name
    if not file_name.lower().endswith(".png"):
        raise ValueError(f"reference image must be a PNG: {file_name}")
    if any(character in file_name for character in ('"', "\r", "\n")):
        raise ValueError(f"reference PNG filename is unsafe: {file_name!r}")
    with path.open("rb") as stream:
        if stream.read(len(_PNG_SIGNATURE)) != _PNG_SIGNATURE:
            raise ValueError(f"reference image is not a valid PNG payload: {file_name}")
    return file_name


def _normalize_reference_subfolder(subfolder: str) -> str:
    value = str(subfolder).strip().replace("\\", "/")
    if not value:
        return ""
    if value.startswith("/") or ":" in value:
        raise ValueError(f"reference subfolder must be relative: {subfolder!r}")

    segments = value.split("/")
    if any(
        not segment
        or segment in {".", ".."}
        or any(character in segment for character in ('"', "\r", "\n"))
        for segment in segments
    ):
        raise ValueError(f"reference subfolder is unsafe: {subfolder!r}")
    return "/".join(segments)


def _validate_multipart_boundary(boundary: str) -> bytes:
    if not boundary or len(boundary) > 70:
        raise ValueError("multipart boundary length is invalid")
    try:
        encoded = boundary.encode("ascii")
    except UnicodeEncodeError as error:
        raise ValueError("multipart boundary must be ASCII") from error
    if any(byte in encoded for byte in b"\r\n\""):
        raise ValueError("multipart boundary contains unsafe characters")
    return encoded


def _require_node_input(
    workflow: dict[str, Any],
    node_id: str,
    input_name: str,
    title: str,
) -> None:
    node = workflow.get(node_id)
    if not isinstance(node, dict):
        raise ValueError(f"{title} auto-bind node is missing: {node_id}")
    inputs = node.get("inputs")
    if not isinstance(inputs, dict) or input_name not in inputs:
        raise ValueError(f"{title} auto-bind node is missing required input: {input_name}")


def _validate_required_bindings(bindings: dict[str, Any]) -> None:
    missing = [name for name in _REQUIRED_BINDINGS if name not in bindings]
    if missing:
        raise ValueError("missing required ComfyUI binding(s): " + ", ".join(missing))
    for name in _REQUIRED_BINDINGS:
        binding = bindings[name]
        if not isinstance(binding, dict):
            raise ValueError(f"ComfyUI binding must be an object: {name}")
        if not isinstance(binding.get("node"), str) or not isinstance(binding.get("input"), str):
            raise ValueError(f"ComfyUI binding requires node/input strings: {name}")


def _set_binding(
    workflow: dict[str, Any],
    binding: dict[str, Any],
    value: Any,
    binding_name: str,
) -> None:
    node_id    = binding.get("node")
    input_name = binding.get("input")
    if not isinstance(node_id, str) or not isinstance(input_name, str):
        raise ValueError(f"invalid ComfyUI binding: {binding_name}")

    node = workflow.get(node_id)
    if not isinstance(node, dict):
        raise ValueError(f"ComfyUI binding node not found for {binding_name}: {node_id}")
    inputs = node.get("inputs")
    if not isinstance(inputs, dict) or input_name not in inputs:
        raise ValueError(
            f"ComfyUI binding input not found for {binding_name}: {node_id}.{input_name}"
        )
    inputs[input_name] = value


def _apply_rmbg_binding(workflow: dict[str, Any], binding: Any) -> None:
    if not isinstance(binding, dict) or not isinstance(binding.get("node"), str):
        raise ValueError("rmbg binding requires a node string")
    node_id = binding["node"]
    node    = workflow.get(node_id)
    if not isinstance(node, dict) or node.get("class_type") != "BiRefNetRMBG":
        raise ValueError("rmbg binding must target a BiRefNetRMBG node")
    inputs = node.get("inputs")
    if not isinstance(inputs, dict):
        raise ValueError("BiRefNetRMBG node is missing inputs")

    background_input = str(binding.get("background_input", "background"))
    model_input      = str(binding.get("model_input", "model"))
    model_name       = str(binding.get("model", "Lucida"))
    inputs[background_input] = "Alpha"
    inputs[model_input]      = model_name


def _verify_optional_rmbg(
    object_info: dict[str, Any],
    workflow: dict[str, Any],
    bindings: dict[str, Any],
) -> None:
    validate_comfyui_workflow_node_types(object_info, workflow)
    if "rmbg" not in bindings:
        return
    rmbg = bindings["rmbg"]
    if not isinstance(rmbg, dict):
        raise ValueError("rmbg binding must be an object")
    node_id = rmbg.get("node")
    if not isinstance(node_id, str):
        raise ValueError("rmbg binding requires node")
    node = workflow.get(node_id)
    if not isinstance(node, dict) or node.get("class_type") != "BiRefNetRMBG":
        raise ValueError("rmbg node must be BiRefNetRMBG")
    if "BiRefNetRMBG" not in object_info:
        raise ValueError("BiRefNetRMBG is not registered in ComfyUI object_info")


def _load_json_object(path: Path | str, label: str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{label} JSON must be an object")
    return payload


def _linked_node_id(value: Any) -> str | None:
    if (
        isinstance(value, list)
        and len(value) == 2
        and isinstance(value[0], (str, int))
        and isinstance(value[1], int)
    ):
        return str(value[0])
    return None


def _manifest_from_plan(plan: dict[str, Any]) -> Path:
    source = plan.get("source_of_truth")
    if not isinstance(source, str) or not source:
        raise ValueError("art plan source_of_truth is missing")
    path = Path(source)
    if path.is_absolute():
        return path
    return (_repository_root() / path).resolve()


def _default_asset_root() -> Path:
    return (
        _repository_root()
        / "windows"
        / "desktop"
        / "src"
        / "PicotooPet.Desktop"
        / "Assets"
        / "Maotai"
        / "V2"
    )


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _encode_multipart_form_data(
    boundary: str,
    *,
    fields: dict[str, str],
    file_field: str,
    file_name: str,
    file_bytes: bytes,
) -> bytes:
    encoded_boundary = _validate_multipart_boundary(boundary)
    chunks: list[bytes] = []
    for name, value in fields.items():
        if any(character in name for character in ('"', "\r", "\n")):
            raise ValueError("multipart field name contains unsafe characters")
        chunks.extend(
            [
                b"--" + encoded_boundary + b"\r\n",
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"),
                value.encode("utf-8"),
                b"\r\n",
            ]
        )

    if any(character in file_field for character in ('"', "\r", "\n")):
        raise ValueError("multipart file field contains unsafe characters")
    if any(character in file_name for character in ('"', "\r", "\n")):
        raise ValueError("multipart filename contains unsafe characters")
    chunks.extend(
        [
            b"--" + encoded_boundary + b"\r\n",
            (
                f'Content-Disposition: form-data; name="{file_field}"; '
                f'filename="{file_name}"\r\n'
            ).encode("utf-8"),
            b"Content-Type: image/png\r\n\r\n",
            file_bytes,
            b"\r\n",
            b"--" + encoded_boundary + b"--\r\n",
        ]
    )
    return b"".join(chunks)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run manifest-derived Maotai v2 art jobs against local ComfyUI.",
    )
    parser.add_argument("plan", type=Path)
    parser.add_argument("workflow", type=Path)
    parser.add_argument("--bindings", type=Path)
    parser.add_argument("--incoming", type=Path, required=True)
    parser.add_argument("--server", default="http://127.0.0.1:8188")
    parser.add_argument("--base-seed", type=int, default=230815)
    parser.add_argument("--timeout", type=float, default=900.0)
    reference_group = parser.add_mutually_exclusive_group()
    reference_group.add_argument("--reference-root", type=Path)
    reference_group.add_argument("--reference-zip", type=Path)
    parser.add_argument("--reference-subfolder", default=_DEFAULT_REFERENCE_SUBFOLDER)
    parser.add_argument("--stage", action="store_true")
    parser.add_argument("--destination", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    result = run_art_plan(
        args.plan,
        args.workflow,
        args.bindings,
        args.incoming,
        server_url=args.server,
        base_seed=args.base_seed,
        prompt_timeout_seconds=args.timeout,
        reference_root=args.reference_root,
        reference_zip=args.reference_zip,
        reference_subfolder=args.reference_subfolder,
        stage=args.stage,
        destination_root=args.destination,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
