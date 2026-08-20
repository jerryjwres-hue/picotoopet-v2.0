from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TOOL_ROOT       = REPOSITORY_ROOT / "windows" / "desktop" / "tools" / "maotai_v2_assets"
MANIFEST_PATH   = (
    REPOSITORY_ROOT
    / "windows"
    / "desktop"
    / "src"
    / "PicotooPet.Desktop"
    / "Views"
    / "Controls"
    / "MaotaiMotion"
    / "MaotaiAssetManifest.cs"
)
ART_JOB_PATH    = TOOL_ROOT / "build_maotai_v2_art_jobs.py"


if str(TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOL_ROOT))


def _load_builder():
    """直接加载仓库内生产器，避免测试依赖可编辑安装环境。"""
    spec = importlib.util.spec_from_file_location("maotai_v2_design_fidelity_builder", ART_JOB_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_all_organic_parts_share_one_canonical_identity_anchor() -> None:
    builder = _load_builder()
    plan    = builder.build_art_plan(MANIFEST_PATH, scale=4.0)

    policy = plan["generation_policy"]
    assert policy["canonical_view"] == "three-quarter front"
    assert policy["identity_anchor"] == "03_working_happy.png"
    assert policy["geometry_reference"] == "01_maotai_rig_design_sheet.png"
    assert policy["camera_locked_across_jobs"] is True
    assert policy["lighting_locked_across_jobs"] is True
    assert policy["structural_anisotropic_warp_forbidden"] is True

    # Organic surfaces      : completed character art owns identity/material; the rig sheet owns geometry only.
    organic_categories = {"core", "face", "limb", "tail", "accessory"}
    organic_jobs       = [job for job in plan["jobs"] if job["category"] in organic_categories]
    assert organic_jobs
    assert {
        job["primary_reference"]
        for job in organic_jobs
    } == {"03_working_happy.png"}


def test_structural_prompts_forbid_visible_joint_hardware_and_body_stumps() -> None:
    builder = _load_builder()
    plan    = builder.build_art_plan(MANIFEST_PATH, scale=4.0)
    jobs    = {job["target_file"]: job for job in plan["jobs"]}

    # Torso contract        : attachment zones are continuous fur, never visible sockets or pre-rendered limb stumps.
    torso_prompt   = jobs["torso_neutral.png"]["positive_prompt"].lower()
    torso_negative = jobs["torso_neutral.png"]["negative_prompt"].lower()
    assert "continuous fur attachment zones" in torso_prompt
    assert "no visible joint socket" in torso_prompt
    assert "geometry guide only" in torso_prompt
    assert "limb stump" in torso_negative
    assert "circular connector" in torso_negative

    # Limb contract         : each segment owns only its local fur volume and hides the connection inside overlap fur.
    limb_prompt   = jobs["front_left_upper.png"]["positive_prompt"].lower()
    limb_negative = jobs["front_left_upper.png"]["negative_prompt"].lower()
    assert "no cuff" in limb_prompt
    assert "no hard ring" in limb_prompt
    assert "geometry guide only" in limb_prompt
    assert "socket ring" in limb_negative
    assert "mechanical connector" in limb_negative


def test_job_metadata_exposes_separate_identity_and_geometry_sources() -> None:
    builder = _load_builder()
    plan    = builder.build_art_plan(MANIFEST_PATH, scale=4.0)

    for job in plan["jobs"]:
        fidelity = job["design_fidelity"]
        assert fidelity["canonical_view"] == "three-quarter front"
        assert fidelity["identity_anchor"] == "03_working_happy.png"
        assert fidelity["geometry_reference"] == "01_maotai_rig_design_sheet.png"
        assert fidelity["preserve_native_aspect"] is True
        assert fidelity["assembly_preview_required"] is True


def test_structural_jobs_cannot_be_promoted_as_rectangular_texture_plates() -> None:
    builder = _load_builder()
    plan    = builder.build_art_plan(MANIFEST_PATH, scale=4.0)
    jobs    = {job["target_file"]: job for job in plan["jobs"]}

    structural_files = {
        "torso_neutral.png",
        "torso_crouch.png",
        "torso_stretch.png",
        "head.png",
        "front_left_upper.png",
        "front_left_lower.png",
        "front_right_upper.png",
        "front_right_lower.png",
        "hind_left_upper.png",
        "hind_left_lower.png",
        "hind_right_upper.png",
        "hind_right_lower.png",
        "tail_base.png",
        "tail_mid.png",
        "tail_tip.png",
    }

    for file_name in structural_files:
        quality = jobs[file_name]["structural_quality"]
        assert quality["gate"] == "organic_silhouette"
        assert quality["reject_rectangular_plate"] is True
        assert quality["require_soft_alpha_edge"] is True
        assert quality["forbid_visible_connector_geometry"] is True
        assert quality["assembly_preview_required"] is True
