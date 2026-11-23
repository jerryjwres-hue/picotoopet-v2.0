"""Offline, read-only byte audit of six unapproved Qwen composition drafts.

This diagnostic never selects a candidate, approves a reference, changes a
Creative package, calls ComfyUI, or authorizes production GPU work.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import sys
from pathlib import Path

from scripts.comfy_png_embedded_evidence import MAX_PNG_BYTES, recover_embedded_png
from scripts.recover_comfy_keyframe_workflow import canonical_bytes, parse_history

MAX_JSON_BYTES = 4 * 1024 * 1024
SHOT_ID = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _regular_bytes(path: Path, maximum: int) -> bytes:
    # 01. Never follow symlinks, special files, or unbounded files.
    mode = path.lstat().st_mode
    if not stat.S_ISREG(mode):
        raise ValueError("COMPOSITION_REVIEW_FILE_TYPE_INVALID")
    with path.open("rb") as stream:
        raw = stream.read(maximum + 1)
    if not 0 < len(raw) <= maximum:
        raise ValueError("COMPOSITION_REVIEW_FILE_SIZE_INVALID")
    return raw


def _json(raw: bytes) -> dict:
    # Reject duplicate keys and NaN/Infinity instead of silently selecting a value.
    doc = parse_history(raw)
    if not isinstance(doc, dict):
        raise ValueError("COMPOSITION_REVIEW_DOCUMENT_INVALID")
    return doc


def _sha(value: object) -> str:
    if not isinstance(value, str) or not DIGEST.fullmatch(value):
        raise ValueError("COMPOSITION_REVIEW_DIGEST_INVALID")
    return value


def audit(bootstrap_dir: Path, review_dir: Path) -> dict:
    """Check exact graphs and image bytes without changing either directory."""
    # 02. Bounded explicit directories only; do not search outside them.
    if (not bootstrap_dir.is_dir() or bootstrap_dir.is_symlink()
        or not review_dir.is_dir() or review_dir.is_symlink()):
        raise ValueError("COMPOSITION_REVIEW_ROOT_INVALID")
    index_raw = _regular_bytes(bootstrap_dir / "variant_index.json", MAX_JSON_BYTES)
    index = _json(index_raw)
    variants = index.get("variants")
    if (index.get("schema") != "picotoo.local-composition-bootstrap-index.v1"
        or index.get("variant_count") != 2
        or not isinstance(variants, list) or len(variants) != 2
        or index.get("production_authorized") is not False
        or index.get("source_inputs_verified") is not False
        or index.get("gpu_post") != 0):
        raise ValueError("COMPOSITION_REVIEW_INDEX_INVALID")

    package_sha = _sha(index.get("creative_package_sha256"))
    kit_sha = _sha(index.get("keyframe_kit_digest"))
    seen_variants: set[int] = set()
    seen_png_hashes: set[str] = set()
    groups: dict[str, dict] = {}
    common_order: list[str] | None = None
    common_source: str | None = None

    for entry in variants:
        # 03. Require two exact variant directory names without path traversal.
        if not isinstance(entry, dict) or type(entry.get("variant")) is not int:
            raise ValueError("COMPOSITION_REVIEW_VARIANT_INVALID")
        variant = entry["variant"]
        folder_name = f"v{variant:04d}"
        if (not 0 <= variant <= 10000 or variant in seen_variants
            or entry.get("relative_directory") != folder_name
            or entry.get("shot_count") != 3):
            raise ValueError("COMPOSITION_REVIEW_VARIANT_INVALID")
        seen_variants.add(variant)
        folder = bootstrap_dir / folder_name
        if not folder.is_dir() or folder.is_symlink():
            raise ValueError("COMPOSITION_REVIEW_VARIANT_DIR_INVALID")
        manifest_raw = _regular_bytes(folder / "batch_manifest.json", MAX_JSON_BYTES)
        if _digest(manifest_raw) != _sha(entry.get("batch_manifest_sha256")):
            raise ValueError("COMPOSITION_REVIEW_MANIFEST_HASH_INVALID")
        manifest = _json(manifest_raw)
        shots = manifest.get("shots")
        if (manifest.get("schema") != "picotoo.local-composition-bootstrap-dry-run.v1"
            or manifest.get("variant") != variant
            or manifest.get("creative_package_sha256") != package_sha
            or manifest.get("keyframe_kit_digest") != kit_sha
            or not isinstance(shots, list) or len(shots) != 3
            or manifest.get("production_authorized") is not False
            or manifest.get("source_inputs_verified") is not False
            or manifest.get("reference_approved") is not False
            or manifest.get("workflow_registered") is not False
            or manifest.get("historical_composition_reused_as_guidance_only") is not True
            or manifest.get("distinct_shot_compositions_observed") is not False
            or manifest.get("source_render_intents_converted") is not False
            or manifest.get("source_profile_conversion_performed") is not False
            or manifest.get("target_geometry_verified") is not False
            or manifest.get("gpu_post") != 0):
            raise ValueError("COMPOSITION_REVIEW_MANIFEST_INVALID")
        source_sha = _sha(manifest.get("source_graph_sha256"))
        if common_source is not None and source_sha != common_source:
            raise ValueError("COMPOSITION_REVIEW_SOURCE_GRAPH_MISMATCH")
        common_source = source_sha
        orders: list[str] = []
        for order, shot in enumerate(shots, 1):
            # 04. Verify every image's embedded API graph against prepared JSON.
            if not isinstance(shot, dict) or not isinstance(shot.get("shot_id"), str):
                raise ValueError("COMPOSITION_REVIEW_SHOT_INVALID")
            shot_id = shot["shot_id"]
            if (not SHOT_ID.fullmatch(shot_id) or shot.get("order") != order
                or shot.get("graph_file") != f"{order:02d}-{shot_id}.json"
                or type(shot.get("seed")) is not int
                or not 0 <= shot["seed"] < 2**63
                or shot.get("human_visual_review") != "NOT_PERFORMED"
                or shot.get("generated_composition") is not None):
                raise ValueError("COMPOSITION_REVIEW_SHOT_INVALID")
            orders.append(shot_id)
            graph_raw = _regular_bytes(folder / shot["graph_file"], MAX_JSON_BYTES)
            graph_sha = _digest(graph_raw)
            if graph_sha != _sha(shot.get("graph_sha256")):
                raise ValueError("COMPOSITION_REVIEW_GRAPH_HASH_INVALID")
            png_name = f"{folder_name}_{shot_id}_shot{order}.png"
            png_raw = _regular_bytes(review_dir / png_name, MAX_PNG_BYTES)
            png_sha = _digest(png_raw)
            if png_sha in seen_png_hashes:
                raise ValueError("COMPOSITION_REVIEW_DUPLICATE_IMAGE_BYTES")
            seen_png_hashes.add(png_sha)
            embedded, proof = recover_embedded_png(png_raw, png_name)
            if (_digest(embedded) != graph_sha
                or proof.get("source_image_container_crc_verified") is not True
                or proof.get("source_image_sha256") != png_sha):
                raise ValueError("COMPOSITION_REVIEW_EMBEDDED_GRAPH_INVALID")
            graph = _json(embedded)
            seeds = [node["inputs"]["seed"] for node in graph.values()
                     if (isinstance(node, dict) and node.get("class_type") == "KSampler"
                         and isinstance(node.get("inputs"), dict)
                         and type(node["inputs"].get("seed")) is int)]
            if seeds != [shot["seed"]]:
                raise ValueError("COMPOSITION_REVIEW_SEED_MISMATCH")
            group = groups.setdefault(shot_id, {
                "shot_id": shot_id, "order": order, "candidates": [],
            })
            if group["order"] != order:
                raise ValueError("COMPOSITION_REVIEW_SHOT_ORDER_MISMATCH")
            group["candidates"].append({
                "variant": variant,
                "filename": png_name,
                "png_sha256": png_sha,
                "graph_sha256": graph_sha,
                "seed": shot["seed"],
                "dimensions": proof["source_image_dimensions"],
                "human_visual_review": "NOT_PERFORMED",
            })
        if common_order is not None and orders != common_order:
            raise ValueError("COMPOSITION_REVIEW_VARIANT_SHOTS_MISMATCH")
        common_order = orders

    if (len(seen_variants) != 2 or len(groups) != 3
        or any(len(group["candidates"]) != 2 for group in groups.values())):
        raise ValueError("COMPOSITION_REVIEW_COVERAGE_INVALID")

    # 05. The operator's separate review index must exist and be unambiguous
    #     JSON. Its unknown schema is NOT independently verified Comfy history.
    local_index = review_dir / "creative_review_index.json"
    local_index_raw = _regular_bytes(local_index, MAX_JSON_BYTES)
    _json(local_index_raw)
    local_index_sha = _digest(local_index_raw)
    return {
        "schema": "picotoo.composition-draft-evidence-audit.v1",
        "bootstrap_index_sha256": _digest(index_raw),
        "creative_review_index_sha256": local_index_sha,
        "creative_package_sha256": package_sha,
        "source_graph_sha256": common_source,
        "candidate_count": len(seen_png_hashes),
        "candidate_groups": [groups[shot] for shot in common_order],
        "image_container_and_embedded_graph_verified": True,
        "comfy_history_independently_verified": False,
        "image_pixels_decoded": False,
        "visual_review_status": "NEEDS_HUMAN_REVIEW",
        "selected_references": None,
        "reference_approved": False,
        "workflow_registered": False,
        "production_authorized": False,
        "gpu_post": 0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bootstrap-dir", required=True, type=Path)
    parser.add_argument("--review-dir", required=True, type=Path)
    parser.add_argument("--report-file", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        # 06a. Resolve only after rejecting redirected operator-supplied roots.
        if args.bootstrap_dir.is_symlink() or args.review_dir.is_symlink():
            raise ValueError("COMPOSITION_REVIEW_ROOT_SYMLINK_INVALID")
        bootstrap = args.bootstrap_dir.resolve(strict=True)
        review = args.review_dir.resolve(strict=True)
        report = args.report_file.resolve(strict=False)
        # 06. Never overwrite, and never write into either evidence directory.
        if (report.is_relative_to(bootstrap) or report.is_relative_to(review)
            or not report.parent.is_dir()):
            raise ValueError("COMPOSITION_REVIEW_REPORT_DESTINATION_INVALID")
        result = audit(bootstrap, review)
        with report.open("xb") as stream:
            stream.write(canonical_bytes(result))
    except (ValueError, OSError, KeyError, TypeError, IndexError,
            AttributeError, OverflowError, RecursionError,
            json.JSONDecodeError):
        print("COMPOSITION_REVIEW=UNVERIFIED; GPU_POST=0", file=sys.stderr)
        return 1
    print("COMPOSITION_REVIEW=BYTE_EVIDENCE_VERIFIED; "
          f"CANDIDATES={result['candidate_count']}; HUMAN_REVIEW=REQUIRED; GPU_POST=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
