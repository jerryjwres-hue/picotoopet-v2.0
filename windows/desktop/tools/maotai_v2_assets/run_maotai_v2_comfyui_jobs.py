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
    title_index: dict[str, str] = {}
    watched_titles              = set(_REQUIRED_AUTO_TITLES) | set(_OPTIONAL_AUTO_TITLES)

    for node_id, node in workflow.items():
        if not isinstance(node_id, str) or not isinstance(node, dict):
            continue
        metadata = node.get("_meta")
        if not isinstance(metadata, dict):
            continue
        title = metadata.get("title")
        if not isinstance(title, str) or title not in watched_titles:
            continue
        if title in title_index:
            raise ValueError(f"duplicate ComfyUI auto-bind title: {title}")
        title_index[title] = node_id

    missing_titles = [title for title in _REQUIRED_AUTO_TITLES if title not in title_index]
    if missing_titles:
        raise ValueError(
            "missing required ComfyUI auto-bind title(s): " + ", ".join(missing_titles)
        )

    sampler_id  = title_index["MAOTAI_SAMPLER"]
    canvas_id   = title_index["MAOTAI_CANVAS"]
    positive_id = title_index["MAOTAI_POSITIVE"]
    negative_id = title_index["MAOTAI_NEGATIVE"]
    save_id     = title_index["MAOTAI_SAVE"]

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

    reference_id = title_index.get("MAOTAI_REFERENCE")
    if reference_id is not None:
        _require_node_input(workflow, reference_id, "image", "MAOTAI_REFERENCE")
        bindings["reference_image"] = {"node": reference_id, "input": "image"}

    rmbg_id = title_index.get("MAOTAI_RMBG")
    if rmbg_id is not None:
        rmbg_node = workflow.get(rmbg_id)
        if not isinstance(rmbg_node, dict) or rmbg_node.get("class_type") != "BiRefNetRMBG":
            raise ValueError("MAOTAI_RMBG must target a BiRefNetRMBG node")
        _require_node_input(workflow, rmbg_id, "background", "MAOTAI_RMBG")
        _require_node_input(workflow, rmbg_id, "model", "MAOTAI_RMBG")
        bindings["rmbg"] = {
            "node": rmbg_id,
            "background_input": "background",
            "model_input": "model",
            "model": "Lucida",
        }

    _validate_required_bindings(bindings)
    return bindings


def workflow_upstream_node_ids(
    workflow: dict[str, Any],
    node_id: str,
) -> set[str]:
    """沿 ComfyUI API link `[upstream_node_id, output_index]` 收集最终节点的全部上游。"""
    if not isinstance(workflow, dict):
        raise ValueError("ComfyUI workflow must be an object")
    if node_id not in workflow or not isinstance(workflow.get(node_id), dict):
        raise ValueError(f"ComfyUI workflow node is missing: {node_id}")

    upstream: set[str] = set()
    visited: set[str]  = {node_id}
    pending: list[str] = [node_id]

    while pending:
        current_id = pending.pop()
        current    = workflow.get(current_id)
        if not isinstance(current, dict):
            raise ValueError(f"ComfyUI workflow node is invalid: {current_id}")
        inputs = current.get("inputs")
        if inputs is None:
            continue
        if not isinstance(inputs, dict):
            raise ValueError(f"ComfyUI workflow node inputs are invalid: {current_id}")

        for input_value in inputs.values():
            linked_id = _workflow_link_node_id(input_value)
            if linked_id is None:
                continue
            if linked_id not in workflow or not isinstance(workflow.get(linked_id), dict):
                raise ValueError(
                    f"dangling ComfyUI workflow link: {current_id} -> {linked_id}"
                )
            if linked_id in visited:
                continue

            visited.add(linked_id)
            upstream.add(linked_id)
            pending.append(linked_id)

    upstream.discard(node_id)
    return upstream


def validate_maotai_workflow_graph(
    workflow: dict[str, Any],
    bindings: dict[str, Any],
) -> None:
    """确认命名生产节点真实参与最终 SaveImage 上游链，拒绝摆设节点和旁路 alpha。"""
    _validate_required_bindings(bindings)

    save_binding = bindings["filename_prefix"]
    save_id      = save_binding.get("node")
    if not isinstance(save_id, str):
        raise ValueError("MAOTAI_SAVE binding requires a node string")

    upstream = workflow_upstream_node_ids(workflow, save_id)
    required_roles = (
        ("positive", "MAOTAI_POSITIVE"),
        ("negative", "MAOTAI_NEGATIVE"),
        ("width", "MAOTAI_CANVAS"),
        ("height", "MAOTAI_CANVAS"),
        ("seed", "MAOTAI_SAMPLER"),
    )

    for binding_name, title in required_roles:
        binding = bindings[binding_name]
        node_id = binding.get("node")
        if not isinstance(node_id, str) or node_id not in upstream:
            raise ValueError(
                f"{title} ({binding_name}) must be upstream of MAOTAI_SAVE"
            )

    reference = bindings.get("reference_image")
    if reference is not None:
        if not isinstance(reference, dict) or not isinstance(reference.get("node"), str):
            raise ValueError("MAOTAI_REFERENCE binding requires a node string")
        if reference["node"] not in upstream:
            raise ValueError("MAOTAI_REFERENCE must be upstream of MAOTAI_SAVE")

    rmbg = bindings.get("rmbg")
    if rmbg is not None:
        if not isinstance(rmbg, dict) or not isinstance(rmbg.get("node"), str):
            raise ValueError("MAOTAI_RMBG binding requires a node string")
        if rmbg["node"] not in upstream:
            raise ValueError("MAOTAI_RMBG must be upstream of MAOTAI_SAVE")


def validate_comfyui_workflow_node_types(
    object_info: dict[str, Any],
    workflow: dict[str, Any],
) -> None:
    """在上传参考图前确认 workflow 的每种 node class 已由当前本机 ComfyUI 注册。"""
    if not isinstance(object_info, dict):
        raise ValueError("ComfyUI /object_info must be an object")
    if not isinstance(workflow, dict):
        raise ValueError("ComfyUI workflow must be an object")

    missing: list[str] = []
    for node_id, node in workflow.items():
        if not isinstance(node_id, str) or not isinstance(node, dict):
            raise ValueError(f"ComfyUI workflow node is invalid: {node_id!r}")
        class_type = node.get("class_type")
        if not isinstance(class_type, str) or not class_type:
            raise ValueError(f"ComfyUI workflow node class_type is invalid: {node_id}")
        if class_type not in object_info:
            missing.append(f"{node_id}:{class_type}")

    if missing:
        raise ValueError(
            "ComfyUI workflow node class is not registered: " + ", ".join(missing)
        )


def _workflow_link_node_id(value: Any) -> str | None:
    """只把 ComfyUI API 的二元 link 识别为依赖，普通列表参数不参与图遍历。"""
    if (
        isinstance(value, list)
        and len(value) == 2
        and isinstance(value[0], str)
        and isinstance(value[1], int)
        and not isinstance(value[1], bool)
    ):
        return value[0]
    return None


def build_multipart_image_upload(
    image_path: Path | str,
    *,
    subfolder: str = _DEFAULT_REFERENCE_SUBFOLDER,
    boundary: str | None = None,
) -> tuple[bytes, str]:
    """按 ComfyUI `/upload/image` 的标准字段构造 multipart；不依赖第三方 HTTP 包。"""
    path       = Path(image_path)
    folder     = _normalize_reference_subfolder(subfolder)
    file_name  = _validate_reference_png(path)
    boundary   = boundary or f"PicotooPetMaotai{uuid.uuid4().hex}"
    boundary_b = _validate_multipart_boundary(boundary)
    payload    = path.read_bytes()

    body = bytearray()

    def add_text(name: str, value: str) -> None:
        body.extend(b"--" + boundary_b + b"\r\n")
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("ascii"))
        body.extend(value.encode("utf-8"))
        body.extend(b"\r\n")

    body.extend(b"--" + boundary_b + b"\r\n")
    body.extend(
        (
            'Content-Disposition: form-data; name="image"; '
            f'filename="{file_name}"\r\n'
        ).encode("ascii")
    )
    body.extend(b"Content-Type: image/png\r\n\r\n")
    body.extend(payload)
    body.extend(b"\r\n")
    add_text("overwrite", "true")
    add_text("type", "input")
    add_text("subfolder", folder)
    body.extend(b"--" + boundary_b + b"--\r\n")

    return bytes(body), f"multipart/form-data; boundary={boundary}"


def normalize_uploaded_input_name(
    payload: dict[str, Any],
    *,
    expected_name: str,
    expected_subfolder: str,
) -> str:
    """严格核对 ComfyUI 上传响应，防止把 output/temp 或意外目录当成 LoadImage 输入。"""
    if not isinstance(payload, dict):
        raise ValueError("ComfyUI upload response must be an object")

    actual_name      = payload.get("name")
    actual_subfolder = payload.get("subfolder")
    actual_type      = payload.get("type")
    if actual_name != expected_name:
        raise ValueError(
            f"ComfyUI upload name mismatch: expected {expected_name}, got {actual_name!r}"
        )
    if actual_subfolder != expected_subfolder:
        raise ValueError(
            "ComfyUI upload subfolder mismatch: "
            f"expected {expected_subfolder}, got {actual_subfolder!r}"
        )
    if actual_type != "input":
        raise ValueError(f"ComfyUI upload type must be input, got {actual_type!r}")

    return f"{expected_subfolder}/{expected_name}" if expected_subfolder else expected_name


def prepare_reference_uploads(
    plan: dict[str, Any],
    reference_root: Path | str,
    client: Any,
    *,
    subfolder: str = _DEFAULT_REFERENCE_SUBFOLDER,
) -> dict[str, str]:
    """先完整 preflight 所有 job 的主参考图，再逐张上传；缺一张时保证零上传副作用。"""
    root       = Path(reference_root)
    folder     = _normalize_reference_subfolder(subfolder)
    references = _required_primary_references(plan)

    if not root.is_dir():
        raise ValueError(f"reference directory missing: {root}")

    # Preflight first       : validate every required reference before the first HTTP side effect.
    reference_paths: dict[str, Path] = {}
    for reference in references:
        path = root / reference
        if not path.is_file():
            raise ValueError(f"required Maotai reference is missing: {reference}")
        _validate_reference_png(path)
        reference_paths[reference] = path

    uploaded: dict[str, str] = {}
    for reference in references:
        uploaded[reference] = client.upload_input_image(
            reference_paths[reference],
            subfolder=folder,
        )
    return uploaded


def materialize_reference_zip(
    plan: dict[str, Any],
    zip_path: Path | str,
    destination_root: Path | str,
    *,
    max_reference_bytes: int = _DEFAULT_MAX_REFERENCE_BYTES,
) -> Path:
    """只物化 plan 需要的参考 PNG；先全量预检，再按安全 basename 写入临时目录。"""
    archive_path = Path(zip_path)
    destination  = Path(destination_root)
    references   = _required_primary_references(plan)

    if max_reference_bytes < len(_PNG_SIGNATURE):
        raise ValueError("reference size limit is too small for a PNG")
    if not archive_path.is_file():
        raise ValueError(f"reference ZIP is missing: {archive_path}")

    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            matches: dict[str, zipfile.ZipInfo] = {}

            for info in archive.infolist():
                if info.is_dir():
                    continue
                member = _validate_zip_member_path(info.filename)
                basename = member.name
                if basename not in references:
                    continue
                if basename in matches:
                    raise ValueError(
                        f"duplicate required reference basename in archive: {basename}"
                    )
                _validate_zip_reference_info(
                    info,
                    basename,
                    max_reference_bytes=max_reference_bytes,
                )
                matches[basename] = info

            missing = [reference for reference in references if reference not in matches]
            if missing:
                raise ValueError(
                    "required Maotai reference missing from ZIP: " + ", ".join(missing)
                )

            # Read and validate all payloads before creating/writing the destination directory.
            payloads: dict[str, bytes] = {}
            for reference in references:
                info    = matches[reference]
                payload = archive.read(info)
                if len(payload) > max_reference_bytes:
                    raise ValueError(
                        f"reference size exceeds limit after decompression: {reference}"
                    )
                if not payload.startswith(_PNG_SIGNATURE):
                    raise ValueError(f"reference is not a PNG payload: {reference}")
                payloads[reference] = payload
    except zipfile.BadZipFile as error:
        raise ValueError(f"invalid Maotai reference ZIP: {archive_path}") from error

    destination.mkdir(parents=True, exist_ok=True)
    for reference in references:
        (destination / reference).write_bytes(payloads[reference])
    return destination


def apply_job_to_workflow(
    workflow: dict[str, Any],
    bindings: dict[str, Any],
    job: dict[str, Any],
    *,
    seed: int,
    filename_prefix: str,
    reference_inputs: dict[str, str] | None = None,
) -> dict[str, Any]:
    """深拷贝 API workflow 并只改显式绑定字段；模板对象本身保持不变。"""
    _validate_required_bindings(bindings)
    rendered = copy.deepcopy(workflow)
    output   = job.get("output")
    if not isinstance(output, dict):
        raise ValueError("art job output contract is missing")

    values = {
        "positive": job.get("positive_prompt"),
        "negative": job.get("negative_prompt"),
        "width": output.get("width_px"),
        "height": output.get("height_px"),
        "seed": seed,
        "filename_prefix": filename_prefix,
    }
    for binding_name, value in values.items():
        if value is None:
            raise ValueError(f"art job value missing for binding: {binding_name}")
        _set_binding(rendered, bindings[binding_name], value, binding_name)

    reference_binding = bindings.get("reference_image")
    if reference_binding is not None:
        reference_name = job.get("primary_reference")
        if not isinstance(reference_name, str) or not reference_name:
            raise ValueError("reference_image binding requires job.primary_reference")
        reference_value = reference_name
        if reference_inputs is not None:
            reference_value = reference_inputs.get(reference_name, "")
            if not reference_value:
                raise ValueError(
                    f"uploaded reference mapping is missing: {reference_name}"
                )
        _set_binding(rendered, reference_binding, reference_value, "reference_image")

    rmbg_binding = bindings.get("rmbg")
    if rmbg_binding is not None:
        _apply_rmbg_binding(rendered, rmbg_binding)

    return rendered


def select_single_png_output(history: dict[str, Any]) -> dict[str, str]:
    """只接受一次 job 的唯一 PNG 输出，避免误把 preview/mask/旧结果当正式部件。"""
    outputs = history.get("outputs")
    if not isinstance(outputs, dict):
        raise ValueError("ComfyUI history must contain outputs")

    png_outputs: list[dict[str, str]] = []
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
            if not isinstance(filename, str) or not filename.lower().endswith(".png"):
                continue
            png_outputs.append(
                {
                    "filename": filename,
                    "subfolder": str(image.get("subfolder", "")),
                    "type": str(image.get("type", "output")),
                }
            )

    if len(png_outputs) != 1:
        raise ValueError(
            f"ComfyUI job must produce exactly one PNG output, found {len(png_outputs)}"
        )
    return png_outputs[0]


def deterministic_seed(base_seed: int, seed_family: str) -> int:
    """镜像/变体共享 seed family，保持身份相关性而不维护第二份资产清单。"""
    digest = hashlib.sha256(f"{base_seed}:{seed_family}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") & 0x7FFF_FFFF_FFFF_FFFF


class ComfyUiLocalClient:
    """最小本地 ComfyUI API client；只访问 normalize_server_url 允许的 loopback。"""

    def __init__(self, server_url: str, *, request_timeout_seconds: float = 30.0) -> None:
        self.server_url              = normalize_server_url(server_url)
        self.request_timeout_seconds = max(1.0, float(request_timeout_seconds))
        self.client_id               = uuid.uuid4().hex

    def object_info(self) -> dict[str, Any]:
        payload = self._request_json("GET", "/object_info")
        if not isinstance(payload, dict):
            raise ValueError("ComfyUI /object_info did not return an object")
        return payload

    def upload_input_image(
        self,
        image_path: Path | str,
        *,
        subfolder: str = _DEFAULT_REFERENCE_SUBFOLDER,
    ) -> str:
        """上传本地参考 PNG 到 ComfyUI input；响应必须与请求的 name/subfolder/type 精确一致。"""
        path               = Path(image_path)
        folder             = _normalize_reference_subfolder(subfolder)
        expected_name      = _validate_reference_png(path)
        body, content_type = build_multipart_image_upload(path, subfolder=folder)
        response           = self._request_multipart_json(
            "/upload/image",
            body,
            content_type,
        )
        return normalize_uploaded_input_name(
            response,
            expected_name=expected_name,
            expected_subfolder=folder,
        )

    def queue_prompt(self, workflow: dict[str, Any]) -> str:
        payload = self._request_json(
            "POST",
            "/prompt",
            {
                "prompt": workflow,
                "client_id": self.client_id,
            },
        )
        if not isinstance(payload, dict) or not isinstance(payload.get("prompt_id"), str):
            raise ValueError("ComfyUI /prompt response is missing prompt_id")
        return payload["prompt_id"]

    def wait_for_history(
        self,
        prompt_id: str,
        *,
        timeout_seconds: float,
        poll_interval_seconds: float = 0.25,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + max(1.0, timeout_seconds)
        encoded  = urllib.parse.quote(prompt_id, safe="")

        while time.monotonic() < deadline:
            payload = self._request_json("GET", f"/history/{encoded}")
            history = _unwrap_history(payload, prompt_id)
            if history is not None and isinstance(history.get("outputs"), dict):
                return history
            time.sleep(max(0.05, poll_interval_seconds))

        raise TimeoutError(f"ComfyUI prompt timed out: {prompt_id}")

    def download_output(self, output: dict[str, str]) -> bytes:
        query = urllib.parse.urlencode(
            {
                "filename": output["filename"],
                "subfolder": output.get("subfolder", ""),
                "type": output.get("type", "output"),
            }
        )
        return self._request_bytes("GET", f"/view?{query}")

    def _request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        data    = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
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

    client = ComfyUiLocalClient(server_url)
    _verify_optional_rmbg(client.object_info(), workflow, bindings)
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

        (incoming / target_file).write_bytes(png_bytes)
        generated.append(target_file)

    manifest_path = _manifest_from_plan(plan)
    report        = validate_asset_directory(incoming, manifest_path)
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
    # Node availability     : reject any workflow class missing from this local ComfyUI before reference upload.
    validate_comfyui_workflow_node_types(object_info, workflow)

    rmbg = bindings.get("rmbg")
    if rmbg is None:
        return
    if "BiRefNetRMBG" not in object_info:
        raise ValueError(
            "ComfyUI-RMBG BiRefNetRMBG node is not installed; remove the rmbg binding or install it"
        )
    if not isinstance(rmbg, dict) or not isinstance(rmbg.get("node"), str):
        raise ValueError("rmbg binding requires a node string")
    node = workflow.get(rmbg["node"])
    if not isinstance(node, dict) or node.get("class_type") != "BiRefNetRMBG":
        raise ValueError("rmbg binding does not point to a BiRefNetRMBG workflow node")


def _unwrap_history(payload: Any, prompt_id: str) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    if isinstance(payload.get("outputs"), dict):
        return payload
    nested = payload.get(prompt_id)
    return nested if isinstance(nested, dict) else None


def _load_json_object(path: Path | str, label: str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{label} JSON must be an object")
    return payload


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[4]


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


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run manifest-derived Maotai v2 art jobs through a local ComfyUI API workflow.",
    )
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--workflow", type=Path, required=True)
    parser.add_argument(
        "--bindings",
        type=Path,
        default=None,
        help="Optional explicit binding JSON; omitted means MAOTAI_* title auto-binding.",
    )
    parser.add_argument("--incoming", type=Path, required=True)

    reference_source = parser.add_mutually_exclusive_group()
    reference_source.add_argument(
        "--reference-dir",
        type=Path,
        default=None,
        help="Local directory whose required references are uploaded to ComfyUI input.",
    )
    reference_source.add_argument(
        "--reference-zip",
        type=Path,
        default=None,
        help="Handoff ZIP; only required reference PNGs are safely materialized and uploaded.",
    )
    parser.add_argument(
        "--reference-subfolder",
        default=_DEFAULT_REFERENCE_SUBFOLDER,
        help="ComfyUI input subfolder used for uploaded Maotai references.",
    )
    parser.add_argument("--server", default="http://127.0.0.1:8188")
    parser.add_argument("--base-seed", type=int, default=230815)
    parser.add_argument("--prompt-timeout", type=float, default=900.0)
    parser.add_argument("--stage", action="store_true")
    parser.add_argument("--destination", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args   = _build_parser().parse_args(argv)
    result = run_art_plan(
        args.plan,
        args.workflow,
        args.bindings,
        args.incoming,
        server_url=args.server,
        base_seed=args.base_seed,
        prompt_timeout_seconds=args.prompt_timeout,
        reference_root=args.reference_dir,
        reference_zip=args.reference_zip,
        reference_subfolder=args.reference_subfolder,
        stage=args.stage,
        destination_root=args.destination,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())