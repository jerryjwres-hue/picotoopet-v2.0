#!/usr/bin/env python3
"""CPU-only handoff to the ACTUAL, previously successful FLUX.2 board runner.

This tool never starts ComfyUI or calls run_flux_board.main(). The verified
legacy runner retains responsibility for model nodes and image generation.
Input and output are unapproved CREATIVE DRAFTS, not ProductionPlans.
"""

from __future__ import annotations

import argparse
import hashlib
import types
import json
import re
import stat
import tempfile
from pathlib import Path

RUNNER_SHA256 = "fba9b6f004871664c92c75f1c36170a17ceef89b47f3a2c71032df472405d2bd"
LORA_V2_SHA256 = "5972e7f782e3e4ed16b764441fdb66d638cb6a8ba85fb8226d95feeb98e8eb70"
LORA_V2_SIZE = 46_223_616
C8B_MASTER_SHA256 = "c6d7e556b8047d06d6ba7c408e8fdde26d3d16dd59d3c029e901847beac8f59b"
# B1 full SHA is not present in the directly inspectable inventory report.
# An exact SHA is supplied by the Windows-side evidence and rehashed here.
# This does not certify an approved Core asset or a matched scene geometry.
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
    # 01. Core packages and old StoryPacks are distinct input identities.
    core_source = "creative_package_sha256" in spec
    if core_source:
        _validate_sha(spec.get("creative_package_sha256"))
        _validate_sha(spec.get("keyframe_kit_digest"))
        if "source_storypack_sha256" in spec:
            raise _bad("SOURCE_SCOPE_CONFLICT")
    else:
        _validate_sha(spec.get("source_storypack_sha256"))
    shot_id = spec.get("shot_id")
    if not isinstance(shot_id, str) or (
        not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", shot_id) if core_source
        else SHOT_PATTERN.fullmatch(shot_id) is None
    ):
        raise _bad("SHOT_ID_INVALID")
    if core_source and (shot_id in (".", "..")
        or type(spec.get("order")) is not int or not 1 <= spec["order"] <= 3
        or type(spec.get("variant")) is not int or not 0 <= spec["variant"] <= 10000):
        raise _bad("SHOT_VARIANT_INVALID")
    seed = spec.get("seed")
    if type(seed) is not int or not 0 <= seed < 2**64:
        raise _bad("SEED_INVALID")
    prompt = spec.get("prompt")
    if (not isinstance(prompt, str) or not 10 <= len(prompt) <= 10_000
        or "mtai_dog" not in prompt.split(",")):
        raise _bad("PROMPT_TRIGGER_INVALID")
    source_profile = spec.get("source_output_profile")
    if source_profile not in (("video.vertical.v1",) if core_source else ("p0_landscape", "design_portrait")):
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
        # B1 full SHA has not been independently attested in this repo.
        # Only the selected local bytes are checked; Core identity/approval
        # remain false until authenticated registry verification.
        observed.append({
            "role": role, "relative_path": relative,
            "sha256": expected_sha, "bytes": len(data),
        })
        legacy_refs.append(relative)
    # 01. The original runner stages by basename; two different directories
    #     with the same basename would silently bind the last copied image.
    if (len(set(legacy_refs)) != len(legacy_refs)
        or len({Path(item).name.casefold() for item in legacy_refs}) != len(legacy_refs)):
        raise _bad("DUPLICATE_REFERENCES")

    # 06. The current LoRA is v2 only; archived v1 is never a fallback.
    if lora_file.is_symlink() or lora_file.name != "maotai_lora_v2.safetensors":
        raise _bad("LORA_V2_FILENAME_INVALID")
    lora_bytes = _read_regular(lora_file)
    if len(lora_bytes) != LORA_V2_SIZE or _sha(lora_bytes) != LORA_V2_SHA256:
        raise _bad("LORA_V2_SHA_MISMATCH")

    # 07. Execute *the exact bytes already verified*, not a second disk
    #     read between digest verification and module loading (TOCTOU).
    #     The pinned original source only starts ComfyUI in main(); this
    #     module is deliberately named differently, so main() never runs.
    module = types.ModuleType("_picotoo_sha_pinned_original_flux_board")
    module.__file__ = str(runner_file)
    exec(compile(runner_raw.decode("utf-8-sig"), runner_file.name, "exec"),
         module.__dict__)
    if not callable(getattr(module, "build", None)):
        raise _bad("RUNNER_BUILD_NOT_FOUND")

    # 07. Preserve the exact original FLUX node logic (ReferenceLatent,
    #     LoraLoaderModelOnly, Flux2Scheduler) by calling its existing build().
    job = {
        # 02. Per-package, shot and variant output prefixes prevent a reroll
        #     from overwriting or being confused with another candidate.
        "id": (f"P0_{spec['creative_package_sha256'][:16]}_S{spec['order']:02d}_v{spec['variant']:05d}"
               if core_source else "P0_" + shot_id),
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
        **({"creative_package_sha256": spec["creative_package_sha256"],
            "keyframe_kit_digest": spec["keyframe_kit_digest"],
            "order": spec["order"], "variant": spec["variant"]}
           if core_source else {"source_storypack_sha256": spec["source_storypack_sha256"]}),
        "source_output_profile": source_profile,
        "draft_still_profile": "flux2.still.864x1536.v1",
        "source_profile_conversion_performed": False,
        "target_geometry_verified": False,
        "character_master_sha256": C8B_MASTER_SHA256,
        "scene_source_sha256": observed[1]["sha256"],
        "scene_local_bytes_verified": True,
        "scene_core_artifact_binding_verified": False,
        "scene_owner_approval_verified": False,
        "lora_v2_sha256": LORA_V2_SHA256,
        "lora_strength": 0.9,
        "references": observed,
        "shot_id": shot_id,
        "seed": seed,
        "job_file_sha256": _sha(as_bytes["flux_board_single_job.json"]),
        "api_graph_sha256": _sha(as_bytes["flux_board_candidate_api_graph.json"]),
        "graph_canonical_sha256": _sha(as_bytes["flux_board_candidate_api_graph.json"].rstrip(b"\n")),
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


def resolve_reusable_bindings(package_file: Path, package_sha: str,
                              catalog_file: Path, selected_shot: str | None = None) -> dict:
    """Project explicitly bound local draft assets onto the frozen Bible."""
    from prepare_local_keyframe_batch import read_package, keyframes

    package = read_package(package_file, package_sha)
    _, frames = keyframes(package, allow_vertical_guidance=True, allow_i2v_guidance=True)
    bible = package["stage_results"]["video_bible.v1"]
    catalog = _read_json(catalog_file)
    # 01. This is a reusable local binding preference, not another asset
    #     registry or an Owner approval. Require the entire exact subject.
    if (set(catalog) != {"schema", "subject", "character_master", "scenes"}
        or catalog["schema"] != "picotoo.flux-reusable-draft-bindings.v1"
        or not isinstance(catalog["subject"], dict)
        or catalog["subject"] != bible.get("subject")
        or catalog["subject"].get("kind") != "PET"
        or bible.get("product", False) is not None):
        raise _bad("REUSABLE_SUBJECT_OR_PRODUCT_MISMATCH")
    character = catalog["character_master"]
    if (not isinstance(character, dict) or set(character) != {"role", "relative_path", "sha256"}
        or character["role"] != "character_master"
        or character["sha256"] != C8B_MASTER_SHA256):
        raise _bad("REUSABLE_CHARACTER_MISMATCH")
    # 02. Exact scene specification, including environment/light/palette;
    #     a similar name or generic room ID never authorizes reuse.
    scenes = catalog["scenes"]
    bible_scenes = bible.get("scenes")
    bible_shots = bible.get("shots")
    if (not isinstance(scenes, list) or not 1 <= len(scenes) <= 32
        or not isinstance(bible_scenes, list) or not isinstance(bible_shots, list)
        or len(bible_shots) != len(frames)
        or any(not isinstance(item, dict) or set(item) != {"scene", "references"}
               or not isinstance(item["scene"], dict) for item in scenes)
        or any(not isinstance(item, dict) for item in bible_scenes + bible_shots)):
        raise _bad("REUSABLE_SCENE_SCHEMA_INVALID")
    by_scene = {item.get("scene_id"): item for item in bible_scenes}
    by_shot = {item.get("shot_id"): item for item in bible_shots}
    if len(by_scene) != len(bible_scenes) or len(by_shot) != len(bible_shots):
        raise _bad("REUSABLE_BIBLE_IDENTITY_INVALID")
    wanted = [frame for frame in frames if selected_shot is None or frame["shot_id"] == selected_shot]
    if not wanted:
        raise _bad("CORE_SHOT_REFERENCES_MISSING")
    mapped = {}
    for frame in wanted:
        shot = by_shot.get(frame["shot_id"])
        if (shot is None or shot.get("order") != frame["order"]
            or "SUBJECT" not in shot.get("featured", [])):
            raise _bad("REUSABLE_SHOT_SCOPE_MISMATCH")
        scene = by_scene.get(shot.get("scene_id"))
        matches = [item for item in scenes if item["scene"] == scene]
        if scene is None or len(matches) != 1:
            raise _bad("REUSABLE_SCENE_BINDING_MISSING_OR_AMBIGUOUS")
        refs = matches[0]["references"]
        # 03. Only a scene master is reusable automatically. Per-shot props
        #     and layout images require the original explicit package map.
        if (not isinstance(refs, list) or len(refs) != 1
            or not isinstance(refs[0], dict)
            or set(refs[0]) != {"role", "relative_path", "sha256"}
            or refs[0]["role"] != "scene_master"):
            raise _bad("REUSABLE_SCENE_REFERENCE_INVALID")
        mapped[frame["shot_id"]] = [dict(character), dict(refs[0])]
    # The existing prepare() verifies actual file hashes, roles, and LoRA
    # before any graph is built. No source rights or visual PASS is inferred.
    return {"schema": "picotoo.flux-board-reference-map.v1",
            "creative_package_sha256": package_sha, "shots": mapped}


def prepare_package_batch(*, package_file: Path, package_sha: str,
                          bindings_file: Path, runner_file: Path, lora_file: Path,
                          output_dir: Path, variant: int, selected_shot: str | None = None) -> dict:
    """Prepare a frozen Core Keyframe Kit with the existing FLUX builder.

    Default is all three shots; a specific shot reroll preserves all others.
    Output is a creative draft only, never a GPU submission or approval.
    """
    # 01. Reuse the already shipped ZIP/kit/bible verification and shot order.
    from prepare_local_keyframe_batch import read_package, keyframes

    if type(variant) is not int or not 0 <= variant <= 10000:
        raise _bad("SHOT_VARIANT_INVALID")
    package = read_package(package_file, package_sha)
    if package["stage_results"]["creative_brief.v1"]["output_profile_id"] != "video.vertical.v1":
        raise _bad("CORE_PORTRAIT_PACKAGE_REQUIRED")
    kit_digest, frames = keyframes(package, allow_vertical_guidance=True, allow_i2v_guidance=True)
    bindings = _read_json(bindings_file)
    if (set(bindings) != {"schema", "creative_package_sha256", "shots"}
        or bindings["schema"] != "picotoo.flux-board-reference-map.v1"
        or bindings["creative_package_sha256"] != package_sha
        or not isinstance(bindings["shots"], dict)
        or not set(bindings["shots"]).issubset({frame["shot_id"] for frame in frames})):
        raise _bad("CORE_REFERENCE_MAP_INVALID")
    wanted = [frame for frame in frames if selected_shot is None or frame["shot_id"] == selected_shot]
    if not wanted or any(frame["shot_id"] not in bindings["shots"] for frame in wanted):
        raise _bad("CORE_SHOT_REFERENCES_MISSING")
    if output_dir.exists() or output_dir.is_symlink() or not output_dir.parent.is_dir():
        raise _bad("OUTPUT_DIR_MUST_BE_NEW")
    records, jobs = [], []
    # 02. Stage the entire batch privately. Missing or changed references in
    #     shot 3 must not publish a partial shot 1/2 export.
    with tempfile.TemporaryDirectory(prefix=".flux-batch-", dir=output_dir.parent) as staging:
        stage = Path(staging)
        payload = stage / "batch"
        payload.mkdir()
        for frame in wanted:
            shot_id, order = frame["shot_id"], frame["order"]
            seed = int.from_bytes(hashlib.sha256(
                f"{package_sha}|{shot_id}|{variant}".encode("utf-8")).digest()[:8], "big") & ((1 << 63) - 1)
            # 03. Preserve the complete frozen still prompt; add only the
            #     known trained LoRA trigger if it is not already the first token.
            prompt = frame["still_prompt"]
            if "mtai_dog" not in prompt.split(","):
                prompt = "mtai_dog, " + prompt
            request = {
                "schema": REQUEST_SCHEMA, "creative_package_sha256": package_sha,
                "keyframe_kit_digest": kit_digest, "source_output_profile": "video.vertical.v1",
                "shot_id": shot_id, "order": order, "variant": variant, "seed": seed,
                "prompt": prompt, "references": bindings["shots"][shot_id],
            }
            request_path = stage / "request.json"
            request_path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
            folder = payload / f"shot-{order:02d}"
            folder.mkdir()
            result = prepare(request_file=request_path, runner_file=runner_file,
                             lora_file=lora_file, output_dir=folder)
            # 03b. The original runner main() accepts one jobs file, loops
            #      through jobs sequentially, and copies each output as id_v1.png.
            single = _read_json(folder / "flux_board_single_job.json")
            job = single["jobs"][0]
            jobs.append(job)
            records.append({
                "runner_output_filename": job["id"] + "_v1.png",
                "shot_id": shot_id, "order": order, "seed": seed,
                "relative_directory": folder.name,
                "api_graph_sha256": result["api_graph_sha256"],
                "graph_canonical_sha256": result["graph_canonical_sha256"],
                "handoff_manifest_sha256": _sha((folder / "flux_board_handoff_manifest.json").read_bytes()),
                "still_prompt_sha256": _sha(frame["still_prompt"].encode("utf-8")),
                "review_checklist": frame["review_checklist"],
            })
        # 04. Unique batch destination under the original runner directory.
        #     Preparation does not execute the GPU or create the destination.
        suffix = "all" if selected_shot is None else f"s{wanted[0]['order']:02d}"
        runner_out = f"keyframes_p0_{package_sha[:16]}_v{variant:05d}_{suffix}"
        if (runner_file.parent / runner_out).exists() or (runner_file.parent / runner_out).is_symlink():
            raise _bad("RUNNER_OUTPUT_ALREADY_EXISTS")
        runner_jobs = json.dumps({"out": runner_out, "jobs": jobs}, sort_keys=True,
                                 ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
        (payload / "flux_board_jobs.json").write_bytes(runner_jobs)
        manifest = {
            "schema": "picotoo.existing-flux-board-batch.v1",
            "runner_output_directory": runner_out,
            "runner_jobs_sha256": _sha(runner_jobs),
            "creative_package_id": package["creative_package_id"],
            "creative_package_sha256": package_sha, "keyframe_kit_digest": kit_digest,
            "variant": variant, "selected_shot": selected_shot, "shots": records,
            "production_authorized": False, "owner_approved": False, "gpu_post": 0,
        }
        (payload / "batch_manifest.json").write_bytes(
            json.dumps(manifest, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n")
        # 04. No overwrite; Windows rename fails if a destination already exists.
        if output_dir.exists() or output_dir.is_symlink():
            raise _bad("OUTPUT_DIR_MUST_BE_NEW")
        payload.rename(output_dir)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="CPU-only FLUX.2 legacy board handoff")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--request", type=Path)
    source.add_argument("--package", type=Path)
    parser.add_argument("--package-sha256")
    parser.add_argument("--reference-map", type=Path)
    parser.add_argument("--variant", type=int, default=0)
    parser.add_argument("--shot")
    parser.add_argument("--runner", type=Path, required=True)
    parser.add_argument("--lora", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.package is not None:
        if args.package_sha256 is None or args.reference_map is None:
            parser.error("--package requires --package-sha256 and --reference-map")
        result = prepare_package_batch(package_file=args.package, package_sha=args.package_sha256,
            bindings_file=args.reference_map, runner_file=args.runner, lora_file=args.lora,
            output_dir=args.output_dir, variant=args.variant, selected_shot=args.shot)
        print("FLUX_P0_6_HANDOFF=CREATIVE_DRAFT_BATCH_ONLY")
        print("SHOT_COUNT=" + str(len(result["shots"])))
    else:
        if args.package_sha256 is not None or args.reference_map is not None or args.shot is not None or args.variant != 0:
            parser.error("package options require --package")
        result = prepare(request_file=args.request, runner_file=args.runner,
                         lora_file=args.lora, output_dir=args.output_dir)
        print("FLUX_P0_6_HANDOFF=CREATIVE_DRAFT_ONLY")
        print("GRAPH_SHA256=" + result["api_graph_sha256"])
    print("PRODUCTION_AUTHORIZED=FALSE; GPU_POST=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
