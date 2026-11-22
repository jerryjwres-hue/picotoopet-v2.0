"""Recover an exact historical ComfyUI still-image graph; never enqueue or execute it.

This is a local evidence adapter, not a renderer or a new workflow authority.
The exported graph can contain private prompts/asset names; keep it on Windows.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path
from uuid import UUID

MAX_HISTORY_BYTES = 16 * 1024 * 1024
MAX_NODES = 512
MAX_INPUTS = 256
COMFY_ORIGIN = "http://127.0.0.1:8188"
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")
SLOT_NAMES = frozenset({
    "text", "image", "seed", "noise_seed", "width", "height",
    "steps", "cfg", "filename_prefix",
})
MODEL_NAMES = frozenset({
    "unet_name", "clip_name", "clip_name1", "clip_name2",
    "vae_name", "ckpt_name", "lora_name", "model_name",
})


def unique_object(pairs: list[tuple[str, object]]) -> dict:
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("HISTORY_DUPLICATE_KEY")
        result[key] = value
    return result


def reject_constant(_value: str) -> None:
    raise ValueError("HISTORY_NONFINITE_JSON")


def parse_history(data: bytes) -> dict:
    if not data or len(data) > MAX_HISTORY_BYTES:
        raise ValueError("HISTORY_SIZE_INVALID")
    value = json.loads(
        data.decode("utf-8-sig"),
        object_pairs_hook=unique_object,
        parse_constant=reject_constant,
    )
    if not isinstance(value, dict):
        raise ValueError("HISTORY_OBJECT_REQUIRED")
    return value


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def prompt_identity(value: str) -> str:
    parsed = UUID(value)
    if str(parsed) != value or parsed.int == 0:
        raise ValueError("HISTORY_PROMPT_ID_INVALID")
    return value


class NoRedirect(urllib.request.HTTPRedirectHandler):
    # 01. Local history GET only: no proxy, redirect, arbitrary URL or POST.
    def redirect_request(self, *_args, **_kwargs):
        raise ValueError("HISTORY_REDIRECT_DENIED")


def fetch_history(prompt_id: str) -> bytes:
    prompt_identity(prompt_id)
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), NoRedirect()
    )
    request = urllib.request.Request(
        f"{COMFY_ORIGIN}/history/{prompt_id}",
        headers={"Accept": "application/json"},
        method="GET",
    )
    with opener.open(request, timeout=10) as response:
        return response.read(MAX_HISTORY_BYTES + 1)


def recover(history: dict, prompt_id: str) -> tuple[bytes, dict]:
    """Extract unchanged graph and bounded evidence; no model/asset trust granted."""
    prompt_identity(prompt_id)
    entry = history.get(prompt_id)
    if not isinstance(entry, dict):
        raise ValueError("HISTORY_EXACT_PROMPT_MISSING")
    status = entry.get("status")
    prompt = entry.get("prompt")
    if (
        not isinstance(status, dict)
        or status.get("status_str") != "success"
        or status.get("completed") is not True
    ):
        raise ValueError("HISTORY_NOT_SUCCESSFUL")
    if not isinstance(prompt, list) or len(prompt) < 3 or prompt[1] != prompt_id:
        raise ValueError("HISTORY_PROMPT_ID_MISMATCH")
    graph = prompt[2]
    if not isinstance(graph, dict) or not 1 <= len(graph) <= MAX_NODES:
        raise ValueError("HISTORY_GRAPH_INVALID")

    # 02. Inventory exact graph structure; do not infer or rewrite bindings.
    inventory = []
    for node_id, node in sorted(graph.items()):
        if (
            not isinstance(node_id, str)
            or not 1 <= len(node_id) <= 128
            or not isinstance(node, dict)
            or not isinstance(node.get("class_type"), str)
            or not 1 <= len(node["class_type"]) <= 160
            or not isinstance(node.get("inputs"), dict)
            or len(node["inputs"]) > MAX_INPUTS
        ):
            raise ValueError("HISTORY_NODE_INVALID")
        inputs = node["inputs"]
        selectors = {
            key: value for key, value in inputs.items()
            if key in MODEL_NAMES and isinstance(value, str)
            and 1 <= len(value) <= 512
        }
        inventory.append({
            "node_id": node_id,
            "class_type": node["class_type"],
            "candidate_input_slots": sorted(key for key in inputs if key in SLOT_NAMES),
            "declared_model_selectors": selectors,
        })

    # 03. Require a recorded image output, not a video or a mere queued prompt.
    #     History alone cannot prove that those bytes still exist or are suitable.
    outputs = entry.get("outputs")
    if not isinstance(outputs, dict):
        raise ValueError("HISTORY_IMAGE_OUTPUT_REQUIRED")
    image_count = 0
    for node_id, output in outputs.items():
        if node_id not in graph or not isinstance(output, dict):
            raise ValueError("HISTORY_OUTPUT_NODE_INVALID")
        images = output.get("images", [])
        if not isinstance(images, list):
            raise ValueError("HISTORY_IMAGE_OUTPUT_INVALID")
        for image in images:
            if (
                isinstance(image, dict)
                and image.get("type") == "output"
                and isinstance(image.get("filename"), str)
                and image["filename"].lower().endswith(IMAGE_SUFFIXES)
            ):
                image_count += 1
    if not image_count:
        raise ValueError("HISTORY_IMAGE_OUTPUT_REQUIRED")

    data = canonical_bytes(graph)
    manifest = {
        "schema": "picotoo.local-keyframe-workflow-recovery.v1",
        "prompt_id": prompt_id,
        "graph_sha256": hashlib.sha256(data).hexdigest(),
        "graph_file": "workflow_api.json",
        "node_count": len(graph),
        "historical_image_output_count": image_count,
        "node_inventory": inventory,
        "history_status": "RECORDED_SUCCESS",
        "image_bytes_verified": False,
        "model_bytes_verified": False,
        "binding_reviewed": False,
        "workflow_registered": False,
        "production_authorized": False,
        "gpu_post": 0,
        "next_state": "UNTRUSTED_CANDIDATE_REQUIRES_LOCAL_BINDING_REVIEW",
    }
    return data, manifest


def export_candidate(directory: Path, data: bytes, manifest: dict) -> None:
    # 04. Write only to an explicitly chosen new local folder; never overwrite.
    directory.mkdir(parents=False, exist_ok=False)
    with (directory / "workflow_api.json").open("xb") as stream:
        stream.write(data)
    # Manifest last: absent manifest means interrupted/incomplete recovery.
    with (directory / "recovery_manifest.json").open("xb") as stream:
        stream.write(canonical_bytes(manifest))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompt-id")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--history-file", type=Path)
    source.add_argument("--live-history", action="store_true")
    source.add_argument("--png-file", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.png_file is not None:
            if args.prompt_id is not None:
                raise ValueError("PNG_EMBEDDED_NO_HISTORY_ID")
            # Source is one explicit existing PNG: never manufacture a
            # synthetic success or history entry from embedded metadata.
            from comfy_png_embedded_evidence import recover_png_file
            data, manifest = recover_png_file(args.png_file)
        else:
            if args.prompt_id is None:
                raise ValueError("HISTORY_PROMPT_ID_REQUIRED")
            prompt_identity(args.prompt_id)
            if args.history_file is not None:
                with args.history_file.open("rb") as stream:
                    raw = stream.read(MAX_HISTORY_BYTES + 1)
            else:
                raw = fetch_history(args.prompt_id)
            data, manifest = recover(parse_history(raw), args.prompt_id)
        export_candidate(args.output_dir, data, manifest)
    except (ValueError, OSError, TypeError, RecursionError, OverflowError):
        # No paths, prompt bodies or private filenames are printed into logs.
        print("KEYFRAME_WORKFLOW_RECOVERY=UNVERIFIED; GPU_POST=0", file=sys.stderr)
        return 1
    print("KEYFRAME_WORKFLOW_RECOVERY=CANDIDATE; GPU_POST=0")
    print(f"GRAPH_SHA256={manifest['graph_sha256']}")
    print("PRODUCTION_AUTHORIZED=FALSE; KEEP_EXPORT_LOCAL=TRUE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
