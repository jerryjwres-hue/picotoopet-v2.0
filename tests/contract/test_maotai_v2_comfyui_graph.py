from __future__ import annotations

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
RUNNER_PATH     = TOOL_ROOT / "run_maotai_v2_comfyui_jobs.py"


if str(TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOL_ROOT))


def _load_runner(module_name: str):
    """按仓库文件加载 runner，验证 API workflow 图结构而不依赖全局安装。"""
    spec = importlib.util.spec_from_file_location(module_name, RUNNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _workflow() -> dict[str, object]:
    """构造一条真实 API JSON 形态的参考图→采样→解码→RMBG→Save 依赖链。"""
    return {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "fixture.safetensors"},
        },
        "3": {
            "class_type": "KSampler",
            "_meta": {"title": "MAOTAI_SAMPLER"},
            "inputs": {
                "seed": 1,
                "model": ["11", 0],
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["5", 0],
            },
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
            "inputs": {"images": ["10", 0], "filename_prefix": "old"},
        },
        "10": {
            "class_type": "BiRefNetRMBG",
            "_meta": {"title": "MAOTAI_RMBG"},
            "inputs": {
                "image": ["12", 0],
                "background": "Color",
                "model": "BiRefNet-general",
            },
        },
        "11": {
            "class_type": "ReferenceConditionerFixture",
            "inputs": {"model": ["1", 0], "image": ["8", 0]},
        },
        "12": {
            "class_type": "VAEDecodeFixture",
            "inputs": {"samples": ["3", 0]},
        },
    }


def _bindings(runner, workflow: dict[str, object]) -> dict[str, object]:
    return runner.build_bindings_from_workflow(workflow)


def _object_info(workflow: dict[str, object]) -> dict[str, object]:
    """模拟 `/object_info` 已注册 node class 集合；值内容与本合同无关。"""
    return {
        node["class_type"]: {}
        for node in workflow.values()
        if isinstance(node, dict) and isinstance(node.get("class_type"), str)
    }


def test_upstream_traversal_recognizes_comfyui_api_link_shape() -> None:
    runner   = _load_runner("run_maotai_v2_graph_upstream")
    workflow = _workflow()

    upstream = runner.workflow_upstream_node_ids(workflow, "9")

    assert upstream == {"1", "3", "5", "6", "7", "8", "10", "11", "12"}
    assert "9" not in upstream


def test_graph_gate_accepts_fully_connected_reference_and_alpha_pipeline() -> None:
    runner   = _load_runner("run_maotai_v2_graph_valid")
    workflow = _workflow()
    bindings = _bindings(runner, workflow)

    runner.validate_maotai_workflow_graph(workflow, bindings)


def test_graph_gate_rejects_named_reference_that_does_not_reach_save() -> None:
    runner   = _load_runner("run_maotai_v2_graph_reference")
    workflow = _workflow()
    workflow["11"]["inputs"]["image"] = "constant-reference-bypass"
    bindings = _bindings(runner, workflow)

    with pytest.raises(ValueError, match="MAOTAI_REFERENCE|reference|upstream"):
        runner.validate_maotai_workflow_graph(workflow, bindings)


def test_graph_gate_rejects_named_rmbg_that_save_bypasses() -> None:
    runner   = _load_runner("run_maotai_v2_graph_rmbg")
    workflow = _workflow()
    workflow["9"]["inputs"]["images"] = ["12", 0]
    bindings = _bindings(runner, workflow)

    with pytest.raises(ValueError, match="MAOTAI_RMBG|RMBG|upstream"):
        runner.validate_maotai_workflow_graph(workflow, bindings)


def test_graph_gate_rejects_disconnected_required_generation_inputs() -> None:
    runner   = _load_runner("run_maotai_v2_graph_required")
    workflow = _workflow()
    workflow["3"]["inputs"]["positive"] = "constant-positive-bypass"
    bindings = _bindings(runner, workflow)

    with pytest.raises(ValueError, match="MAOTAI_POSITIVE|positive|upstream"):
        runner.validate_maotai_workflow_graph(workflow, bindings)


def test_upstream_traversal_handles_cycles_but_rejects_dangling_links() -> None:
    runner   = _load_runner("run_maotai_v2_graph_cycle")
    workflow = _workflow()
    workflow["11"]["inputs"]["feedback"] = ["13", 0]
    workflow["13"] = {
        "class_type": "CycleFixture",
        "inputs": {
            "model": ["11", 0],
            "metadata": [1, 2, 3],
        },
    }

    upstream = runner.workflow_upstream_node_ids(workflow, "9")
    assert "13" in upstream
    runner.validate_maotai_workflow_graph(workflow, _bindings(runner, workflow))

    workflow["13"]["inputs"]["dangling"] = ["missing-node", 0]
    with pytest.raises(ValueError, match="missing-node|dangling"):
        runner.workflow_upstream_node_ids(workflow, "9")


def test_run_art_plan_validates_graph_before_any_comfyui_network_side_effect(
    tmp_path: Path,
) -> None:
    runner   = _load_runner("run_maotai_v2_graph_preflight")
    workflow = _workflow()
    workflow["9"]["inputs"]["images"] = ["12", 0]

    plan_path     = tmp_path / "plan.json"
    workflow_path = tmp_path / "workflow.json"
    incoming      = tmp_path / "incoming"
    plan_path.write_text(
        json.dumps(
            {
                "source_of_truth": "windows/desktop/src/PicotooPet.Desktop/Views/Controls/MaotaiMotion/MaotaiAssetManifest.cs",
                "jobs": [
                    {
                        "target_file": "torso_neutral.png",
                        "seed_family": "torso",
                        "primary_reference": "03_working_happy.png",
                        "positive_prompt": "fixture",
                        "negative_prompt": "fixture",
                        "output": {"width_px": 328, "height_px": 280},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    workflow_path.write_text(json.dumps(workflow), encoding="utf-8")

    class NetworkMustNotStart:
        def __init__(self, *args, **kwargs) -> None:
            raise AssertionError("ComfyUI network client must not start before graph validation")

    runner.ComfyUiLocalClient = NetworkMustNotStart

    with pytest.raises(ValueError, match="MAOTAI_RMBG|RMBG|upstream"):
        runner.run_art_plan(
            plan_path,
            workflow_path,
            None,
            incoming,
        )


def test_node_type_preflight_accepts_only_workflow_classes_registered_by_comfyui() -> None:
    runner      = _load_runner("run_maotai_v2_node_types")
    workflow    = _workflow()
    object_info = _object_info(workflow)

    runner.validate_comfyui_workflow_node_types(object_info, workflow)

    del object_info["ReferenceConditionerFixture"]
    with pytest.raises(ValueError, match="ReferenceConditionerFixture|registered|node class"):
        runner.validate_comfyui_workflow_node_types(object_info, workflow)


def test_run_art_plan_checks_node_types_before_reference_upload_or_prompt_queue(
    tmp_path: Path,
) -> None:
    runner      = _load_runner("run_maotai_v2_node_type_order")
    workflow    = _workflow()
    object_info = _object_info(workflow)
    del object_info["ReferenceConditionerFixture"]

    plan_path     = tmp_path / "plan.json"
    workflow_path = tmp_path / "workflow.json"
    incoming      = tmp_path / "incoming"
    plan_path.write_text(
        json.dumps(
            {
                "source_of_truth": "windows/desktop/src/PicotooPet.Desktop/Views/Controls/MaotaiMotion/MaotaiAssetManifest.cs",
                "jobs": [
                    {
                        "target_file": "torso_neutral.png",
                        "seed_family": "torso",
                        "primary_reference": "03_working_happy.png",
                        "positive_prompt": "fixture",
                        "negative_prompt": "fixture",
                        "output": {"width_px": 368, "height_px": 312},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    workflow_path.write_text(json.dumps(workflow), encoding="utf-8")

    class NodeTypePreflightClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def object_info(self) -> dict[str, object]:
            return object_info

        def upload_input_image(self, *args, **kwargs) -> str:
            raise AssertionError("reference upload must not start before node type preflight")

        def queue_prompt(self, *args, **kwargs) -> str:
            raise AssertionError("prompt queue must not start before node type preflight")

    runner.ComfyUiLocalClient = NodeTypePreflightClient

    with pytest.raises(ValueError, match="ReferenceConditionerFixture|registered|node class"):
        runner.run_art_plan(
            plan_path,
            workflow_path,
            None,
            incoming,
            reference_root=tmp_path / "missing-references",
        )
