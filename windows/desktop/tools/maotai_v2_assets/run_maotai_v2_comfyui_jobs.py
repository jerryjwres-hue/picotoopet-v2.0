from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
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
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
_PNG_SIGNATURE  = b"\x89PNG\r\n\x1a\n"


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
    """读取显式 node/input 绑定；不猜节点 ID，也不注入隐藏默认绑定。"""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("ComfyUI bindings JSON must be an object")
    _validate_required_bindings(payload)
    return payload


def apply_job_to_workflow(
    workflow: dict[str, Any],
    bindings: dict[str, Any],
    job: dict[str, Any],
    *,
    seed: int,
    filename_prefix: str,
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
        _set_binding(rendered, reference_binding, reference_name, "reference_image")

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
        self.server_url             = normalize_server_url(server_url)
        self.request_timeout_seconds = max(1.0, float(request_timeout_seconds))
        self.client_id              = uuid.uuid4().hex

    def object_info(self) -> dict[str, Any]:
        payload = self._request_json("GET", "/object_info")
        if not isinstance(payload, dict):
            raise ValueError("ComfyUI /object_info did not return an object")
        return payload

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
    bindings_path: Path | str,
    incoming_root: Path | str,
    *,
    server_url: str = "http://127.0.0.1:8188",
    base_seed: int = 230815,
    prompt_timeout_seconds: float = 900.0,
    stage: bool = False,
    destination_root: Path | str | None = None,
) -> dict[str, Any]:
    """串行生成完整 manifest 集合；全部输出验证通过前绝不触碰正式 V2 目录。"""
    plan       = _load_json_object(plan_path, "art plan")
    workflow   = _load_json_object(workflow_path, "ComfyUI workflow")
    bindings   = load_bindings(bindings_path)
    incoming   = Path(incoming_root)
    jobs       = plan.get("jobs")
    if not isinstance(jobs, list) or not jobs:
        raise ValueError("art plan must contain non-empty jobs")

    incoming.mkdir(parents=True, exist_ok=True)
    existing_pngs = sorted(path.name for path in incoming.glob("*.png"))
    if existing_pngs:
        raise ValueError(
            "incoming directory must not contain stale PNGs before a production run: "
            + ", ".join(existing_pngs[:5])
        )

    client = ComfyUiLocalClient(server_url)
    _verify_optional_rmbg(client.object_info(), workflow, bindings)

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
    parser.add_argument("--bindings", type=Path, required=True)
    parser.add_argument("--incoming", type=Path, required=True)
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
        stage=args.stage,
        destination_root=args.destination,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
