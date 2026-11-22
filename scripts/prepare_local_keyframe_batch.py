"""Prepare three local keyframe prompt graphs from a frozen Creative package.

CPU-only dry run. Requires a locally reviewed, exact input-slot map; does not
submit a prompt, register a workflow, write to Comfy input, or grant approval.
All generated files remain local and must be treated as untrusted candidates.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path, PurePosixPath
from uuid import UUID

from recover_comfy_keyframe_workflow import (
    MAX_HISTORY_BYTES, canonical_bytes, parse_history,
)
from qwen_reference_bindings import resolve_reference_bindings

MAX_PACKAGE_BYTES = 16 * 1024 * 1024
PROFILE = "video.landscape.v1"
ID = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def require_digest(value: object) -> str:
    if not isinstance(value, str) or not DIGEST.fullmatch(value):
        raise ValueError("KEYFRAME_DIGEST_INVALID")
    return value


def read_bounded(path: Path, limit: int = MAX_HISTORY_BYTES) -> bytes:
    with path.open("rb") as handle:
        data = handle.read(limit + 1)
    if not 0 < len(data) <= limit:
        raise ValueError("KEYFRAME_FILE_SIZE_INVALID")
    return data


def read_package(path: Path, expected_sha: str) -> dict:
    # 01. Accept the original Core ZIP only, verify the independently supplied digest.
    from io import BytesIO

    data = read_bounded(path, MAX_PACKAGE_BYTES)
    if sha(data) != require_digest(expected_sha):
        raise ValueError("KEYFRAME_PACKAGE_HASH_MISMATCH")
    with zipfile.ZipFile(BytesIO(data)) as archive:
        members = archive.infolist()
        if len(members) != 1 or members[0].file_size > MAX_PACKAGE_BYTES:
            raise ValueError("KEYFRAME_PACKAGE_MEMBER_INVALID")
        member = members[0]
        parts = PurePosixPath(member.filename).parts
        if len(parts) != 2 or parts[1] != "creative-package.json":
            raise ValueError("KEYFRAME_PACKAGE_MEMBER_INVALID")
        package_id = str(UUID(parts[0]))
        if parts[0] != package_id or member.flag_bits & 1:
            raise ValueError("KEYFRAME_PACKAGE_MEMBER_INVALID")
        with archive.open(member) as handle:
            payload = handle.read(MAX_PACKAGE_BYTES + 1)
        if len(payload) > MAX_PACKAGE_BYTES:
            raise ValueError("KEYFRAME_PACKAGE_MEMBER_INVALID")
    package = parse_history(payload)
    if package.get("creative_package_id") != package_id:
        raise ValueError("KEYFRAME_PACKAGE_ID_MISMATCH")
    return package


def keyframes(package: dict) -> tuple[str, list[dict]]:
    # 02. Use exact Core kit payload, including original review state and shot order.
    if (package.get("schema_version") != "1.0"
        or package.get("quality_outcome") != "PASS"
        or package.get("creative_profile") != "creative.content_plan.v2"):
        raise ValueError("KEYFRAME_PACKAGE_NOT_PASS_V2")
    stages = package["stage_results"]
    kit = stages["keyframe_kit.v1"]
    bible = stages["video_bible.v1"]
    if (kit["schema_version"] != "keyframe_kit.v1"
        or kit["bible_digest"] != bible["bible_digest"]
        or sha(canonical_bytes({k: v for k, v in bible.items() if k != "bible_digest"}))
            != require_digest(bible["bible_digest"])
        or stages["creative_brief.v1"]["output_profile_id"] != PROFILE):
        raise ValueError("KEYFRAME_KIT_LINEAGE_INVALID")
    digest = require_digest(kit["kit_digest"])
    # Matches Core _kit_digest: omit bible_digest, retain kit_digest as null.
    body = {**kit, "kit_digest": None}
    body.pop("bible_digest", None)
    if sha(canonical_bytes(body)) != digest:
        raise ValueError("KEYFRAME_KIT_HASH_MISMATCH")
    frames = kit["keyframes"]
    shots = stages["shot_plan.v1"]["shots"]
    if not isinstance(frames, list) or len(frames) != 3 or not isinstance(shots, list) or len(shots) != 3:
        raise ValueError("KEYFRAME_FULL_COVERAGE_REQUIRED")
    seen = set()
    for index, (frame, shot) in enumerate(zip(frames, shots, strict=True), 1):
        shot_id = frame["shot_id"]
        if (not isinstance(shot_id, str) or not ID.fullmatch(shot_id)
            or shot_id in seen or frame["order"] != index or shot["order"] != index
            or shot_id != shot["shot_id"] or shot["duration_seconds"] != 4
            or shot["render_intent"] != "GENERATIVE_VIDEO"
            or frame["approval_status"] != "PENDING_HUMAN_REVIEW"
            or not isinstance(frame["still_prompt"], str) or not 1 <= len(frame["still_prompt"]) <= 5000
            or not isinstance(frame["review_checklist"], list)
            or not frame["review_checklist"]
            or any(not isinstance(x, str) or not x.strip() for x in frame["review_checklist"])):
            raise ValueError("KEYFRAME_SHOT_SCOPE_INVALID")
        seen.add(shot_id)
    return digest, frames


def slot(graph: dict, binding: dict, allowed: set[str], value_type: type) -> tuple[str, str]:
    if not isinstance(binding, dict) or set(binding) != {"node_id", "class_type", "input_name"}:
        raise ValueError("KEYFRAME_SLOT_MAP_INVALID")
    node_id, name = binding["node_id"], binding["input_name"]
    if not isinstance(node_id, str) or not isinstance(name, str) or name not in allowed:
        raise ValueError("KEYFRAME_SLOT_MAP_INVALID")
    node = graph[node_id]
    if node["class_type"] != binding["class_type"] or type(node["inputs"][name]) is not value_type:
        raise ValueError("KEYFRAME_SLOT_TYPE_MISMATCH")
    return node_id, name


def prepare(graph: dict, recovery: dict, bindings: dict, package: dict,
            package_sha: str, variant: int,
            input_root: Path | None = None) -> tuple[dict[str, bytes], dict]:
    # 03. Freeze all topology and non-allowlisted inputs: no guessed node IDs.
    graph_sha = sha(canonical_bytes(graph))
    require_digest(package_sha)
    if (recovery["schema"] != "picotoo.local-keyframe-workflow-recovery.v1"
        or recovery["graph_sha256"] != graph_sha
        or recovery.get("production_authorized") is not False
        or recovery.get("history_status") not in (
            "RECORDED_SUCCESS", "PNG_EMBEDDED_NO_HISTORY"
        )
        or recovery.get("gpu_post") != 0
        or not 1 <= len(graph) <= 512):
        raise ValueError("KEYFRAME_RECOVERY_MISMATCH")
    if (type(variant) is not int or not 0 <= variant <= 10000
        or bindings.get("schema") != "picotoo.local-keyframe-slot-map.v1"
        or bindings.get("graph_sha256") != graph_sha
        or set(bindings) not in (
            {"schema", "graph_sha256", "positive_prompt", "seed", "output_prefix"},
            {"schema", "graph_sha256", "positive_prompt", "seed", "output_prefix", "reference_images"},
        )):
        raise ValueError("KEYFRAME_BINDINGS_INVALID")
    prompt_binding = bindings["positive_prompt"]
    # 01. Qwen-Image-Edit uses a strictly named .prompt field. Do not allow
    #     arbitrary class_type or transform other prompt-like graph fields.
    if prompt_binding.get("input_name") == "prompt":
        if prompt_binding.get("class_type") != "TextEncodeQwenImageEditPlus":
            raise ValueError("KEYFRAME_QWEN_PROMPT_NODE_INVALID")
        prompt_slot = slot(graph, prompt_binding, {"prompt"}, str)
    else:
        prompt_slot = slot(graph, prompt_binding, {"text"}, str)
    seed_slot = slot(graph, bindings["seed"], {"seed", "noise_seed"}, int)
    prefix_slot = slot(graph, bindings["output_prefix"], {"filename_prefix"}, str)
    if len({prompt_slot, seed_slot, prefix_slot}) != 3:
        raise ValueError("KEYFRAME_SLOT_COLLISION")

    # Keep recovered identity conditioning, model selectors, dimensions and
    # negative prompt untouched. This is a candidate projection, not verification
    # of their contents, current file availability, or FLUX model identity.
    kit_digest, frames = keyframes(package)
    references, reference_inventory = resolve_reference_bindings(
        graph, bindings, frames, input_root
    )
    files: dict[str, bytes] = {}
    records = []
    for frame in frames:
        shot_id = frame["shot_id"]
        seed = int.from_bytes(hashlib.sha256(
            f"{package_sha}|{shot_id}|{variant}".encode()
        ).digest()[:8], "big") & ((1 << 63) - 1)
        candidate = copy.deepcopy(graph)
        prefix = f"PicotooPet/keyframes/{package_sha[:16]}/{shot_id}/v{variant:04d}"
        for (node_id, name), value in (
            (prompt_slot, frame["still_prompt"]), (seed_slot, seed), (prefix_slot, prefix)
        ):
            candidate[node_id]["inputs"][name] = value
        # 02. Change only explicitly reviewed LoadImage filename inputs;
        #     all model selectors, negative prompts and graph topology stay frozen.
        for node_id, per_shot in references.items():
            candidate[node_id]["inputs"]["image"] = per_shot[shot_id]
        filename = f"{frame['order']:02d}-{shot_id}.json"
        data = canonical_bytes(candidate)
        files[filename] = data
        records.append({
            "shot_id": shot_id, "order": frame["order"], "seed": seed,
            "graph_file": filename, "graph_sha256": sha(data),
            "still_prompt_sha256": sha(frame["still_prompt"].encode("utf-8")),
            "review_checklist": frame["review_checklist"],
        })
    manifest = {
        "schema": "picotoo.local-keyframe-batch-dry-run.v1",
        "creative_package_id": package["creative_package_id"],
        "creative_package_sha256": package_sha,
        "keyframe_kit_digest": kit_digest,
        "source_graph_sha256": graph_sha,
        "slot_map_sha256": sha(canonical_bytes(bindings)),
        "variant": variant,
        "history_provenance": recovery["history_status"],
        "reference_inputs": reference_inventory,
        "shots": records,
        "source_inputs_verified": False,
        "workflow_registered": False,
        "production_authorized": False,
        "gpu_post": 0,
    }
    return files, manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--package-sha256", required=True)
    parser.add_argument("--recovery-dir", type=Path, required=True)
    parser.add_argument("--slot-map", type=Path, required=True)
    parser.add_argument("--input-root", type=Path)
    parser.add_argument("--variant", type=int, default=0)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        package = read_package(args.package, args.package_sha256)
        graph = parse_history(read_bounded(args.recovery_dir / "workflow_api.json"))
        recovery = parse_history(read_bounded(args.recovery_dir / "recovery_manifest.json"))
        bindings = parse_history(read_bounded(args.slot_map))
        files, manifest = prepare(graph, recovery, bindings, package,
                                  args.package_sha256, args.variant, args.input_root)
        # 04. No overwrite; the last-written manifest marks complete export.
        args.output_dir.mkdir(parents=False, exist_ok=False)
        for name, data in files.items():
            with (args.output_dir / name).open("xb") as handle:
                handle.write(data)
        with (args.output_dir / "batch_manifest.json").open("xb") as handle:
            handle.write(canonical_bytes(manifest))
    except (ValueError, OSError, TypeError, KeyError, IndexError, AttributeError,
            RecursionError, OverflowError, zipfile.BadZipFile, RuntimeError):
        print("KEYFRAME_BATCH=UNVERIFIED; GPU_POST=0", file=sys.stderr)
        return 1
    print("KEYFRAME_BATCH=DRY_RUN_CANDIDATE; SHOTS=3; GPU_POST=0")
    print("SOURCE_INPUTS_VERIFIED=FALSE; PRODUCTION_AUTHORIZED=FALSE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
