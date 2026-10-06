from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TOOL_ROOT       = (
    REPOSITORY_ROOT
    / "windows"
    / "desktop"
    / "tools"
    / "maotai_v2_assets"
)
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
RUNNER_PATH     = TOOL_ROOT / "run_maotai_v2_comfyui_jobs.py"


if str(TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOL_ROOT))

from maotai_manifest_contract import parse_manifest  # noqa: E402


def _load_module(path: Path, module_name: str):
    """按仓库文件加载工具，保证 contract test 不依赖可编辑安装副作用。"""
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_art_plan_is_manifest_derived_and_one_component_per_job() -> None:
    builder     = _load_module(ART_JOB_PATH, "build_maotai_v2_art_jobs")
    descriptors = parse_manifest(MANIFEST_PATH)

    plan = builder.build_art_plan(MANIFEST_PATH, scale=4.0)
    jobs = plan["jobs"]

    assert [job["target_file"] for job in jobs] == list(descriptors)
    assert len(jobs) == len(descriptors)
    assert len({job["target_file"] for job in jobs}) == len(jobs)
    assert plan["source_of_truth"] == str(MANIFEST_PATH.relative_to(REPOSITORY_ROOT)).replace("\\", "/")
    assert plan["generation_policy"]["parts_per_job"] == 1
    assert plan["generation_policy"]["source_mode"] == "reference_only"

    for job in jobs:
        assert "crop_source" not in job
        assert "sheet_region" not in job
        assert job["target_file"].endswith(".png")
        assert job["output"]["transparent_png"] is True


def test_art_plan_scales_canvas_pivot_and_overlap_from_manifest() -> None:
    builder     = _load_module(ART_JOB_PATH, "build_maotai_v2_art_jobs_scale")
    descriptors = parse_manifest(MANIFEST_PATH)
    plan        = builder.build_art_plan(MANIFEST_PATH, scale=4.0)
    jobs        = {job["target_file"]: job for job in plan["jobs"]}

    for file_name, descriptor in descriptors.items():
        job = jobs[file_name]
        assert job["output"]["width_px"] == round(descriptor.logical_width * 4.0)
        assert job["output"]["height_px"] == round(descriptor.logical_height * 4.0)
        assert job["pivot_px"] == {
            "x": descriptor.pivot_x * 4.0,
            "y": descriptor.pivot_y * 4.0,
        }
        assert job["joint_overlap_px"] == descriptor.joint_overlap_pixels * 4.0

    with pytest.raises(ValueError, match="2"):
        builder.build_art_plan(MANIFEST_PATH, scale=1.5)


def test_art_prompts_freeze_canonical_identity_and_reject_complete_character_frames() -> None:
    builder = _load_module(ART_JOB_PATH, "build_maotai_v2_art_jobs_prompt")
    plan    = builder.build_art_plan(MANIFEST_PATH, scale=4.0)

    references = plan["reference_files"]
    assert references[0] == "01_maotai_rig_design_sheet.png"
    assert "03_working_happy.png" in references
    assert all("/" not in name and "\\" not in name for name in references)

    for job in plan["jobs"]:
        positive = job["positive_prompt"].lower()
        negative = job["negative_prompt"].lower()

        assert "maotai" in positive
        assert "alaskan malamute" in positive
        assert "isolated" in positive
        assert "independent" in positive
        assert "transparent" in positive
        assert "canonical" in positive
        assert "three-quarter" in positive
        assert "hidden fur overlap" in positive
        assert job["target_file"].removesuffix(".png").replace("_", " ") in positive

        assert "complete dog" in negative
        assert "assembled dog" in negative
        assert "full-body character" in negative
        assert "extra limb" in negative
        assert "sprite sheet" in negative
        assert "opaque background" in negative
        assert "text" in negative
        assert "ui" in negative


def test_seed_families_keep_mirrored_and_variant_parts_visually_related() -> None:
    builder = _load_module(ART_JOB_PATH, "build_maotai_v2_art_jobs_seed")
    jobs    = {
        job["target_file"]: job
        for job in builder.build_art_plan(MANIFEST_PATH, scale=4.0)["jobs"]
    }

    assert jobs["ear_left.png"]["seed_family"] == jobs["ear_right.png"]["seed_family"]
    assert jobs["eye_left_open.png"]["seed_family"] == jobs["eye_right_open.png"]["seed_family"]
    assert jobs["front_left_upper.png"]["seed_family"] == jobs["front_right_upper.png"]["seed_family"]
    assert jobs["hind_left_paw.png"]["seed_family"] == jobs["hind_right_paw.png"]["seed_family"]
    assert jobs["torso_neutral.png"]["seed_family"] == jobs["torso_crouch.png"]["seed_family"]
    assert jobs["torso_neutral.png"]["seed_family"] == jobs["torso_stretch.png"]["seed_family"]


def test_art_plan_points_back_to_existing_fail_closed_validator_and_stage_command() -> None:
    builder = _load_module(ART_JOB_PATH, "build_maotai_v2_art_jobs_stage")
    plan    = builder.build_art_plan(MANIFEST_PATH, scale=4.0)

    staging = plan["staging"]
    assert staging["validator"].endswith("validate_maotai_v2_assets.py")
    assert "stage" in staging["command"]
    assert staging["all_assets_required_before_stage"] is True


def test_comfyui_binding_applies_one_job_without_mutating_template() -> None:
    runner = _load_module(RUNNER_PATH, "run_maotai_v2_comfyui_jobs")
    job    = {
        "target_file": "ear_left.png",
        "positive_prompt": "positive fixture",
        "negative_prompt": "negative fixture",
        "output": {"width_px": 136, "height_px": 176},
    }
    workflow = {
        "3": {"class_type": "KSampler", "inputs": {"seed": 1}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 64, "height": 64}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "old positive"}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "old negative"}},
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "old"}},
        "10": {
            "class_type": "BiRefNetRMBG",
            "inputs": {"background": "Color", "model": "BiRefNet-general"},
        },
    }
    bindings = {
        "positive": {"node": "6", "input": "text"},
        "negative": {"node": "7", "input": "text"},
        "width": {"node": "5", "input": "width"},
        "height": {"node": "5", "input": "height"},
        "seed": {"node": "3", "input": "seed"},
        "filename_prefix": {"node": "9", "input": "filename_prefix"},
        "rmbg": {
            "node": "10",
            "background_input": "background",
            "model_input": "model",
            "model": "Lucida",
        },
    }
    original = copy.deepcopy(workflow)

    rendered = runner.apply_job_to_workflow(
        workflow,
        bindings,
        job,
        seed=4321,
        filename_prefix="maotai-v2/ear_left",
    )

    assert workflow == original
    assert rendered["6"]["inputs"]["text"] == "positive fixture"
    assert rendered["7"]["inputs"]["text"] == "negative fixture"
    assert rendered["5"]["inputs"]["width"] == 136
    assert rendered["5"]["inputs"]["height"] == 176
    assert rendered["3"]["inputs"]["seed"] == 4321
    assert rendered["9"]["inputs"]["filename_prefix"] == "maotai-v2/ear_left"
    assert rendered["10"]["inputs"]["background"] == "Alpha"
    assert rendered["10"]["inputs"]["model"] == "Lucida"


def test_comfyui_runner_is_local_only_and_rejects_missing_bindings() -> None:
    runner = _load_module(RUNNER_PATH, "run_maotai_v2_comfyui_jobs_security")

    assert runner.normalize_server_url("http://127.0.0.1:8188") == "http://127.0.0.1:8188"
    assert runner.normalize_server_url("http://localhost:8188/") == "http://localhost:8188"
    assert runner.normalize_server_url("http://[::1]:8188") == "http://[::1]:8188"

    with pytest.raises(ValueError, match="loopback|local"):
        runner.normalize_server_url("http://192.168.1.50:8188")
    with pytest.raises(ValueError, match="http"):
        runner.normalize_server_url("https://127.0.0.1:8188")

    workflow = {"1": {"class_type": "CLIPTextEncode", "inputs": {"text": "x"}}}
    with pytest.raises(ValueError, match="binding"):
        runner.apply_job_to_workflow(
            workflow,
            {"positive": {"node": "1", "input": "text"}},
            {
                "target_file": "head.png",
                "positive_prompt": "p",
                "negative_prompt": "n",
                "output": {"width_px": 312, "height_px": 280},
            },
            seed=1,
            filename_prefix="head",
        )


def test_comfyui_result_selection_requires_a_single_png_output() -> None:
    runner = _load_module(RUNNER_PATH, "run_maotai_v2_comfyui_jobs_output")

    history = {
        "outputs": {
            "9": {
                "images": [
                    {
                        "filename": "ear_left_00001_.png",
                        "subfolder": "maotai-v2",
                        "type": "output",
                    }
                ]
            }
        }
    }
    selected = runner.select_single_png_output(history)
    assert selected["filename"] == "ear_left_00001_.png"

    with pytest.raises(ValueError, match="exactly one"):
        runner.select_single_png_output({"outputs": {}})
    with pytest.raises(ValueError, match="exactly one"):
        runner.select_single_png_output(
            {
                "outputs": {
                    "9": {
                        "images": [
                            {"filename": "a.png", "subfolder": "", "type": "output"},
                            {"filename": "b.png", "subfolder": "", "type": "output"},
                        ]
                    }
                }
            }
        )


def test_comfyui_binding_json_round_trips_without_hidden_defaults(tmp_path: Path) -> None:
    runner  = _load_module(RUNNER_PATH, "run_maotai_v2_comfyui_jobs_bindings")
    payload = {
        "positive": {"node": "6", "input": "text"},
        "negative": {"node": "7", "input": "text"},
        "width": {"node": "5", "input": "width"},
        "height": {"node": "5", "input": "height"},
        "seed": {"node": "3", "input": "seed"},
        "filename_prefix": {"node": "9", "input": "filename_prefix"},
    }
    path = tmp_path / "bindings.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert runner.load_bindings(path) == payload
