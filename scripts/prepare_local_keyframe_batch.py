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
# 01. Bound one offline request to prevent accidental huge file trees.
#     More variants can be prepared in separate non-overwriting folders.
MAX_VARIANTS_PER_EXPORT = 8
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
    # 04. Source class cannot be upgraded by changing an untrusted manifest
    #     label: historyless PNG remains historyless and needs its exact
    #     observed PNG digest plus structural CRC evidence.
    if recovery["history_status"] == "PNG_EMBEDDED_NO_HISTORY":
        if (recovery.get("prompt_id") is not None
            or recovery.get("source_kind") != "COMFY_PNG_TEXt_PROMPT"
            or not recovery.get("source_image_container_crc_verified") is True
            or not isinstance(recovery.get("source_image_sha256"), str)
            or len(recovery["source_image_sha256"]) != 64
            or any(ch not in "0123456789abcdef"
                   for ch in recovery["source_image_sha256"])):
            raise ValueError("KEYFRAME_EMBEDDED_PROVENANCE_INVALID")
    elif recovery.get("source_kind") == "COMFY_PNG_TEXt_PROMPT":
        raise ValueError("KEYFRAME_HISTORY_PROVENANCE_CONFLICT")
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



def bootstrap_compositions(
    graph: dict, recovery: dict, package: dict, package_sha: str,
    variant: int, input_root: Path,
) -> tuple[dict[str, bytes], dict]:
    """Prepare *unapproved creative drafts*, never strict reference bindings.

    The existing Qwen composition may guide all three proposed generations,
    but it is NEVER accepted as three independently produced source images.
    Outputs must be reviewed and subsequently passed through strict readiness.
    """
    # 01. Reuse the actual observed three-LoadImage Qwen graph and frozen Kit.
    #     No guessed node IDs, invented pixels, model switch or network action.
    from qwen_reference_readiness import _graph_slots, _observe_input

    digest = sha(canonical_bytes(graph))
    require_digest(package_sha)
    if (not isinstance(graph, dict) or not 1 <= len(graph) <= 512
        or not isinstance(recovery, dict)
        or recovery.get("schema") != "picotoo.local-keyframe-workflow-recovery.v1"
        or recovery.get("graph_sha256") != digest
        or recovery.get("production_authorized") is not False
        or recovery.get("gpu_post") != 0
        or recovery.get("history_status") not in (
            "RECORDED_SUCCESS", "PNG_EMBEDDED_NO_HISTORY"
        )
        or type(variant) is not int or not 0 <= variant <= 10000
        or not input_root.is_dir() or input_root.is_symlink()):
        raise ValueError("COMPOSITION_BOOTSTRAP_SOURCE_INVALID")
    if recovery["history_status"] == "PNG_EMBEDDED_NO_HISTORY":
        if (recovery.get("prompt_id") is not None
            or recovery.get("source_kind") != "COMFY_PNG_TEXt_PROMPT"
            or recovery.get("source_image_container_crc_verified") is not True
            or not isinstance(recovery.get("source_image_sha256"), str)
            or not DIGEST.fullmatch(recovery["source_image_sha256"])):
            raise ValueError("COMPOSITION_BOOTSTRAP_PROVENANCE_INVALID")
    elif recovery.get("source_kind") == "COMFY_PNG_TEXt_PROMPT":
        raise ValueError("COMPOSITION_BOOTSTRAP_PROVENANCE_CONFLICT")

    slots, load_ids = _graph_slots(graph)
    if len(load_ids) != 3:
        raise ValueError("COMPOSITION_BOOTSTRAP_QWEN_INPUTS_INVALID")
    kit_digest, frames = keyframes(package)
    observed_inputs = []
    for node_id in load_ids:
        # 02. Pin three source references by real image bytes. The original
        #     graph stays unchanged; none becomes an approved S2/S3 output.
        filename = graph[node_id]["inputs"]["image"]
        image = _observe_input(input_root, filename)
        observed_inputs.append({
            "node_id": node_id, "filename": image["filename"],
            "sha256": image["sha256"], "bytes": image["bytes"],
            "role": "HISTORICAL_GUIDANCE_ONLY",
        })

    # 03. Only the positive prompt, sampler seed and SaveImage prefix can
    #     change; all LoadImage, model, negative and topology inputs are frozen.
    prompt_id = slots["positive_prompt"]["node_id"]
    sampler_id = slots["seed"]["node_id"]
    save_id = slots["output_prefix"]["node_id"]
    files: dict[str, bytes] = {}
    records = []
    for frame in frames:
        shot_id = frame["shot_id"]
        seed = int.from_bytes(hashlib.sha256(
            f"composition-bootstrap|{package_sha}|{shot_id}|{variant}".encode()
        ).digest()[:8], "big") & ((1 << 63) - 1)
        projected = copy.deepcopy(graph)
        projected[prompt_id]["inputs"]["prompt"] = frame["still_prompt"]
        projected[sampler_id]["inputs"]["seed"] = seed
        projected[save_id]["inputs"]["filename_prefix"] = (
            f"PicotooPet/composition_bootstrap/{package_sha[:16]}/{shot_id}/v{variant:04d}"
        )
        graph_name = f"{frame['order']:02d}-{shot_id}.json"
        data = canonical_bytes(projected)
        files[graph_name] = data
        records.append({
            "shot_id": shot_id, "order": frame["order"],
            "graph_file": graph_name, "graph_sha256": sha(data),
            "seed": seed,
            "still_prompt_sha256": sha(frame["still_prompt"].encode("utf-8")),
            "review_checklist": list(frame["review_checklist"]),
            "generated_composition": None,
            "human_visual_review": "NOT_PERFORMED",
        })

    # 04. Deliberately incompatible with the strict output collector's
    #     batch schema: these files are creative bootstrap *proposals* only.
    manifest = {
        "schema": "picotoo.local-composition-bootstrap-dry-run.v1",
        "creative_package_id": package["creative_package_id"],
        "creative_package_sha256": package_sha,
        "keyframe_kit_digest": kit_digest,
        "source_graph_sha256": digest,
        "history_provenance": recovery["history_status"],
        "variant": variant,
        "historical_reference_inputs": observed_inputs,
        "historical_composition_reused_as_guidance_only": True,
        "distinct_shot_compositions_observed": False,
        "shots": records,
        "source_inputs_verified": False,
        "workflow_registered": False,
        "reference_approved": False,
        "production_authorized": False,
        "gpu_post": 0,
    }
    return files, manifest


def _write_candidate(folder: Path, files: dict[str, bytes], manifest: dict) -> bytes:
    """Write one ordinary batch compatible with the existing collector."""
    # 05. Never overwrite existing candidate folders or graph contents.
    #     Manifest is written last, so missing manifest means incomplete.
    folder.mkdir(parents=False, exist_ok=False)
    for name, data in files.items():
        with (folder / name).open("xb") as handle:
            handle.write(data)
    manifest_bytes = canonical_bytes(manifest)
    with (folder / "batch_manifest.json").open("xb") as handle:
        handle.write(manifest_bytes)
    return manifest_bytes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--package-sha256", required=True)
    parser.add_argument("--recovery-dir", type=Path, required=True)
    parser.add_argument("--slot-map", type=Path)
    parser.add_argument("--composition-bootstrap", action="store_true")
    parser.add_argument("--input-root", type=Path)
    parser.add_argument("--variant", type=int, default=0)
    parser.add_argument("--variant-count", type=int, default=1)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        # 06. The legacy single-variant layout stays byte-for-byte
        #     compatible. A multi-variant export is a parent of unchanged
        #     per-variant 3-shot batch folders, not a new collector schema.
        if (not 1 <= args.variant_count <= MAX_VARIANTS_PER_EXPORT
            or not 0 <= args.variant <= 10000
            or args.variant + args.variant_count > 10001):
            raise ValueError("KEYFRAME_VARIANT_RANGE_INVALID")
        package = read_package(args.package, args.package_sha256)
        graph = parse_history(read_bounded(args.recovery_dir / "workflow_api.json"))
        recovery = parse_history(read_bounded(args.recovery_dir / "recovery_manifest.json"))
        # 09. Bootstrap has no strict per-shot composition map yet. Never
        #     silently use a bootstrap graph as a production reference batch.
        if args.composition_bootstrap:
            if args.slot_map is not None or args.input_root is None:
                raise ValueError("COMPOSITION_BOOTSTRAP_ARGUMENTS_INVALID")
            bindings = None
        else:
            if args.slot_map is None:
                raise ValueError("KEYFRAME_SLOT_MAP_REQUIRED")
            bindings = parse_history(read_bounded(args.slot_map))
        prepared = []
        for variant in range(args.variant, args.variant + args.variant_count):
            if args.composition_bootstrap:
                files, manifest = bootstrap_compositions(
                    graph, recovery, package, args.package_sha256,
                    variant, args.input_root
                )
            else:
                files, manifest = prepare(
                    graph, recovery, bindings, package, args.package_sha256,
                    variant, args.input_root
                )
            prepared.append((variant, files, manifest))

        # 07. Prepare and validate all variants BEFORE creating anything.
        #     A partial write never contains the final index manifest.
        if args.variant_count == 1:
            _, files, manifest = prepared[0]
            _write_candidate(args.output_dir, files, manifest)
        else:
            args.output_dir.mkdir(parents=False, exist_ok=False)
            entries = []
            for variant, files, manifest in prepared:
                folder_name = f"v{variant:04d}"
                manifest_bytes = _write_candidate(
                    args.output_dir / folder_name, files, manifest
                )
                entries.append({
                    "variant": variant,
                    "relative_directory": folder_name,
                    "batch_manifest_sha256": sha(manifest_bytes),
                    "shot_count": 3,
                })
            # 08. Index is only an offline navigation aid. Existing
            #     batch_manifest.json remains the sole per-batch contract.
            index = {
                "schema": ("picotoo.local-composition-bootstrap-index.v1"
                           if args.composition_bootstrap else
                           "picotoo.local-keyframe-variant-index.v1"),
                "creative_package_sha256": args.package_sha256,
                "keyframe_kit_digest": prepared[0][2]["keyframe_kit_digest"],
                "variant_count": args.variant_count,
                "variants": entries,
                "source_inputs_verified": False,
                "production_authorized": False,
                "gpu_post": 0,
            }
            with (args.output_dir / "variant_index.json").open("xb") as handle:
                handle.write(canonical_bytes(index))
    except (ValueError, OSError, TypeError, KeyError, IndexError, AttributeError,
            RecursionError, OverflowError, zipfile.BadZipFile, RuntimeError):
        print("KEYFRAME_BATCH=UNVERIFIED; GPU_POST=0", file=sys.stderr)
        return 1
    if args.composition_bootstrap:
        # 10. A reusable historical conditioning image is not a distinct
        #     S2/S3 composition; all three generated images remain absent.
        print("COMPOSITION_BOOTSTRAP=DRY_RUN_ONLY; "
              f"VARIANTS={args.variant_count}; SHOTS_PER_VARIANT=3; GPU_POST=0")
        print("DISTINCT_S2_S3_COMPOSITIONS=NOT_CREATED; OWNER_APPROVAL=FALSE")
    elif args.variant_count == 1:
        print("KEYFRAME_BATCH=DRY_RUN_CANDIDATE; SHOTS=3; GPU_POST=0")
    else:
        print("KEYFRAME_VARIANTS=DRY_RUN_CANDIDATES; "
              f"VARIANTS={args.variant_count}; SHOTS_PER_VARIANT=3; GPU_POST=0")
    print("SOURCE_INPUTS_VERIFIED=FALSE; PRODUCTION_AUTHORIZED=FALSE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
