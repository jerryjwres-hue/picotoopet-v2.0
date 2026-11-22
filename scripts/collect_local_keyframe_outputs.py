"""Read-only evidence collector for three already-completed local ComfyUI keyframes.

This tool never submits prompts, selects a preferred frame, changes the generated
images, grants image rights, creates reference approvals, or starts a Worker/GPU.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import struct
import sys
import zlib
from pathlib import Path, PurePosixPath

from prepare_local_keyframe_batch import read_bounded, require_digest
from recover_comfy_keyframe_workflow import (
    canonical_bytes, fetch_history, parse_history, prompt_identity,
)

MAX_IMAGE_BYTES = 32 * 1024 * 1024
MAX_CANDIDATES_PER_SHOT = 32
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def file_sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def png_chunks_checked(data: bytes) -> tuple[int, int]:
    """Validate PNG container boundaries/CRCs, NOT pixel decoding or aesthetics."""
    if not data.startswith(PNG_SIGNATURE) or len(data) > MAX_IMAGE_BYTES:
        raise ValueError("CANDIDATE_PNG_INVALID")
    offset, dimensions, seen_idat, seen_iend = 8, None, False, False
    while offset < len(data):
        if offset + 12 > len(data):
            raise ValueError("CANDIDATE_PNG_TRUNCATED")
        length = struct.unpack_from(">I", data, offset)[0]
        chunk = data[offset + 4:offset + 8]
        if length > MAX_IMAGE_BYTES or offset + 12 + length > len(data):
            raise ValueError("CANDIDATE_PNG_CHUNK_INVALID")
        payload = data[offset + 8:offset + 8 + length]
        crc = struct.unpack_from(">I", data, offset + 8 + length)[0]
        if zlib.crc32(chunk + payload) & 0xffffffff != crc:
            raise ValueError("CANDIDATE_PNG_CRC_INVALID")
        if dimensions is None:
            if chunk != b"IHDR" or length != 13:
                raise ValueError("CANDIDATE_PNG_IHDR_MISSING")
            width, height, bit_depth, color_type, compression, filtering, interlace = (
                struct.unpack(">IIBBBBB", payload)
            )
            if (not 1 <= width <= 8192 or not 1 <= height <= 8192
                or (bit_depth, color_type) not in {
                    (8, 0), (8, 2), (8, 3), (8, 4), (8, 6),
                    (16, 0), (16, 2), (16, 4), (16, 6),
                    (1, 0), (2, 0), (4, 0), (1, 3), (2, 3), (4, 3),
                }
                or compression != 0 or filtering != 0 or interlace not in (0, 1)):
                raise ValueError("CANDIDATE_PNG_DIMENSIONS_INVALID")
            dimensions = (width, height)
        elif chunk == b"IHDR" or chunk == b"acTL" or chunk == b"fcTL" or chunk == b"fdAT":
            # 01. Reject animated assets and multiple image headers at this seam.
            raise ValueError("CANDIDATE_PNG_MULTIFRAME_DENIED")
        elif chunk == b"IDAT":
            seen_idat = True
        elif chunk == b"IEND":
            if length != 0 or seen_iend or not seen_idat or offset + 12 != len(data):
                raise ValueError("CANDIDATE_PNG_IEND_INVALID")
            seen_iend = True
        offset += 12 + length
        if seen_iend:
            break
    if dimensions is None or not seen_idat or not seen_iend:
        raise ValueError("CANDIDATE_PNG_INCOMPLETE")
    return dimensions


def safe_components(value: str, *, filename: bool) -> list[str]:
    if not isinstance(value, str) or len(value) > 240 or "\\" in value or ":" in value:
        raise ValueError("CANDIDATE_OUTPUT_PATH_INVALID")
    if filename and ("/" in value or not value.lower().endswith(".png")):
        raise ValueError("CANDIDATE_OUTPUT_FILE_INVALID")
    if not value and not filename:
        return []
    parts = PurePosixPath(value).parts
    if (value.startswith("/") or not parts or any(
        p in ("", ".", "..") or p.endswith(" ") or p.endswith(".")
        or any(ord(ch) < 32 for ch in p) for p in parts
    )):
        raise ValueError("CANDIDATE_OUTPUT_PATH_INVALID")
    if PurePosixPath(*parts).as_posix() != value:
        raise ValueError("CANDIDATE_OUTPUT_PATH_INVALID")
    return list(parts)


def verified_output(output_root: Path, subfolder: str, filename: str) -> tuple[str, bytes, tuple[int, int]]:
    """Pin file descriptor and reject links; this is observation, not immutable staging."""
    parts = safe_components(subfolder, filename=False) + safe_components(filename, filename=True)
    root = output_root.absolute()
    if not root.is_dir() or root.is_symlink():
        raise ValueError("CANDIDATE_ROOT_INVALID")
    for index in range(1, len(parts)):
        parent = root.joinpath(*parts[:index])
        if parent.is_symlink() or not parent.is_dir():
            raise ValueError("CANDIDATE_PARENT_INVALID")
    source = root.joinpath(*parts)
    if source.is_symlink():
        raise ValueError("CANDIDATE_SYMLINK_DENIED")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(source, flags)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= MAX_IMAGE_BYTES:
            raise ValueError("CANDIDATE_FILE_INVALID")
        data = stream.read(MAX_IMAGE_BYTES + 1)
        after = os.fstat(stream.fileno())
        if (len(data) != before.st_size or len(data) > MAX_IMAGE_BYTES
            or (before.st_ino, before.st_dev, before.st_size, before.st_mtime_ns)
               != (after.st_ino, after.st_dev, after.st_size, after.st_mtime_ns)):
            raise ValueError("CANDIDATE_FILE_CHANGED")
    return PurePosixPath(*parts).as_posix(), data, png_chunks_checked(data)


def candidate_history(history: dict, prompt_id: str, expected_graph_sha: str) -> list[dict]:
    """Require exact prompt-graph identity and completed history, not name similarity."""
    prompt_identity(prompt_id)
    entry = history.get(prompt_id)
    if not isinstance(entry, dict) or entry.get("status") != {
        "status_str": "success", "completed": True
    }:
        # 02. Histories containing extra diagnostic status keys are valid too.
        if not isinstance(entry, dict) or not isinstance(entry.get("status"), dict):
            raise ValueError("CANDIDATE_HISTORY_INVALID")
        if (entry["status"].get("status_str") != "success"
            or entry["status"].get("completed") is not True):
            raise ValueError("CANDIDATE_HISTORY_NOT_COMPLETE")
    prompt = entry.get("prompt")
    if (not isinstance(prompt, list) or len(prompt) < 3
        or prompt[1] != prompt_id or not isinstance(prompt[2], dict)
        or file_sha(canonical_bytes(prompt[2])) != expected_graph_sha):
        raise ValueError("CANDIDATE_GRAPH_MISMATCH")
    outputs = entry.get("outputs")
    if not isinstance(outputs, dict):
        raise ValueError("CANDIDATE_HISTORY_OUTPUT_MISSING")
    images = []
    for node_id, output in outputs.items():
        if node_id not in prompt[2] or not isinstance(output, dict):
            raise ValueError("CANDIDATE_HISTORY_NODE_INVALID")
        for item in output.get("images", []):
            if (not isinstance(item, dict) or item.get("type") != "output"
                or not isinstance(item.get("filename"), str)
                or not isinstance(item.get("subfolder", ""), str)):
                raise ValueError("CANDIDATE_HISTORY_IMAGE_INVALID")
            images.append({"node_id": node_id, "filename": item["filename"],
                           "subfolder": item.get("subfolder", "")})
    if not 1 <= len(images) <= MAX_CANDIDATES_PER_SHOT:
        raise ValueError("CANDIDATE_IMAGE_COUNT_INVALID")
    return images


def collect(batch: dict, batch_dir: Path, identities: dict,
            histories: dict[str, dict], output_root: Path) -> dict:
    """Make a bounded review manifest, never a selected or approved reference."""
    if (batch.get("schema") != "picotoo.local-keyframe-batch-dry-run.v1"
        or batch.get("production_authorized") is not False
        or batch.get("gpu_post") != 0 or batch.get("source_inputs_verified") is not False
        or not isinstance(batch.get("shots"), list) or len(batch["shots"]) != 3
        or identities.get("schema") != "picotoo.keyframe-prompt-identities.v1"
        or not isinstance(identities.get("shots"), list) or len(identities["shots"]) != 3):
        raise ValueError("CANDIDATE_BATCH_INVALID")
    require_digest(batch["creative_package_sha256"])
    require_digest(batch["source_graph_sha256"])
    require_digest(batch["keyframe_kit_digest"])
    require_digest(batch["slot_map_sha256"])
    shot_ids = [s["shot_id"] for s in batch["shots"]]
    if (len(set(shot_ids)) != 3
        or set(shot_ids) != {s["shot_id"] for s in identities["shots"]}):
        raise ValueError("CANDIDATE_SHOT_COVERAGE_INVALID")
    prompt_ids = [s["prompt_id"] for s in identities["shots"]]
    if len(set(prompt_ids)) != 3:
        raise ValueError("CANDIDATE_PROMPT_DUPLICATED")
    index = {s["shot_id"]: s["prompt_id"] for s in identities["shots"]}
    used_paths, used_hashes, output_records = set(), set(), []
    for order, shot in enumerate(batch["shots"], 1):
        if shot.get("order") != order or not isinstance(shot.get("graph_file"), str):
            raise ValueError("CANDIDATE_SHOT_ORDER_INVALID")
        expected_filename = f"{order:02d}-{shot['shot_id']}.json"
        if shot["graph_file"] != expected_filename:
            raise ValueError("CANDIDATE_GRAPH_PATH_INVALID")
        expected_sha = require_digest(shot["graph_sha256"])
        if file_sha(read_bounded(batch_dir / expected_filename)) != expected_sha:
            raise ValueError("CANDIDATE_PREPARED_GRAPH_TAMPERED")
        prompt_id = prompt_identity(index[shot["shot_id"]])
        entries = candidate_history(histories[prompt_id], prompt_id, expected_sha)
        candidates = []
        for image in entries:
            path, data, (width, height) = verified_output(
                output_root, image["subfolder"], image["filename"]
            )
            digest = file_sha(data)
            if path in used_paths or digest in used_hashes:
                raise ValueError("CANDIDATE_DUPLICATE_IMAGE_ACROSS_SHOTS")
            used_paths.add(path)
            used_hashes.add(digest)
            candidates.append({
                "output_relative_path": path, "sha256": digest,
                "bytes": len(data), "width": width, "height": height,
                "comfy_output_node": image["node_id"], "format": "png",
                "image_container_crc_verified": True,
                "pixels_decoded": False, "visual_review": "UNREVIEWED",
            })
        output_records.append({
            "shot_id": shot["shot_id"], "order": order, "prompt_id": prompt_id,
            "prepared_graph_sha256": expected_sha, "candidates": candidates,
            "selected_reference": None,
        })
    return {
        "schema": "picotoo.local-keyframe-output-candidates.v1",
        "creative_package_id": batch["creative_package_id"],
        "creative_package_sha256": batch["creative_package_sha256"],
        "keyframe_kit_digest": batch["keyframe_kit_digest"],
        "batch_manifest_sha256": file_sha(canonical_bytes(batch)),
        "shots": output_records,
        "recorded_image_bytes_observed": True,
        "candidate_files_staged": False,
        "review_status": "NEEDS_HUMAN_REVIEW",
        "source_rights_confirmed": False,
        "reference_approved": False,
        "gpu_post": 0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-dir", type=Path, required=True)
    parser.add_argument("--prompt-ids", type=Path, required=True)
    parser.add_argument("--history-dir", type=Path)
    parser.add_argument("--live-history", action="store_true")
    parser.add_argument("--comfy-output-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.live_history == (args.history_dir is not None):
        parser.error("Choose exactly one history source.")
    try:
        batch = parse_history(read_bounded(args.batch_dir / "batch_manifest.json"))
        identities = parse_history(read_bounded(args.prompt_ids))
        ids = [prompt_identity(item["prompt_id"]) for item in identities["shots"]]
        histories = {
            key: parse_history(
                fetch_history(key) if args.live_history
                else read_bounded(args.history_dir / f"{key}.json")
            ) for key in ids
        }
        result = collect(batch, args.batch_dir, identities, histories, args.comfy_output_root)
        # 03. No image is copied or imported into approved Core reference storage.
        args.output_dir.mkdir(parents=False, exist_ok=False)
        with (args.output_dir / "candidate_manifest.json").open("xb") as output:
            output.write(canonical_bytes(result))
    except (KeyError, IndexError, ValueError, OSError, TypeError, OverflowError):
        print("KEYFRAME_CANDIDATES=UNVERIFIED; GPU_POST=0", file=sys.stderr)
        return 1
    print("KEYFRAME_CANDIDATES=OBSERVED; HUMAN_REVIEW=REQUIRED; GPU_POST=0")
    print("REFERENCE_APPROVED=FALSE; SOURCE_RIGHTS_CONFIRMED=FALSE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
