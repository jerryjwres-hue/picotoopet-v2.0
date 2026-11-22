"""Strict offline mapping of three real PNGs to prepared graph hashes.

This supplements (never fabricates) Comfy history. Each image's embedded API
prompt must hash to the exact frozen prepared graph for the assigned shot.
No scanning arbitrary folders, network traffic, or production authorization.
"""
from __future__ import annotations

from pathlib import Path

from comfy_png_embedded_evidence import recover_embedded_png
from recover_comfy_keyframe_workflow import canonical_bytes
from collect_local_keyframe_outputs import (
    file_sha, safe_components, verified_output,
)
from prepare_local_keyframe_batch import read_bounded, require_digest

MAX_IMAGES_PER_SHOT = 32


def collect_embedded_outputs(
    batch: dict, batch_dir: Path, selection: dict, output_root: Path,
) -> dict:
    """Read explicit filename map, not a claimed or guessed Comfy success record."""
    if (not isinstance(batch, dict)
        or batch.get("schema") != "picotoo.local-keyframe-batch-dry-run.v1"
        or batch.get("production_authorized") is not False
        or batch.get("gpu_post") != 0
        or batch.get("source_inputs_verified") is not False
        or batch.get("history_provenance") != "PNG_EMBEDDED_NO_HISTORY"
        or not isinstance(batch.get("shots"), list) or len(batch["shots"]) != 3
        or not isinstance(selection, dict)
        or set(selection) != {"schema", "shots"}
        or selection["schema"] != "picotoo.local-keyframe-embedded-output-map.v1"
        or not isinstance(selection["shots"], list) or len(selection["shots"]) != 3):
        raise ValueError("PNG_OUTPUT_BATCH_SCOPE_INVALID")
    for key in ("creative_package_sha256", "source_graph_sha256",
                "keyframe_kit_digest", "slot_map_sha256"):
        require_digest(batch[key])

    used_images, used_hashes, outputs = set(), set(), []
    for order, (shot, selected) in enumerate(
        zip(batch["shots"], selection["shots"], strict=True), 1
    ):
        shot_id = shot["shot_id"]
        if (not isinstance(shot_id, str)
            or shot.get("order") != order
            or shot.get("graph_file") != f"{order:02d}-{shot_id}.json"
            or not isinstance(selected, dict)
            or set(selected) != {"shot_id", "files"}
            or selected["shot_id"] != shot_id
            or not isinstance(selected["files"], list)
            or not 1 <= len(selected["files"]) <= MAX_IMAGES_PER_SHOT):
            raise ValueError("PNG_OUTPUT_SHOT_SCOPE_INVALID")
        expected = require_digest(shot["graph_sha256"])
        if file_sha(read_bounded(batch_dir / shot["graph_file"])) != expected:
            raise ValueError("PNG_OUTPUT_FROZEN_GRAPH_CHANGED")
        images = []
        for relative in selected["files"]:
            if not isinstance(relative, str):
                raise ValueError("PNG_OUTPUT_PATH_INVALID")
            pieces = safe_components(relative, filename=False)
            if not pieces or not pieces[-1].lower().endswith(".png"):
                raise ValueError("PNG_OUTPUT_FILENAME_INVALID")
            subfolder, _, filename = relative.rpartition("/")
            name, png_bytes, (width, height) = verified_output(
                output_root, subfolder, filename
            )
            digest = file_sha(png_bytes)
            if name != relative or name in used_images or digest in used_hashes:
                raise ValueError("PNG_OUTPUT_REUSED_IMAGE_INVALID")
            embedded_graph, proof = recover_embedded_png(png_bytes, filename)
            if (file_sha(embedded_graph) != expected
                or proof["history_status"] != "PNG_EMBEDDED_NO_HISTORY"
                or proof["source_image_sha256"] != digest
                or proof["source_image_dimensions"] != [width, height]):
                raise ValueError("PNG_OUTPUT_EMBEDDED_GRAPH_MISMATCH")
            used_images.add(name)
            used_hashes.add(digest)
            images.append({
                "output_relative_path": name,
                "sha256": digest,
                "bytes": len(png_bytes), "width": width, "height": height,
                "comfy_output_node": None, "format": "png",
                "image_container_crc_verified": True,
                "embedded_prompt_graph_verified": True,
                "pixels_decoded": False, "visual_review": "UNREVIEWED",
            })
        outputs.append({
            "shot_id": shot_id, "order": order,
            "prompt_id": None,
            "prepared_graph_sha256": expected,
            "candidates": images,
            "selected_reference": None,
        })
    return {
        "schema": "picotoo.local-keyframe-output-candidates.v1",
        "creative_package_id": batch["creative_package_id"],
        "creative_package_sha256": batch["creative_package_sha256"],
        "keyframe_kit_digest": batch["keyframe_kit_digest"],
        "batch_manifest_sha256": file_sha(canonical_bytes(batch)),
        "history_provenance": "PNG_EMBEDDED_NO_HISTORY",
        "comfy_history_success_verified": False,
        "shots": outputs,
        "recorded_image_bytes_observed": True,
        "candidate_files_staged": False,
        "review_status": "NEEDS_HUMAN_REVIEW",
        "source_rights_confirmed": False,
        "reference_approved": False,
        "gpu_post": 0,
    }
