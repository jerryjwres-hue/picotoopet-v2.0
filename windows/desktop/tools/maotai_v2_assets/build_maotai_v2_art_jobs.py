from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Iterable


_TOOL_DIRECTORY = str(Path(__file__).resolve().parent)

from maotai_manifest_contract import AssetDescriptor, parse_manifest


DEFAULT_REFERENCE_FILES = (
    "01_maotai_rig_design_sheet.png",
    "03_working_happy.png",
    "04_working_tired.png",
    "05_working_annoyed.png",
    "06_idle_paw.png",
)

_MIN_SCALE = 2.0


def build_art_plan(
    manifest_path: Path | str,
    *,
    scale: float = 4.0,
    reference_files: Iterable[str] | None = None,
) -> dict[str, object]:
    """从 C# manifest 生成一部件一任务的生产计划，不维护第二份资产清单。"""
    if not isinstance(scale, (int, float)) or scale < _MIN_SCALE:
        raise ValueError("Maotai v2 art scale must be at least 2x logical size")

    manifest    = Path(manifest_path).resolve()
    descriptors = parse_manifest(manifest)
    references  = _normalize_reference_files(reference_files)
    jobs        = [
        _build_job(descriptor, scale=float(scale), references=references)
        for descriptor in descriptors.values()
    ]

    validator = _relative_to_repo(Path(_TOOL_DIRECTORY) / "validate_maotai_v2_assets.py")
    return {
        "schema_version": 1,
        "source_of_truth": _relative_to_repo(manifest),
        "reference_files": list(references),
        "generation_policy": {
            "parts_per_job": 1,
            "source_mode": "reference_only",
            "default_scale": float(scale),
            "canonical_view": "three-quarter front",
            "transparent_background_required": True,
            "whole_character_crop_forbidden": True,
        },
        "jobs": jobs,
        "staging": {
            "validator": validator,
            "all_assets_required_before_stage": True,
            "command": f"python {validator} stage <incoming_dir>",
        },
    }


def _build_job(
    descriptor: AssetDescriptor,
    *,
    scale: float,
    references: tuple[str, ...],
) -> dict[str, object]:
    part_name = descriptor.file_name.removesuffix(".png").replace("_", " ")
    category  = _part_category(descriptor.file_name)
    width_px  = round(descriptor.logical_width * scale)
    height_px = round(descriptor.logical_height * scale)
    pivot_x   = descriptor.pivot_x * scale
    pivot_y   = descriptor.pivot_y * scale
    overlap   = descriptor.joint_overlap_pixels * scale

    return {
        "target_file": descriptor.file_name,
        "category": category,
        "seed_family": _seed_family(descriptor.file_name),
        "reference_files": list(references),
        "primary_reference": _primary_reference(category),
        "output": {
            "width_px": width_px,
            "height_px": height_px,
            "transparent_png": True,
        },
        "pivot_px": {
            "x": pivot_x,
            "y": pivot_y,
        },
        "joint_overlap_px": overlap,
        "positive_prompt": _positive_prompt(
            part_name=part_name,
            category=category,
            width_px=width_px,
            height_px=height_px,
            pivot_x=pivot_x,
            pivot_y=pivot_y,
            overlap=overlap,
        ),
        "negative_prompt": _negative_prompt(),
    }


def _positive_prompt(
    *,
    part_name: str,
    category: str,
    width_px: int,
    height_px: int,
    pivot_x: float,
    pivot_y: float,
    overlap: float,
) -> str:
    category_instruction = {
        "core": (
            "Preserve the canonical silhouette and attachment geometry; torso variants may change "
            "only the intended crouch/stretch silhouette, never camera or identity."
        ),
        "face": (
            "Render only the requested facial/head component with matching fur direction, material, "
            "expression language, and transparent padding around the overlay."
        ),
        "limb": (
            "Render only this limb segment or paw in the canonical joint orientation; preserve generous "
            "hidden attachment fur so rotation cannot reveal seams."
        ),
        "tail": (
            "Render only this tail segment with continuous fur flow and generous hidden attachment fur "
            "for rotation overlap."
        ),
        "accessory": (
            "Render only the requested blue-headphone component, matching the canonical material, "
            "lighting, perspective, and attachment angle."
        ),
        "prop": (
            "Render only the requested desktop-pet prop with the same canonical camera, soft CG light, "
            "and transparent isolation."
        ),
    }[category]

    return (
        f"Create exactly one isolated independent raster component: {part_name}. "
        "Character identity is Maotai, a premium cute chibi Alaskan Malamute desktop pet with soft "
        "high-end 3D CG fur rendering and the established blue-headphone visual identity where relevant. "
        "Use the exact canonical three-quarter front perspective, proportions, fur colors, material response, "
        "and studio lighting from the supplied reference images. References are identity/style/pose guidance "
        "only; do not crop or extract pixels from them. "
        f"{category_instruction} "
        f"Final canvas is {width_px}x{height_px}px with transparent background. "
        f"Target logical pivot maps to approximately ({pivot_x:.1f}, {pivot_y:.1f})px on this canvas. "
        f"Where this part attaches, preserve hidden fur overlap of approximately {overlap:.1f}px; for overlays "
        "without a rotating joint, preserve clean transparent padding while keeping the same hidden fur overlap "
        "production margin. Keep the requested component fully inside the canvas with transparent edge padding."
    )


def _negative_prompt() -> str:
    return (
        "complete dog, assembled dog, full-body character, whole character frame, complete head when only a "
        "sub-part is requested, extra limb, duplicate part, additional body parts, disconnected duplicate fur, "
        "sprite sheet, contact sheet, exploded sheet, grid, panel layout, crop marks, labels, text, typography, "
        "UI, interface, scenery, room, landscape, decorative background, white background, opaque background, "
        "colored background, hard rectangle edge, clipping, cutout from a complete dog, inconsistent camera, "
        "different breed, husky identity drift, mismatched lighting, mismatched fur palette, low-detail vector art"
    )


def _normalize_reference_files(reference_files: Iterable[str] | None) -> tuple[str, ...]:
    values = tuple(reference_files) if reference_files is not None else DEFAULT_REFERENCE_FILES
    if not values:
        raise ValueError("at least one Maotai reference file is required")

    normalized: list[str] = []
    for value in values:
        name = str(value).strip()
        if not name or Path(name).name != name or "/" in name or "\\" in name:
            raise ValueError(f"reference files must be basenames only: {value!r}")
        normalized.append(name)
    return tuple(normalized)


def _part_category(file_name: str) -> str:
    stem = file_name.removesuffix(".png")
    if stem.startswith(("torso_", "chest_")):
        return "core"
    if stem.startswith(("headphone_",)):
        return "accessory"
    if stem.startswith(("front_", "hind_")):
        return "limb"
    if stem.startswith("tail_"):
        return "tail"
    if stem in {"laptop", "drink", "shadow"}:
        return "prop"
    return "face"


def _primary_reference(category: str) -> str:
    if category in {"core", "face", "accessory"}:
        return "03_working_happy.png"
    if category == "limb":
        return "06_idle_paw.png"
    return "01_maotai_rig_design_sheet.png"


def _seed_family(file_name: str) -> str:
    stem = file_name.removesuffix(".png")
    if stem.startswith("torso_"):
        return "torso"

    mirrored = re.sub(r"(^|_)left(?=_|$)", r"\1side", stem)
    mirrored = re.sub(r"(^|_)right(?=_|$)", r"\1side", mirrored)
    return mirrored


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _relative_to_repo(path: Path) -> str:
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(_repository_root().resolve())
    except ValueError:
        return resolved.as_posix()
    return relative.as_posix()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a manifest-derived one-component-per-job Maotai v2 art production plan.",
    )
    parser.add_argument("manifest", type=Path, nargs="?", default=_default_manifest_path())
    parser.add_argument("--scale", type=float, default=4.0)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reference", action="append", dest="references")
    return parser


def _default_manifest_path() -> Path:
    return (
        _repository_root()
        / "windows"
        / "desktop"
        / "src"
        / "PicotooPet.Desktop"
        / "Views"
        / "Controls"
        / "MaotaiMotion"
        / "MaotaiAssetManifest.cs"
    )


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    plan = build_art_plan(
        args.manifest,
        scale=args.scale,
        reference_files=args.references,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"MAOTAI_V2_ART_JOBS={len(plan['jobs'])} | {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
