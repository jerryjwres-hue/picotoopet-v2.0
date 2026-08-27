from __future__ import annotations

import importlib.util
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
RUNNER_PATH     = TOOL_ROOT / "run_maotai_v2_comfyui_jobs.py"


if str(TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOL_ROOT))


def _load_runner(module_name: str):
    """按仓库路径加载 runner，验证 API workflow 标题约定而不依赖安装副作用。"""
    spec = importlib.util.spec_from_file_location(module_name, RUNNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _workflow() -> dict[str, object]:
    return {
        "3": {
            "class_type": "KSampler",
            "_meta": {"title": "MAOTAI_SAMPLER"},
            "inputs": {"seed": 1, "steps": 20},
        },
        "5": {
            "class_type": "EmptyLatentImage",
            "_meta": {"title": "MAOTAI_CANVAS"},
            "inputs": {"width": 512, "height": 512, "batch_size": 1},
        },
        "6": {
            "class_type": "CLIPTextEncode",
            "_meta": {"title": "MAOTAI_POSITIVE"},
            "inputs": {"text": "positive"},
        },
        "7": {
            "class_type": "CLIPTextEncode",
            "_meta": {"title": "MAOTAI_NEGATIVE"},
            "inputs": {"text": "negative"},
        },
        "8": {
            "class_type": "LoadImage",
            "_meta": {"title": "MAOTAI_REFERENCE"},
            "inputs": {"image": "03_working_happy.png"},
        },
        "9": {
            "class_type": "SaveImage",
            "_meta": {"title": "MAOTAI_SAVE"},
            "inputs": {"filename_prefix": "old"},
        },
        "10": {
            "class_type": "BiRefNetRMBG",
            "_meta": {"title": "MAOTAI_RMBG"},
            "inputs": {"background": "Color", "model": "BiRefNet-general"},
        },
    }


def test_autobind_maps_named_nodes_without_manual_node_ids() -> None:
    runner   = _load_runner("run_maotai_v2_comfyui_autobind")
    bindings = runner.build_bindings_from_workflow(_workflow())

    assert bindings == {
        "positive": {"node": "6", "input": "text"},
        "negative": {"node": "7", "input": "text"},
        "width": {"node": "5", "input": "width"},
        "height": {"node": "5", "input": "height"},
        "seed": {"node": "3", "input": "seed"},
        "filename_prefix": {"node": "9", "input": "filename_prefix"},
        "reference_image": {"node": "8", "input": "image"},
        "rmbg": {
            "node": "10",
            "background_input": "background",
            "model_input": "model",
            "model": "Lucida",
        },
    }


def test_autobind_allows_reference_and_rmbg_to_be_optional() -> None:
    runner   = _load_runner("run_maotai_v2_comfyui_autobind_optional")
    workflow = _workflow()
    del workflow["8"]
    del workflow["10"]

    bindings = runner.build_bindings_from_workflow(workflow)

    assert "reference_image" not in bindings
    assert "rmbg" not in bindings
    assert bindings["positive"] == {"node": "6", "input": "text"}


def test_autobind_rejects_duplicate_titles_and_missing_required_titles() -> None:
    runner   = _load_runner("run_maotai_v2_comfyui_autobind_invalid")
    workflow = _workflow()
    workflow["11"] = {
        "class_type": "CLIPTextEncode",
        "_meta": {"title": "MAOTAI_POSITIVE"},
        "inputs": {"text": "duplicate"},
    }

    with pytest.raises(ValueError, match="duplicate|MAOTAI_POSITIVE"):
        runner.build_bindings_from_workflow(workflow)

    workflow = _workflow()
    del workflow["7"]
    with pytest.raises(ValueError, match="MAOTAI_NEGATIVE"):
        runner.build_bindings_from_workflow(workflow)


def test_autobind_rejects_named_nodes_that_do_not_expose_required_inputs() -> None:
    runner   = _load_runner("run_maotai_v2_comfyui_autobind_inputs")
    workflow = _workflow()
    workflow["5"]["inputs"] = {"width": 512}

    with pytest.raises(ValueError, match="height|MAOTAI_CANVAS"):
        runner.build_bindings_from_workflow(workflow)


def test_autobind_rmbg_title_must_target_birefnet_node() -> None:
    runner   = _load_runner("run_maotai_v2_comfyui_autobind_rmbg")
    workflow = _workflow()
    workflow["10"]["class_type"] = "SaveImage"

    with pytest.raises(ValueError, match="BiRefNetRMBG|MAOTAI_RMBG"):
        runner.build_bindings_from_workflow(workflow)
