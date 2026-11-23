"""Inspect existing Qwen first-frame PNGs offline without Comfy /history.

Input PNGs are never changed. The only permitted write is one explicit new
JSON inventory outside the Comfy output root. This is not an image decoder,
model check, run receipt, owner approval, or permission to use the GPU.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import stat
import sys
from pathlib import Path

from scripts.comfy_png_embedded_evidence import MAX_PNG_BYTES, recover_png_file
from scripts.recover_comfy_keyframe_workflow import canonical_bytes

MAX_CANDIDATES = 64
PREFIX = "PVP_"


def _links(graph: dict, start: object) -> set[str]:
    # 01. Trace only explicit Comfy [node_id, output_index] links. A linked
    #     negative encoder may look identical to a positive encoder otherwise.
    if not isinstance(start, list) or len(start) != 2 or not isinstance(start[0], str):
        return set()
    pending = [start[0]]
    seen: set[str] = set()
    while pending:
        node_id = pending.pop()
        if node_id in seen or node_id not in graph:
            continue
        seen.add(node_id)
        if len(seen) > 512:
            raise ValueError("QWEN_GRAPH_WIRING_TOO_LARGE")
        for value in graph[node_id]["inputs"].values():
            if (isinstance(value, list) and len(value) == 2
                and isinstance(value[0], str) and type(value[1]) is int):
                pending.append(value[0])
    return seen


def _inspect_png(path: Path) -> dict:
    # 02. Do not follow symlinks, scan directories, infer a Prompt ID, or
    #     include untrusted raw prompt text in the inspection report.
    details = path.lstat()
    if (not stat.S_ISREG(details.st_mode) or not 0 < details.st_size <= MAX_PNG_BYTES):
        raise ValueError("QWEN_PNG_NOT_ORDINARY_BOUNDED_FILE")
    graph_bytes, proof = recover_png_file(path)
    graph = json.loads(graph_bytes)
    qwen = sorted(
        key for key, node in graph.items()
        if node["class_type"] == "TextEncodeQwenImageEditPlus"
        and isinstance(node["inputs"].get("prompt"), str)
    )
    load_image = sorted(
        [
            {"node_id": node_id, "class_type": "LoadImage", "input_name": "image",
             "current_filename": node["inputs"]["image"]}
            for node_id, node in graph.items()
            if node["class_type"] == "LoadImage"
            and isinstance(node["inputs"].get("image"), str)
        ],
        key=lambda x: x["node_id"],
    )
    samplers = sorted(
        node_id for node_id, node in graph.items()
        if node["class_type"] == "KSampler"
        and type(node["inputs"].get("seed")) is int
    )
    outputs = sorted(
        node_id for node_id, node in graph.items()
        if node["class_type"] == "SaveImage"
        and isinstance(node["inputs"].get("filename_prefix"), str)
    )
    positive, negative, wiring = None, None, "UNVERIFIED"
    if len(samplers) == 1:
        sampler = graph[samplers[0]]["inputs"]
        pos = set(qwen) & _links(graph, sampler.get("positive"))
        neg = set(qwen) & _links(graph, sampler.get("negative"))
        if len(pos) == len(neg) == 1 and pos.isdisjoint(neg):
            positive, negative = next(iter(pos)), next(iter(neg))
            wiring = "EXPLICIT_GRAPH_LINKS"
    model_names = [
        {"node_id": node["node_id"], "class_type": node["class_type"],
         "selectors": node["declared_model_selectors"]}
        for node in proof["node_inventory"] if node["declared_model_selectors"]
    ]
    return {
        "filename": path.name,
        "png_sha256": proof["source_image_sha256"],
        "png_bytes": proof["source_image_bytes"],
        "dimensions": proof["source_image_dimensions"],
        "graph_sha256": proof["graph_sha256"],
        "history_status": "PNG_EMBEDDED_NO_HISTORY",
        "prompt_id": None,
        "qwen_prompt_nodes": qwen,
        "positive_prompt_node": positive,
        "negative_prompt_node": negative,
        "prompt_wiring": wiring,
        "sampler_seed_nodes": samplers,
        "save_image_nodes": outputs,
        "load_image_slots": load_image,
        "declared_model_names_only": model_names,
        "node_count": proof["node_count"],
        "has_qwen_binding_shape": bool(qwen and len(samplers) == 1
                                       and len(outputs) == 1 and load_image),
        "pixel_decode": "NOT_PERFORMED",
        "image_quality": "UNREVIEWED",
    }


def inspect_loadimage_inputs(png_files: list[dict], input_root: Path) -> dict:
    """Inspect only filenames referenced by verified PNG graphs; never infer S2/S3.

    This is a separate read-only input inventory. Reused shared pet/bowl
    references are expected; no image is assigned to a production shot.
    """
    # 01. The optional path is explicit and must be an ordinary directory.
    #     Avoid scanning drives, walking subfolders or inferring rights.
    if not input_root.is_dir() or input_root.is_symlink():
        raise ValueError("QWEN_INPUT_ROOT_INVALID")

    references: dict[str, list[dict]] = {}
    for png in png_files:
        for slot in png["load_image_slots"]:
            name = slot["current_filename"]
            references.setdefault(name, []).append({
                "output_png": png["filename"],
                "node_id": slot["node_id"],
            })
    if len(references) > 192:
        raise ValueError("QWEN_INPUT_REFERENCE_COUNT_INVALID")

    # 02. Reuse the strict Comfy image verifier, including path restrictions,
    #     bounded size, PNG/JPEG integrity and hash. Import lazily to avoid
    #     coupling the normal output-only PNG audit to the readiness module.
    from scripts.qwen_reference_readiness import _observe_input

    observed: list[dict] = []
    missing: list[dict] = []
    for filename, usages in sorted(references.items()):
        try:
            entry = _observe_input(input_root, filename)
            observed.append({
                "filename": filename,
                "sha256": entry["sha256"],
                "bytes": entry["bytes"],
                "format": entry["format"],
                # 05. Canonical JSON round-trips dimensions as a list,
                #     never a Python tuple (CI expects byte-equivalent data).
                "dimensions": list(entry["dimensions"]),
                "used_by": usages,
                "pixels_decoded": False,
                "owner_approved": False,
            })
        except FileNotFoundError:
            missing.append({
                "filename": filename,
                "reason": "QWEN_INPUT_FILE_NOT_FOUND",
                "used_by": usages,
            })
        except (ValueError, OSError, TypeError, KeyError, IndexError,
                OverflowError, RecursionError):
            # 03. Never include exceptions, file contents, prompt strings,
            #     absolute paths, or inferred success in a JSON report.
            missing.append({
                "filename": filename,
                "reason": "QWEN_INPUT_FILE_UNVERIFIED",
                "used_by": usages,
            })

    return {
        "status": "ALL_REFERENCED_INPUT_BYTES_OBSERVED"
        if observed and not missing else "INPUT_REFERENCES_UNVERIFIED",
        "referenced_file_count": len(references),
        "observed_file_count": len(observed),
        "observed": observed,
        "unverified": missing,
        "shot_2_3_assignment": "UNVERIFIED",
        "independent_composition_images": "UNVERIFIED",
        "input_rights_confirmed": False,
        "gpu_post": 0,
    }


def inspect_directory(
    output_root: Path, *, prefix: str = PREFIX, expected_count: int | None = None,
    input_root: Path | None = None,
) -> dict:
    """Enumerate only bounded, directly contained PNGs with an explicit prefix."""
    if (not output_root.is_dir() or output_root.is_symlink()
        or not isinstance(prefix, str) or not 1 <= len(prefix) <= 48
        or any(char in prefix for char in ("/", "\\", ":", "\x00"))
        or expected_count is not None
        and (type(expected_count) is not int or not 1 <= expected_count <= MAX_CANDIDATES)):
        raise ValueError("QWEN_INSPECTION_SCOPE_INVALID")
    paths = sorted(
        (item for item in output_root.iterdir()
         if item.name.startswith(prefix) and item.suffix.lower() == ".png"),
        key=lambda item: item.name,
    )
    if not paths or len(paths) > MAX_CANDIDATES:
        raise ValueError("QWEN_INSPECTION_FILE_COUNT_INVALID")
    errors: list[dict] = []
    files: list[dict] = []
    seen: set[str] = set()
    for path in paths:
        try:
            item = _inspect_png(path)
            if item["png_sha256"] in seen:
                raise ValueError("QWEN_DUPLICATED_IMAGE_BYTES")
            seen.add(item["png_sha256"])
            files.append(item)
        except (ValueError, OSError, TypeError, KeyError, IndexError,
                RecursionError, OverflowError, json.JSONDecodeError) as exc:
            # 03. Return only bounded reason codes: no private prompt text,
            #     arbitrary exception message or absolute local path.
            reason = str(exc)
            if not reason.startswith(("QWEN_", "PNG_", "HISTORY_")):
                reason = "QWEN_PNG_UNVERIFIED"
            errors.append({"filename": path.name, "reason": reason[:80]})
    if expected_count is not None and len(paths) != expected_count:
        errors.append({"filename": None, "reason": "QWEN_EXPECTED_COUNT_MISMATCH"})
    # 04. Input bytes are a separate observation dimension. Even fully
    #     available shared inputs cannot prove independent S2/S3 compositions.
    input_inventory = (inspect_loadimage_inputs(files, input_root)
                       if input_root is not None else None)
    return {
        "schema": "picotoo.qwen-local-png-readonly-inspection.v1",
        "status": "OBSERVED_NEEDS_REVIEW" if not errors else "UNVERIFIED",
        "candidate_count": len(paths),
        "verified_png_count": len(files),
        "files": files,
        "errors": errors,
        **({"referenced_input_inventory": input_inventory}
           if input_inventory is not None else {}),
        "raw_prompt_text_exported": False,
        "comfy_history_success_verified": False,
        "model_files_verified": False,
        "png_pixels_decoded": False,
        "production_authorized": False,
        "owner_approved": False,
        "gpu_post": 0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--prefix", default=PREFIX)
    parser.add_argument("--expected-count", type=int)
    parser.add_argument("--input-root", type=Path)
    parser.add_argument("--report-file", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        root = args.output_root.resolve(strict=True)
        report = args.report_file.resolve(strict=False)
        # 04. Never write reports into Comfy's output tree, and never replace
        #     an existing report. The operator explicitly chooses the path.
        input_root = args.input_root.resolve(strict=True) if args.input_root else None
        if (report.is_relative_to(root)
            or (input_root is not None and report.is_relative_to(input_root))
            or not report.parent.is_dir()):
            raise ValueError("QWEN_REPORT_DESTINATION_INVALID")
        result = inspect_directory(
            args.output_root, prefix=args.prefix, expected_count=args.expected_count,
            input_root=args.input_root,
        )
        with args.report_file.open("xb") as stream:
            stream.write(canonical_bytes(result))
    except (ValueError, OSError, TypeError, RecursionError, OverflowError):
        print("QWEN_PNG_INSPECTION=UNVERIFIED; GPU_POST=0", file=sys.stderr)
        return 1
    print(f"QWEN_PNG_INSPECTION={result['status']}; COUNT={result['candidate_count']}; GPU_POST=0")
    if "referenced_input_inventory" in result:
        inventory = result["referenced_input_inventory"]
        print("QWEN_REFERENCED_INPUTS="
              + f"{inventory['observed_file_count']}/{inventory['referenced_file_count']}"
              + "; S2_S3_ASSIGNMENT=UNVERIFIED; GPU_POST=0")
    print("MODEL_INFERENCE=NOT_RUN; PRODUCTION_AUTHORIZED=FALSE")
    return 0 if not result["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
