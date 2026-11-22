"""Verified shot-scoped Comfy LoadImage bindings on existing, local input bytes.

No image upload, copy, generation, approval, new model or Comfy POST.
All three Qwen LoadImage inputs must be explicitly accounted for.
"""
from __future__ import annotations

import hashlib
import os
import stat
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


def jpeg_dimensions(data: bytes) -> tuple[int, int]:
    """Check bounded JPEG marker framing and SOF, not compressed pixel quality."""
    # 01. SOI, a valid Start-of-Frame, Start-of-Scan and terminal EOI
    #     must all exist. EXIF strings or a renamed PNG are not sufficient.
    if len(data) < 16 or not data.startswith(b"\xff\xd8") or not data.endswith(b"\xff\xd9"):
        raise ValueError("KEYFRAME_REFERENCE_JPEG_CONTAINER_INVALID")
    offset, dimensions, saw_scan = 2, None, False
    sof_markers = {
        0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
        0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
    }
    while offset < len(data) - 2:
        if data[offset] != 0xFF:
            raise ValueError("KEYFRAME_REFERENCE_JPEG_MARKER_INVALID")
        while offset < len(data) - 2 and data[offset] == 0xFF:
            offset += 1
        if offset >= len(data) - 2:
            raise ValueError("KEYFRAME_REFERENCE_JPEG_MARKER_INVALID")
        marker = data[offset]
        offset += 1
        if marker in (0x00, 0xD8, 0xD9, 0x01, *range(0xD0, 0xD8)):
            raise ValueError("KEYFRAME_REFERENCE_JPEG_MARKER_INVALID")
        if offset + 2 > len(data) - 2:
            raise ValueError("KEYFRAME_REFERENCE_JPEG_SEGMENT_INVALID")
        length = int.from_bytes(data[offset:offset + 2], "big")
        if length < 2 or offset + length > len(data) - 2:
            raise ValueError("KEYFRAME_REFERENCE_JPEG_SEGMENT_INVALID")
        payload = data[offset + 2:offset + length]
        if marker in sof_markers:
            if dimensions is not None or len(payload) < 9:
                raise ValueError("KEYFRAME_REFERENCE_JPEG_FRAME_INVALID")
            precision = payload[0]
            height = int.from_bytes(payload[1:3], "big")
            width = int.from_bytes(payload[3:5], "big")
            channels = payload[5]
            if (precision not in (8, 12) or not 1 <= height <= 8192
                or not 1 <= width <= 8192 or channels not in (1, 3, 4)
                or len(payload) != 6 + 3 * channels):
                raise ValueError("KEYFRAME_REFERENCE_JPEG_FRAME_INVALID")
            dimensions = width, height
        if marker == 0xDA:
            if dimensions is None or len(payload) < 6:
                raise ValueError("KEYFRAME_REFERENCE_JPEG_SCAN_INVALID")
            saw_scan = True
            # 02. Entropy-coded bytes are opaque; do not decode, interpret,
            #     or claim pixel identity from this structural inspection.
            break
        offset += length
    if dimensions is None or not saw_scan:
        raise ValueError("KEYFRAME_REFERENCE_JPEG_INCOMPLETE")
    return dimensions


def _verified_jpeg_input(root: Path, filename: str) -> tuple[str, bytes, tuple[int, int]]:
    """Reuse the existing Comfy output path guard without requiring PNG suffix."""
    # 03. Explicitly check each path component and the open descriptor;
    #     never resolve a symlink or follow relative parent traversal.
    from collect_local_keyframe_outputs import MAX_IMAGE_BYTES, safe_components
    pieces = safe_components(filename, filename=False)
    base = root.absolute()
    if not base.is_dir() or base.is_symlink():
        raise ValueError("KEYFRAME_REFERENCE_ROOT_INVALID")
    for index in range(1, len(pieces)):
        parent = base.joinpath(*pieces[:index])
        if parent.is_symlink() or not parent.is_dir():
            raise ValueError("KEYFRAME_REFERENCE_PARENT_INVALID")
    path = base.joinpath(*pieces)
    if path.is_symlink():
        raise ValueError("KEYFRAME_REFERENCE_SYMLINK_DENIED")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= MAX_IMAGE_BYTES:
            raise ValueError("KEYFRAME_REFERENCE_FILE_INVALID")
        data = stream.read(MAX_IMAGE_BYTES + 1)
        after = os.fstat(stream.fileno())
        if (len(data) != before.st_size or len(data) > MAX_IMAGE_BYTES
            or (before.st_ino, before.st_dev, before.st_size, before.st_mtime_ns)
               != (after.st_ino, after.st_dev, after.st_size, after.st_mtime_ns)):
            raise ValueError("KEYFRAME_REFERENCE_FILE_CHANGED")
    return filename, data, jpeg_dimensions(data)


def _verify(root: Path, file: dict) -> tuple[str, dict]:
    # 02. Verify exact bytes in the existing Comfy input root, fail closed on
    #     links/traversal, and return provenance only (not a rights approval).
    if not isinstance(file, dict) or set(file) != {"filename", "sha256", "bytes"}:
        raise ValueError("KEYFRAME_REFERENCE_FILE_INVALID")
    filename, digest, count = file["filename"], file["sha256"], file["bytes"]
    if (not isinstance(filename, str) or not filename.lower().endswith((".png", ".jpg", ".jpeg"))
        or not isinstance(digest, str) or len(digest) != 64
        or any(ch not in "0123456789abcdef" for ch in digest)
        or type(count) is not int or not 0 < count <= 32 * 1024 * 1024):
        raise ValueError("KEYFRAME_REFERENCE_FILE_INVALID")
    # 03. Local import avoids cycle: collector reuses batch digest validators.
    from collect_local_keyframe_outputs import verified_output
    subfolder, _, basename = filename.rpartition("/")
    if filename.lower().endswith(".png"):
        relative, data, dimensions = verified_output(root, subfolder, basename)
    else:
        relative, data, dimensions = _verified_jpeg_input(root, filename)
    if relative != filename or len(data) != count or hashlib.sha256(data).hexdigest() != digest:
        raise ValueError("KEYFRAME_REFERENCE_BYTES_MISMATCH")
    return filename, {"sha256": digest, "bytes": count, "dimensions": dimensions,
                      "format": "jpeg" if filename.lower().endswith((".jpg", ".jpeg")) else "png",
                      "pixels_decoded": False}


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
