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
import urllib.request
import zlib
from pathlib import Path, PurePosixPath

from prepare_local_keyframe_batch import ID, read_bounded, require_digest
from recover_comfy_keyframe_workflow import (
    COMFY_ORIGIN, MAX_HISTORY_BYTES, NoRedirect, canonical_bytes,
    fetch_history, parse_history, prompt_identity,
)

MAX_IMAGE_BYTES = 32 * 1024 * 1024
MAX_CANDIDATES_PER_SHOT = 32
MAX_HISTORY_ITEMS = 2000
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


def fetch_recent_history() -> bytes:
    """One fixed local GET only; never enqueue, mutate, or browse arbitrary URLs."""
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), NoRedirect()
    )
    request = urllib.request.Request(
        f"{COMFY_ORIGIN}/history",
        headers={"Accept": "application/json"}, method="GET",
    )
    with opener.open(request, timeout=10) as response:
        return response.read(MAX_HISTORY_BYTES + 1)


def discover_exact_prompt_ids(batch: dict, batch_dir: Path,
                              listing: dict) -> tuple[dict, dict[str, dict]]:
    """Discover unique completed prompt IDs by byte-exact frozen graph digest.

    01. Ambiguity never selects a 'newest' picture; callers must use explicit
        prompt IDs when the same graph has been executed more than once.
    02. Failed, incomplete, or unrelated history entries do not grant a match.
    """
    shots = batch.get("shots")
    if not isinstance(shots, list) or len(shots) != 3:
        raise ValueError("CANDIDATE_DISCOVERY_BATCH_INVALID")
    if not isinstance(listing, dict) or len(listing) > MAX_HISTORY_ITEMS:
        raise ValueError("CANDIDATE_DISCOVERY_HISTORY_SIZE_INVALID")
    expected = {}
    for order, shot in enumerate(shots, 1):
        shot_id, graph_file = shot.get("shot_id"), shot.get("graph_file")
        if (not isinstance(shot_id, str)
            or graph_file != f"{order:02d}-{shot_id}.json"):
            raise ValueError("CANDIDATE_DISCOVERY_GRAPH_INVALID")
        digest = require_digest(shot["graph_sha256"])
        if digest in expected or file_sha(read_bounded(batch_dir / graph_file)) != digest:
            raise ValueError("CANDIDATE_DISCOVERY_GRAPH_INVALID")
        expected[digest] = shot_id

    matched: dict[str, list[tuple[str, dict]]] = {shot_id: [] for shot_id in expected.values()}
    for prompt_id, entry in listing.items():
        if not isinstance(entry, dict):
            continue
        try:
            prompt_identity(prompt_id)
        except (ValueError, TypeError, AttributeError):
            continue
        prompt = entry.get("prompt")
        if (not isinstance(prompt, list) or len(prompt) < 3
            or prompt[1] != prompt_id or not isinstance(prompt[2], dict)):
            continue
        digest = file_sha(canonical_bytes(prompt[2]))
        shot_id = expected.get(digest)
        if shot_id is None:
            continue
        try:
            candidate_history({prompt_id: entry}, prompt_id, digest)
        except (ValueError, TypeError, KeyError):
            continue
        matched[shot_id].append((prompt_id, entry))

    if any(len(matches) != 1 for matches in matched.values()):
        raise ValueError("CANDIDATE_DISCOVERY_AMBIGUOUS_OR_MISSING")
    identities = {"schema": "picotoo.keyframe-prompt-identities.v1",
                  "shots": [{"shot_id": shot["shot_id"],
                             "prompt_id": matched[shot["shot_id"]][0][0]}
                            for shot in shots]}
    histories = {entries[0][0]: {entries[0][0]: entries[0][1]}
                 for entries in matched.values()}
    return identities, histories


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


def collect_variant_snapshot(
    variants_root: Path, listing: dict, output_root: Path,
) -> tuple[list[tuple[str, dict]], dict]:
    """Match all bounded seed variants to exact completed Comfy graph bytes.

    This is CPU-only: no model call, no output-name guessing, no PNG copy.
    Existing collector contracts remain authoritative per variant and shot.
    """
    # 01. Only an explicit, ordinary prepared parent is eligible.
    root = variants_root.absolute()
    index_file = root / "variant_index.json"
    if (not root.is_dir() or root.is_symlink() or index_file.is_symlink()
        or not index_file.is_file()):
        raise ValueError("CANDIDATE_VARIANT_ROOT_INVALID")
    source = read_bounded(index_file)
    index = parse_history(source)
    entries = index.get("variants")
    count = index.get("variant_count")
    if (index.get("schema") != "picotoo.local-keyframe-variant-index.v1"
        or type(count) is not int or not 2 <= count <= 8
        or not isinstance(entries, list) or len(entries) != count
        or index.get("source_inputs_verified") is not False
        or index.get("production_authorized") is not False
        or index.get("gpu_post") != 0
        or not isinstance(listing, dict) or len(listing) > MAX_HISTORY_ITEMS):
        raise ValueError("CANDIDATE_VARIANT_INDEX_INVALID")
    package_digest = require_digest(index["creative_package_sha256"])
    kit_digest = require_digest(index["keyframe_kit_digest"])
    seen_versions: set[int] = set()
    seen_images: set[str] = set()
    seen_paths: set[str] = set()
    seen_prompts: set[str] = set()
    prepared: list[tuple[str, dict]] = []
    index_rows = []
    first_variant = None
    source_contract = None
    total_candidates = 0
    for entry in entries:
        # 02. Never join unchecked JSON paths or infer a variant number
        #     from a candidate filename. Use only the exact frozen index.
        if not isinstance(entry, dict) or set(entry) != {
            "variant", "relative_directory", "batch_manifest_sha256", "shot_count"
        }:
            raise ValueError("CANDIDATE_VARIANT_ENTRY_INVALID")
        variant = entry["variant"]
        if (type(variant) is not int or not 0 <= variant <= 10000
            or variant in seen_versions or type(entry["shot_count"]) is not int
            or entry["shot_count"] != 3
            or entry["relative_directory"] != f"v{variant:04d}"):
            raise ValueError("CANDIDATE_VARIANT_SCOPE_INVALID")
        if first_variant is None:
            first_variant = variant
        if variant != first_variant + len(prepared):
            raise ValueError("CANDIDATE_VARIANT_ORDER_INVALID")
        seen_versions.add(variant)
        folder_name = f"v{variant:04d}"
        folder = root / folder_name
        batch_path = folder / "batch_manifest.json"
        if (not folder.is_dir() or folder.is_symlink()
            or batch_path.is_symlink() or not batch_path.is_file()):
            raise ValueError("CANDIDATE_VARIANT_BATCH_MISSING")
        batch_bytes = read_bounded(batch_path)
        if file_sha(batch_bytes) != require_digest(entry["batch_manifest_sha256"]):
            raise ValueError("CANDIDATE_VARIANT_BATCH_DIGEST_MISMATCH")
        batch = parse_history(batch_bytes)
        if (canonical_bytes(batch) != batch_bytes
            or batch.get("schema") != "picotoo.local-keyframe-batch-dry-run.v1"
            or batch.get("variant") != variant
            or batch.get("creative_package_sha256") != package_digest
            or batch.get("keyframe_kit_digest") != kit_digest
            or batch.get("source_inputs_verified") is not False
            or batch.get("production_authorized") is not False
            or batch.get("gpu_post") != 0):
            raise ValueError("CANDIDATE_VARIANT_BATCH_INVALID")
        # 03. Every variant must share one source graph, slot map and Core
        #     creative-package identity. No arbitrary graph path, link,
        #     parent traversal or extra shots can join this offline batch.
        contract = (
            batch.get("creative_package_id"),
            batch.get("source_graph_sha256"),
            batch.get("slot_map_sha256"),
        )
        if (not isinstance(contract[0], str) or not contract[0]
            or any(require_digest(value) != value for value in contract[1:])):
            raise ValueError("CANDIDATE_VARIANT_SOURCE_IDENTITY_INVALID")
        if source_contract is None:
            source_contract = contract
        elif contract != source_contract:
            raise ValueError("CANDIDATE_VARIANT_SOURCE_CONFLICT")
        shots = batch.get("shots")
        if not isinstance(shots, list) or len(shots) != 3:
            raise ValueError("CANDIDATE_VARIANT_SHOT_COVERAGE_INVALID")
        for order, shot in enumerate(shots, 1):
            if not isinstance(shot, dict):
                raise ValueError("CANDIDATE_VARIANT_SHOT_INVALID")
            shot_id, name = shot.get("shot_id"), shot.get("graph_file")
            if (not isinstance(shot_id, str) or not ID.fullmatch(shot_id)
                or name != f"{order:02d}-{shot_id}.json"):
                raise ValueError("CANDIDATE_VARIANT_GRAPH_PATH_INVALID")
            graph_path = folder / name
            if graph_path.is_symlink() or not graph_path.is_file():
                raise ValueError("CANDIDATE_VARIANT_GRAPH_FILE_INVALID")
        # 04. Match recorded successful Comfy history by exact graph SHA,
        #     reuse the verified output bytes/CRC/shot-scope collector, and
        #     preserve each candidate's own prompt ID and graph identity.
        ids, histories = discover_exact_prompt_ids(batch, folder, listing)
        result = collect(batch, folder, ids, histories, output_root)
        for shot in result["shots"]:
            prompt_id = shot["prompt_id"]
            if prompt_id in seen_prompts:
                raise ValueError("CANDIDATE_VARIANT_PROMPT_REUSED")
            seen_prompts.add(prompt_id)
            for candidate in shot["candidates"]:
                digest = candidate["sha256"]
                name = candidate["output_relative_path"].casefold()
                if digest in seen_images or name in seen_paths:
                    raise ValueError("CANDIDATE_VARIANT_IMAGE_REUSED")
                seen_images.add(digest)
                seen_paths.add(name)
                total_candidates += 1
                if total_candidates > 96:
                    raise ValueError("CANDIDATE_VARIANT_TOO_MANY_IMAGES")
        data = canonical_bytes(result)
        prepared.append((folder_name, result))
        index_rows.append({
            "variant": variant,
            "relative_directory": folder_name,
            "candidate_manifest_sha256": file_sha(data),
            "shot_count": 3,
        })
    # 05. This index only points to already-observed candidate reports.
    #     It never certifies real model quality, creative rights or a Job.
    report_index = {
        "schema": "picotoo.local-keyframe-observed-variant-index.v1",
        "creative_package_sha256": package_digest,
        "keyframe_kit_digest": kit_digest,
        "variant_count": count,
        "variants": index_rows,
        "source_rights_confirmed": False,
        "reference_approved": False,
        "gpu_post": 0,
    }
    return prepared, report_index


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    batch_source = parser.add_mutually_exclusive_group(required=True)
    batch_source.add_argument("--batch-dir", type=Path)
    batch_source.add_argument("--variants-root", type=Path)
    parser.add_argument("--prompt-ids", type=Path)
    history_source = parser.add_mutually_exclusive_group(required=True)
    history_source.add_argument("--history-dir", type=Path)
    history_source.add_argument("--live-history", action="store_true")
    history_source.add_argument("--history-snapshot", type=Path)
    history_source.add_argument("--live-history-scan", action="store_true")
    history_source.add_argument("--embedded-png-map", type=Path)
    parser.add_argument("--comfy-output-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    auto_discovery = args.history_snapshot is not None or args.live_history_scan
    embedded_mode = args.embedded_png_map is not None
    variant_mode = args.variants_root is not None
    if variant_mode and (args.history_snapshot is None or args.prompt_ids is not None):
        parser.error("Multi-seed collection requires one offline --history-snapshot.")
    if embedded_mode or auto_discovery:
        if args.prompt_ids is not None:
            parser.error("Embedded/auto mode cannot use --prompt-ids.")
    elif args.prompt_ids is None:
        parser.error("Explicit Comfy history requires --prompt-ids.")
    try:
        if variant_mode:
            # 06. One offline history snapshot resolves every variant.
            #     All 3xN images are checked BEFORE creating output files.
            listing = parse_history(read_bounded(args.history_snapshot))
            groups, index = collect_variant_snapshot(
                args.variants_root, listing, args.comfy_output_root
            )
            args.output_dir.mkdir(parents=False, exist_ok=False)
            for folder_name, result in groups:
                dest = args.output_dir / folder_name
                dest.mkdir(exist_ok=False)
                with (dest / "candidate_manifest.json").open("xb") as output:
                    output.write(canonical_bytes(result))
            # 07. Last-written index signifies completed export; each
            #     vNNNN/candidate_manifest.json can be opened in WPF.
            with (args.output_dir / "observed_variant_index.json").open("xb") as output:
                output.write(canonical_bytes(index))
            print(f"KEYFRAME_VARIANT_CANDIDATES=OBSERVED; VARIANTS={len(groups)}; GPU_POST=0")
            print("HUMAN_REVIEW=REQUIRED; REFERENCE_APPROVED=FALSE")
            return 0
        batch = parse_history(read_bounded(args.batch_dir / "batch_manifest.json"))
        if embedded_mode:
            # 01. No network, no fake Comfy history, no inferred output path.
            from offline_png_output_collector import collect_embedded_outputs
            selected = parse_history(read_bounded(args.embedded_png_map))
            result = collect_embedded_outputs(
                batch, args.batch_dir, selected, args.comfy_output_root
            )
        elif auto_discovery:
            listing = parse_history(
                fetch_recent_history() if args.live_history_scan
                else read_bounded(args.history_snapshot)
            )
            identities, histories = discover_exact_prompt_ids(
                batch, args.batch_dir, listing
            )
        else:
            identities = parse_history(read_bounded(args.prompt_ids))
            ids = [prompt_identity(item["prompt_id"]) for item in identities["shots"]]
            histories = {
                key: parse_history(
                    fetch_history(key) if args.live_history
                    else read_bounded(args.history_dir / f"{key}.json")
                ) for key in ids
            }
        if not embedded_mode:
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
