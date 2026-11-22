"""CPU-only Qwen three-shot reference readiness; no source mutation or GPU.

A historical source graph can prove the *shape* of the workflow, not that a
new composition exists or is visually approved. This tool reports missing
shot-scoped files and emits a slot-map PROPOSAL only when all exact local input
bytes are observed. The strict batch preparer and Owner gates remain unchanged.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from scripts.audit_local_qwen_pngs import _links
from scripts.recover_comfy_keyframe_workflow import canonical_bytes, parse_history
from scripts.qwen_reference_bindings import _verify, _verified_jpeg_input
from collect_local_keyframe_outputs import verified_output
from prepare_local_keyframe_batch import (
    keyframes, read_bounded, read_package, require_digest, sha,
)

MAX_INPUT_BYTES = 32 * 1024 * 1024


def _observe_input(input_root: Path, filename: str) -> dict:
    # 01. No arbitrary path traversal, symlink, or unbounded JPEG/PNG read.
    #     The existing collectors protect pinned file descriptors and CRC/SOF.
    if not isinstance(filename, str) or not filename.lower().endswith(
        (".png", ".jpg", ".jpeg")
    ):
        raise ValueError("REFERENCE_PREFLIGHT_UNSUPPORTED_FORMAT")
    if filename.lower().endswith(".png"):
        subfolder, _, basename = filename.rpartition("/")
        observed, data, dimensions = verified_output(input_root, subfolder, basename)
        fmt = "png"
    else:
        observed, data, dimensions = _verified_jpeg_input(input_root, filename)
        fmt = "jpeg"
    if observed != filename or not 0 < len(data) <= MAX_INPUT_BYTES:
        raise ValueError("REFERENCE_PREFLIGHT_FILE_CHANGED")
    metadata = {
        "filename": filename,
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
    }
    # 02. Reuse exactly the same verification contract as strict preparation.
    _verify(input_root, metadata)
    return {**metadata, "format": fmt, "dimensions": dimensions,
            "pixels_decoded": False, "owner_approved": False}


def _graph_slots(graph: dict) -> tuple[dict, list[str]]:
    if not isinstance(graph, dict) or not 1 <= len(graph) <= 512:
        raise ValueError("REFERENCE_PREFLIGHT_GRAPH_INVALID")
    loads = sorted(n for n, node in graph.items()
                   if node.get("class_type") == "LoadImage"
                   and isinstance(node.get("inputs", {}).get("image"), str))
    if not loads or len(loads) != sum(
        node.get("class_type") == "LoadImage" for node in graph.values()
    ):
        raise ValueError("REFERENCE_PREFLIGHT_LOADIMAGE_INVALID")
    samplers = [n for n, node in graph.items()
                if node.get("class_type") == "KSampler"
                and type(node.get("inputs", {}).get("seed")) is int]
    outputs = [n for n, node in graph.items()
               if node.get("class_type") == "SaveImage"
               and isinstance(node.get("inputs", {}).get("filename_prefix"), str)]
    qwen = {n for n, node in graph.items()
            if node.get("class_type") == "TextEncodeQwenImageEditPlus"
            and isinstance(node.get("inputs", {}).get("prompt"), str)}
    if len(samplers) != 1 or len(outputs) != 1 or len(qwen) != 2:
        raise ValueError("REFERENCE_PREFLIGHT_QWEN_LAYOUT_INVALID")
    sampler = graph[samplers[0]]["inputs"]
    pos = qwen & _links(graph, sampler.get("positive"))
    neg = qwen & _links(graph, sampler.get("negative"))
    if len(pos) != 1 or len(neg) != 1 or pos == neg:
        raise ValueError("REFERENCE_PREFLIGHT_PROMPT_LINKS_INVALID")
    return {
        "positive_prompt": {
            "node_id": next(iter(pos)), "class_type": "TextEncodeQwenImageEditPlus",
            "input_name": "prompt",
        },
        "seed": {"node_id": samplers[0], "class_type": "KSampler", "input_name": "seed"},
        "output_prefix": {
            "node_id": outputs[0], "class_type": "SaveImage",
            "input_name": "filename_prefix",
        },
    }, loads


def inspect_readiness(
    graph: dict, recovery: dict, package: dict, package_sha256: str,
    input_root: Path, *, composition_node: str,
    fixed_nodes: tuple[str, ...], shot_2: str | None = None,
    shot_3: str | None = None,
) -> dict:
    """Report exact missing files; never emit runnable graph or authorization."""
    # 03. Require an exact frozen historical graph identity, not one guessed
    #     from model names or output PNG filenames alone.
    digest = sha(canonical_bytes(graph))
    require_digest(package_sha256)
    if (not isinstance(recovery, dict)
        or recovery.get("schema") != "picotoo.local-keyframe-workflow-recovery.v1"
        or recovery.get("graph_sha256") != digest
        or recovery.get("production_authorized") is not False
        or recovery.get("gpu_post") != 0
        or recovery.get("history_status") not in (
            "RECORDED_SUCCESS", "PNG_EMBEDDED_NO_HISTORY"
        )
        or not input_root.is_dir() or input_root.is_symlink()):
        raise ValueError("REFERENCE_PREFLIGHT_SOURCE_UNVERIFIED")
    if recovery["history_status"] == "PNG_EMBEDDED_NO_HISTORY" and (
        recovery.get("prompt_id") is not None
        or recovery.get("source_kind") != "COMFY_PNG_TEXt_PROMPT"
        or recovery.get("source_image_container_crc_verified") is not True
        or not isinstance(recovery.get("source_image_sha256"), str)
        or len(recovery["source_image_sha256"]) != 64
    ):
        raise ValueError("REFERENCE_PREFLIGHT_PNG_PROVENANCE_INVALID")
    slots, load_ids = _graph_slots(graph)
    if (not isinstance(composition_node, str)
        or composition_node not in load_ids
        or not isinstance(fixed_nodes, tuple)
        or len(fixed_nodes) != len(load_ids) - 1
        or len(set(fixed_nodes)) != len(fixed_nodes)
        or set(fixed_nodes) != set(load_ids) - {composition_node}):
        raise ValueError("REFERENCE_PREFLIGHT_ROLE_MAP_INVALID")
    kit_digest, frames = keyframes(package)
    shots = [frame["shot_id"] for frame in frames]
    if len(shots) != 3 or len(set(shots)) != 3:
        raise ValueError("REFERENCE_PREFLIGHT_SHOTS_INVALID")

    # 04. The historical first composition is only a candidate for shot 1;
    #     no automatic duplication onto new shots 2 or 3 is allowed.
    compositions = [
        graph[composition_node]["inputs"]["image"], shot_2, shot_3
    ]
    missing, invalid, inventory, map_entries, seen = [], [], [], [], set()
    shot_files = []
    for index, (shot_id, name) in enumerate(zip(shots, compositions, strict=True), 1):
        if name is None:
            missing.append({"shot_id": shot_id, "node_id": composition_node,
                            "reason": "MISSING_SHOT_COMPOSITION"})
            continue
        if name in seen:
            invalid.append({"shot_id": shot_id, "node_id": composition_node,
                            "reason": "DUPLICATE_SHOT_COMPOSITION"})
            continue
        seen.add(name)
        try:
            observed = _observe_input(input_root, name)
        except FileNotFoundError:
            missing.append({"shot_id": shot_id, "node_id": composition_node,
                            "reason": "FILE_NOT_FOUND"})
            continue
        except (ValueError, OSError, TypeError):
            invalid.append({"shot_id": shot_id, "node_id": composition_node,
                            "reason": "INVALID_COMPOSITION_FILE"})
            continue
        inventory.append({"shot_id": shot_id, "node_id": composition_node,
                          "role": "COMPOSITION_CANDIDATE", **observed})
        shot_files.append({"shot_id": shot_id, **{key: observed[key]
                         for key in ("filename", "sha256", "bytes")}})
    map_entries.append({"node_id": composition_node, "class_type": "LoadImage",
                        "input_name": "image", "mode": "per_shot", "files": shot_files})

    for node_id in sorted(fixed_nodes):
        name = graph[node_id]["inputs"]["image"]
        try:
            observed = _observe_input(input_root, name)
        except FileNotFoundError:
            missing.append({"node_id": node_id, "reason": "FIXED_REFERENCE_NOT_FOUND"})
            continue
        except (ValueError, OSError, TypeError):
            invalid.append({"node_id": node_id, "reason": "INVALID_FIXED_REFERENCE"})
            continue
        inventory.append({"node_id": node_id, "role": "FIXED_SHARED_REFERENCE", **observed})
        map_entries.append({"node_id": node_id, "class_type": "LoadImage",
                            "input_name": "image", "mode": "fixed",
                            "file": {key: observed[key]
                                     for key in ("filename", "sha256", "bytes")}})

    # 05. Convert the frozen Creative keyframe kit into an exact local work
    #     order, instead of asking an operator to retype three long prompts.
    #     Its text comes ONLY from the verified kit, never from a guessed
    #     composition or a historical Comfy PNG's negative prompt.
    missing_shots = {item["shot_id"] for item in missing if "shot_id" in item}
    invalid_shots = {item["shot_id"] for item in invalid if "shot_id" in item}
    observed_shots = {
        item["shot_id"]: item
        for item in inventory if item.get("role") == "COMPOSITION_CANDIDATE"
    }
    work_items = []
    for frame in frames:
        shot_id = frame["shot_id"]
        if shot_id in invalid_shots:
            state = "INVALID_REFERENCE"
        elif shot_id in missing_shots:
            state = "NEEDS_DISTINCT_COMPOSITION"
        elif shot_id in observed_shots:
            state = "OBSERVED_UNAPPROVED"
        else:
            state = "UNVERIFIED"
        work_items.append({
            "shot_id": shot_id,
            "order": frame["order"],
            "composition_status": state,
            "composition_node": composition_node,
            "existing_input_filename": (
                observed_shots[shot_id]["filename"]
                if shot_id in observed_shots else None
            ),
            "source": "FROZEN_CREATIVE_KEYFRAME_KIT",
            "creative_still_prompt": frame["still_prompt"],
            "creative_still_prompt_sha256": sha(
                frame["still_prompt"].encode("utf-8")
            ),
            "camera_framing": frame.get("camera_framing"),
            "scene_id": frame.get("scene_id"),
            "review_checklist": list(frame["review_checklist"]),
            "prompt_text_local_only": True,
            "new_image_created": False,
            "owner_approved": False,
        })

    complete = not missing and not invalid and len(map_entries) == len(load_ids)
    proposed = None
    if complete:
        # 05. This is a binding *proposal* for human confirmation, not a
        #     workflow registration or executable three-shot submission.
        proposed = {
            "schema": "picotoo.local-keyframe-slot-map.v1",
            "graph_sha256": digest,
            **slots,
            "reference_images": map_entries,
        }
    return {
        "schema": "picotoo.qwen-reference-readiness.v1",
        "status": ("BLOCKED_INVALID_REFERENCE" if invalid else
                   "BLOCKED_MISSING_REFERENCES" if missing else
                   "READY_FOR_OWNER_BINDING_REVIEW"),
        "source_graph_sha256": digest,
        "creative_package_sha256": package_sha256,
        "creative_kit_digest": kit_digest,
        "history_status": recovery["history_status"],
        "composition_node": composition_node,
        "fixed_nodes": sorted(fixed_nodes),
        "shot_ids": shots,
        "inventory": inventory,
        "missing": missing,
        "invalid": invalid,
        "binding_proposal": proposed,
        # 06. Present shot-specific creative instructions for missing visuals.
        #     This is a local work order, not a generated artifact or approval.
        "composition_work_order": {
            "schema": "picotoo.qwen-local-composition-workorder.v1",
            "creative_kit_digest": kit_digest,
            "shot_count": 3,
            "items": work_items,
            "source_workflow_modified": False,
            "all_images_approved": False,
            "gpu_post": 0,
        },
        "image_quality": "UNREVIEWED",
        "source_rights_confirmed": False,
        "source_inputs_verified_for_production": False,
        "production_authorized": False,
        "gpu_post": 0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recovery-dir", type=Path, required=True)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--package-sha256", required=True)
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--composition-node", required=True)
    parser.add_argument("--fixed-node", action="append", default=[])
    parser.add_argument("--shot-2")
    parser.add_argument("--shot-3")
    parser.add_argument("--report-file", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        output_root = args.input_root.resolve(strict=True)
        output_path = args.report_file.resolve(strict=False)
        if (output_path.is_relative_to(output_root)
            or not output_path.parent.is_dir()
            or output_path.exists()):
            raise ValueError("REFERENCE_PREFLIGHT_REPORT_PATH_INVALID")
        graph = parse_history(read_bounded(args.recovery_dir / "workflow_api.json"))
        recovery = parse_history(read_bounded(args.recovery_dir / "recovery_manifest.json"))
        package = read_package(args.package, args.package_sha256)
        report = inspect_readiness(
            graph, recovery, package, args.package_sha256,
            args.input_root, composition_node=args.composition_node,
            fixed_nodes=tuple(args.fixed_node), shot_2=args.shot_2,
            shot_3=args.shot_3,
        )
        with args.report_file.open("xb") as output:
            output.write(canonical_bytes(report))
    except (KeyError, ValueError, OSError, TypeError, OverflowError,
            RecursionError, IndexError, AttributeError):
        print("QWEN_REFERENCE_PREFLIGHT=UNVERIFIED; GPU_POST=0", file=sys.stderr)
        return 1
    print(f"QWEN_REFERENCE_PREFLIGHT={report['status']}; "
          f"MISSING={len(report['missing'])}; GPU_POST=0")
    return 0 if report["status"] == "READY_FOR_OWNER_BINDING_REVIEW" else 2


if __name__ == "__main__":
    raise SystemExit(main())
