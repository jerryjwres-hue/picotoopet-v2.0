"""Verified shot-scoped Comfy LoadImage bindings on existing, local input bytes.

No image upload, copy, generation, approval, new model or Comfy POST.
All three Qwen LoadImage inputs must be explicitly accounted for.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

MAX_REFERENCE_ENTRIES = 12


def _load_image_slot(graph: dict, entry: dict) -> str:
    # 01. Use an exact node/type/name contract; never guess from image filenames.
    if (not isinstance(entry, dict)
        or set(entry) not in (
            {"node_id", "class_type", "input_name", "mode", "files"},
            {"node_id", "class_type", "input_name", "mode", "file"},
        )):
        raise ValueError("KEYFRAME_REFERENCE_BINDING_INVALID")
    node_id = entry["node_id"]
    if (not isinstance(node_id, str) or node_id not in graph
        or graph[node_id].get("class_type") != "LoadImage"
        or entry["class_type"] != "LoadImage"
        or entry["input_name"] != "image"
        or not isinstance(graph[node_id].get("inputs", {}).get("image"), str)):
        raise ValueError("KEYFRAME_REFERENCE_NODE_INVALID")
    return node_id


def _verify(root: Path, file: dict) -> tuple[str, dict]:
    # 02. Verify exact bytes in the existing Comfy input root, fail closed on
    #     links/traversal, and return provenance only (not a rights approval).
    if not isinstance(file, dict) or set(file) != {"filename", "sha256", "bytes"}:
        raise ValueError("KEYFRAME_REFERENCE_FILE_INVALID")
    filename, digest, count = file["filename"], file["sha256"], file["bytes"]
    if (not isinstance(filename, str) or not filename.lower().endswith(".png")
        or not isinstance(digest, str) or len(digest) != 64
        or any(ch not in "0123456789abcdef" for ch in digest)
        or type(count) is not int or not 0 < count <= 32 * 1024 * 1024):
        raise ValueError("KEYFRAME_REFERENCE_FILE_INVALID")
    # 03. Local import avoids cycle: collector reuses batch digest validators.
    from collect_local_keyframe_outputs import verified_output
    subfolder, _, basename = filename.rpartition("/")
    relative, data, dimensions = verified_output(root, subfolder, basename)
    if relative != filename or len(data) != count or hashlib.sha256(data).hexdigest() != digest:
        raise ValueError("KEYFRAME_REFERENCE_BYTES_MISMATCH")
    return filename, {"sha256": digest, "bytes": count, "dimensions": dimensions}


def resolve_reference_bindings(
    graph: dict, bindings: dict, frames: list[dict], input_root: Path | None,
) -> tuple[dict[str, dict[str, str]], list[dict]]:
    """Strict LoadImage coverage: per-shot composition + explicit pinned shared inputs."""
    load_images = {
        node_id for node_id, node in graph.items()
        if isinstance(node, dict) and node.get("class_type") == "LoadImage"
    }
    if not load_images and "reference_images" not in bindings:
        return {}, []
    entries = bindings.get("reference_images")
    if (not load_images or not isinstance(entries, list)
        or len(entries) != len(load_images) or len(entries) > MAX_REFERENCE_ENTRIES
        or input_root is None or not input_root.is_dir()):
        raise ValueError("KEYFRAME_REFERENCE_FULL_COVERAGE_REQUIRED")

    shot_ids = [frame["shot_id"] for frame in frames]
    if len(shot_ids) != 3 or len(set(shot_ids)) != 3:
        raise ValueError("KEYFRAME_REFERENCE_SHOT_SCOPE_INVALID")
    resolved: dict[str, dict[str, str]] = {}
    inventory = []
    for entry in entries:
        node_id = _load_image_slot(graph, entry)
        if node_id not in load_images or node_id in resolved:
            raise ValueError("KEYFRAME_REFERENCE_DUPLICATE_NODE")
        mode = entry["mode"]
        shots = {}
        recorded = {}
        if mode == "fixed" and "file" in entry:
            expected = graph[node_id]["inputs"]["image"]
            name, evidence = _verify(input_root, entry["file"])
            if name != expected:
                raise ValueError("KEYFRAME_REFERENCE_FIXED_SOURCE_CHANGED")
            for shot_id in shot_ids:
                shots[shot_id] = name
                recorded[shot_id] = evidence
        elif mode == "per_shot" and "files" in entry:
            files = entry["files"]
            if not isinstance(files, list) or len(files) != 3:
                raise ValueError("KEYFRAME_REFERENCE_SHOT_COVERAGE_INVALID")
            for shot_id, item in zip(shot_ids, files, strict=True):
                if (not isinstance(item, dict) or set(item) != {"shot_id", "filename", "sha256", "bytes"}
                    or item["shot_id"] != shot_id):
                    raise ValueError("KEYFRAME_REFERENCE_SHOT_COVERAGE_INVALID")
                name, evidence = _verify(
                    input_root, {key: item[key] for key in ("filename", "sha256", "bytes")}
                )
                if name in shots.values():
                    raise ValueError("KEYFRAME_REFERENCE_REUSED_PER_SHOT")
                shots[shot_id] = name
                recorded[shot_id] = evidence
        else:
            raise ValueError("KEYFRAME_REFERENCE_MODE_INVALID")
        resolved[node_id] = shots
        inventory.append({
            "node_id": node_id, "class_type": "LoadImage", "mode": mode,
            "shots": [{"shot_id": shot_id, "input_filename": shots[shot_id],
                       **recorded[shot_id]} for shot_id in shot_ids],
        })
    if set(resolved) != load_images:
        raise ValueError("KEYFRAME_REFERENCE_FULL_COVERAGE_REQUIRED")
    return resolved, sorted(inventory, key=lambda item: item["node_id"])
