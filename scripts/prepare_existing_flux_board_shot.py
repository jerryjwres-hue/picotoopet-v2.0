#!/usr/bin/env python3
"""CPU-only handoff to the ACTUAL, previously successful FLUX.2 board runner.

This tool never starts ComfyUI or calls run_flux_board.main(). The verified
legacy runner retains responsibility for model nodes and image generation.
Input and output are unapproved CREATIVE DRAFTS, not ProductionPlans.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import stat
from pathlib import Path

RUNNER_SHA256 = "fba9b6f004871664c92c75f1c36170a17ceef89b47f3a2c71032df472405d2bd"
LORA_V2_SHA256 = "5972e7f782e3e4ed16b764441fdb66d638cb6a8ba85fb8226d95feeb98e8eb70"
LORA_V2_SIZE = 46_223_616
C8B_MASTER_SHA256 = "c6d7e556b8047d06d6ba7c408e8fdde26d3d16dd59d3c029e901847beac8f59b"
B1_SCENE_SHA256 = "c89f7c8d8e44b97d884fb6ad4e6f53e2873a7836422bb7e747b8711e4382c043"
SHA_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
SHOT_PATTERN = re.compile(r"S0[1-3]\Z")
FILENAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,120}\Z")
REQUEST_SCHEMA = "picotoo.existing-flux-board-shot.v1"
MANIFEST_SCHEMA = "picotoo.existing-flux-board-handoff.v1"


def _bad(reason: str) -> ValueError:
    return ValueError("FLUX_EXISTING_BOARD_" + reason)


def _json_pairs(values: list[tuple[str, object]]) -> dict:
    # 01. A repeated key must never silently replace a frozen SHA or prompt.
    output: dict = {}
    for key, value in values:
        if key in output:
            raise _bad("DUPLICATE_JSON_KEY")
        output[key] = value
    return output


def _read_json(path: Path) -> dict:
    raw = _read_regular(path, max_bytes=256_000)
    value = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_json_pairs)
    if not isinstance(value, dict):
        raise _bad("REQUEST_SCHEMA_INVALID")
    return value


def _read_regular(path: Path, *, max_bytes: int = 80_000_000) -> bytes:
    # 02. Do not dereference symlinks or trust truncated/max-size files.
    if path.is_symlink() or not path.is_file():
        raise _bad("INPUT_NOT_REGULAR")
    item = path.stat()
    if not stat.S_ISREG(item.st_mode) or item.st_size < 1 or item.st_size > max_bytes:
        raise _bad("INPUT_SIZE_INVALID")
    raw = path.read_bytes()
    if len(raw) != item.st_size:
        raise _bad("INPUT_CHANGED_DURING_READ")
    return raw


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _validate_sha(value: object) -> str:
    if not isinstance(value, str) or SHA_PATTERN.fullmatch(value) is None:
        raise _bad("SHA256_REQUIRED")
    return value


def _resolve_ref(root: Path, relative: object) -> Path:
    # 03. Original runner interprets refs relative to the runner script.
    #     Do not allow absolute paths, nested links or directory traversal.
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise _bad("REFERENCE_RELATIVE_PATH_INVALID")
    parts = Path(relative).parts
    if Path(relative).is_absolute() or any(part in (".", "..") for part in parts):
        raise _bad("REFERENCE_RELATIVE_PATH_INVALID")
    candidate = root.joinpath(*parts)
    if not candidate.resolve().is_relative_to(root.resolve()):
        raise _bad("REFERENCE_ESCAPES_RUNNER")
    current = root
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise _bad("REFERENCE_SYMLINK_DENIED")
    return candidate


def prepare(
    *,
    request_file: Path,
    runner_file: Path,
    lora_file: Path,
    output_dir: Path,
) -> dict:
    """Create one verified legacy jobs JSON and exact-node graph, with no GPU."""
    # 04. The *original* source is SHA pinned, so import may not silently
    #     execute an unrelated or newly edited local Python program.
    runner_raw = _read_regular(runner_file, max_bytes=128_000)
    if _sha(runner_raw) != RUNNER_SHA256:
        raise _bad("RUNNER_SOURCE_SHA_MISMATCH")
    if runner_file.name != "run_flux_board.py":
        raise _bad("RUNNER_NAME_INVALID")

    spec = _read_json(request_file)
    if spec.get("schema") != REQUEST_SCHEMA:
        raise _bad("REQUEST_SCHEMA_INVALID")
    _validate_sha(spec.get("source_storypack_sha256"))
    shot_id = spec.get("shot_id")
    if not isinstance(shot_id, str) or SHOT_PATTERN.fullmatch(shot_id) is None:
        raise _bad("SHOT_ID_INVALID")
    seed = spec.get("seed")
    if type(seed) is not int or not 0 <= seed < 2**64:
        raise _bad("SEED_INVALID")
    prompt = spec.get("prompt")
    if (not isinstance(prompt, str) or not 10 <= len(prompt) <= 10_000
        or "mtai_dog" not in prompt.split(",")):
        raise _bad("PROMPT_TRIGGER_INVALID")
    source_profile = spec.get("source_output_profile")
    if source_profile not in ("p0_landscape", "design_portrait"):
        raise _bad("SOURCE_PROFILE_UNKNOWN")

    # 05. This always generates a portrait draft 864x1536 because that is
    #     the validated runner behavior. It DOES NOT rewrite the StoryPack
    #     profile, certify geometry, or make video I2V inputs approved.
    references = spec.get("references")
    if not isinstance(references, list) or not 2 <= len(references) <= 4:
        raise _bad("REFERENCE_COUNT_INVALID")
    expected_roles = ("character_master", "scene_master")
    observed: list[dict] = []
    legacy_refs: list[str] = []
    for index, entry in enumerate(references):
        if not isinstance(entry, dict):
            raise _bad("REFERENCE_SCHEMA_INVALID")
        role = entry.get("role")
        if index < 2 and role != expected_roles[index]:
            raise _bad("REFERENCE_ORDER_INVALID")
        if index >= 2 and role not in ("prop", "layout"):
            raise _bad("REFERENCE_ROLE_INVALID")
        relative = entry.get("relative_path")
        path = _resolve_ref(runner_file.parent, relative)
        if not FILENAME_PATTERN.fullmatch(path.name):
            raise _bad("REFERENCE_FILENAME_INVALID")
        expected_sha = _validate_sha(entry.get("sha256"))
        data = _read_regular(path)
        if _sha(data) != expected_sha:
            raise _bad("REFERENCE_SHA_MISMATCH")
        if index == 0 and expected_sha != C8B_MASTER_SHA256:
            raise _bad("NOT_APPROVED_C8B_IDENTITY_SOURCE")
        if index == 1 and expected_sha != B1_SCENE_SHA256:
            raise _bad("NOT_REGISTERED_B1_SCENE_SOURCE")
        observed.append({
            "role": role, "relative_path": relative,
            "sha256": expected_sha, "bytes": len(data),
        })
        legacy_refs.append(relative)
    if len(set(legacy_refs)) != len(legacy_refs):
        raise _bad("DUPLICATE_REFERENCES")

    # 06. The current LoRA is v2 only; archived v1 is never a fallback.
    if lora_file.is_symlink() or lora_file.name != "maotai_lora_v2.safetensors":
        raise _bad("LORA_V2_FILENAME_INVALID")
    lora_bytes = _read_regular(lora_file)
    if len(lora_bytes) != LORA_V2_SIZE or _sha(lora_bytes) != LORA_V2_SHA256:
        raise _bad("LORA_V2_SHA_MISMATCH")

    runner_spec = importlib.util.spec_from_file_location(
        "_picotoo_sha_pinned_original_flux_board", str(runner_file)
    )
    if runner_spec is None or runner_spec.loader is None:
        raise _bad("RUNNER_LOAD_FAILED")
    module = importlib.util.module_from_spec(runner_spec)
    runner_spec.loader.exec_module(module)
    if not callable(getattr(module, "build", None)):
        raise _bad("RUNNER_BUILD_NOT_FOUND")

    # 07. Preserve the exact original FLUX node logic (ReferenceLatent,
    #     LoraLoaderModelOnly, Flux2Scheduler) by calling its existing build().
    job = {
        "id": "P0_" + shot_id,
        "refs": legacy_refs,
        "seeds": [seed],
        "prompt": prompt,
        "lora": {"name": lora_file.name, "strength": 0.9},
        "w": 864,
        "h": 1536,
    }
    node_refs = ["PTV2_" + Path(item).name for item in legacy_refs]
    graph = module.build(job, seed, node_refs)
    if (not isinstance(graph, dict) or graph.get("6", {}).get("class_type") != "LoraLoaderModelOnly"
        or graph["6"]["inputs"].get("strength_model") != 0.9
        or graph["4"]["inputs"].get("text") != prompt
        or graph["20"]["inputs"].get("width") != 864
        or graph["20"]["inputs"].get("height") != 1536
        or graph["23"]["inputs"].get("noise_seed") != seed
        or graph["27"]["inputs"].get("filename_prefix") != "PTV2_" + job["id"]):
        raise _bad("LEGACY_GRAPH_CONTRACT_MISMATCH")
    for index, name in enumerate(node_refs):
        if graph.get(str(100 + 10 * index), {}).get("inputs", {}).get("image") != name:
            raise _bad("GRAPH_REFERENCES_CHANGED")

    # 08. Write separately from the legacy runner directory. Running
    #     run_flux_board.main() is deliberately NOT part of this tool.
    if output_dir.is_symlink() or not output_dir.is_dir() or any(output_dir.iterdir()):
        raise _bad("OUTPUT_DIR_MUST_BE_EMPTY")
    legacy_jobs = {"out": "keyframes_p0_new_review", "jobs": [job]}
    files = {
        "flux_board_single_job.json": legacy_jobs,
        "flux_board_candidate_api_graph.json": graph,
    }
    as_bytes = {
        name: json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8") + b"\n"
        for name, value in files.items()
    }
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "runner_source_sha256": RUNNER_SHA256,
        "source_storypack_sha256": spec["source_storypack_sha256"],
        "source_output_profile": source_profile,
        "draft_still_profile": "flux2.still.864x1536.v1",
        "source_profile_conversion_performed": False,
        "target_geometry_verified": False,
        "character_master_sha256": C8B_MASTER_SHA256,
        "scene_master_sha256": B1_SCENE_SHA256,
        "lora_v2_sha256": LORA_V2_SHA256,
        "lora_strength": 0.9,
        "references": observed,
        "shot_id": shot_id,
        "seed": seed,
        "job_file_sha256": _sha(as_bytes["flux_board_single_job.json"]),
        "api_graph_sha256": _sha(as_bytes["flux_board_candidate_api_graph.json"]),
        "input_state": "LOCAL_BYTES_VERIFIED_CREATIVE_DRAFT",
        "production_authorized": False,
        "owner_approved": False,
        "gpu_post": 0,
        "existing_runner_executed": False,
        "needs_manual_review": True,
    }
    as_bytes["flux_board_handoff_manifest.json"] = (
        json.dumps(manifest, sort_keys=True, ensure_ascii=False,
                   separators=(",", ":")).encode("utf-8") + b"\n"
    )
    for name, raw in as_bytes.items():
        (output_dir / name).write_bytes(raw)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="CPU-only FLUX.2 legacy board handoff")
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--runner", type=Path, required=True)
    parser.add_argument("--lora", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = prepare(
        request_file=args.request, runner_file=args.runner,
        lora_file=args.lora, output_dir=args.output_dir,
    )
    print("FLUX_P0_6_HANDOFF=CREATIVE_DRAFT_ONLY")
    print("GRAPH_SHA256=" + result["api_graph_sha256"])
    print("PRODUCTION_AUTHORIZED=FALSE; GPU_POST=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
