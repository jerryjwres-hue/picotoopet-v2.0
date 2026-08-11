"""2.3.20.1 source-controlled ComfyUI workflow-template contracts."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_ROOT = ROOT / "windows" / "production" / "workflows"
MODEL_MANIFEST = ROOT / "windows" / "bootstrap" / "model_manifest.json"

T2V = WORKFLOW_ROOT / "wan22-ti2v5b-t2v-api-v1.json"
I2V = WORKFLOW_ROOT / "wan22-ti2v5b-i2v-api-v1.json"

ALLOWED_T2V_CLASSES = {
    "UNETLoader",
    "CLIPLoader",
    "VAELoader",
    "ModelSamplingSD3",
    "CLIPTextEncode",
    "Wan22ImageToVideoLatent",
    "KSampler",
    "VAEDecode",
    "SaveWEBM",
}
ALLOWED_I2V_CLASSES = ALLOWED_T2V_CLASSES | {"LoadImage"}

PINNED_LOADERS = {
    "UNETLoader": ("unet_name", "wan2.2_ti2v_5B_fp16.safetensors"),
    "CLIPLoader": ("clip_name", "umt5_xxl_fp8_e4m3fn_scaled.safetensors"),
    "VAELoader": ("vae_name", "wan2.2_vae.safetensors"),
}


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _node_classes(workflow: dict[str, object]) -> set[str]:
    return {
        str(node["class_type"])
        for node in workflow.values()
        if isinstance(node, dict) and "class_type" in node
    }


def _assert_api_format(workflow: dict[str, object], allowed_classes: set[str]) -> None:
    assert workflow
    for node_id, node in workflow.items():
        assert node_id.isdigit(), node_id
        assert isinstance(node, dict), node_id
        assert set(node) == {"class_type", "inputs"}, node_id
        assert node["class_type"] in allowed_classes, node_id
        assert isinstance(node["inputs"], dict), node_id


def _assert_pinned_loaders(workflow: dict[str, object]) -> None:
    by_class = {
        str(node["class_type"]): node
        for node in workflow.values()
        if isinstance(node, dict)
    }
    for class_type, (field_name, expected_name) in PINNED_LOADERS.items():
        node = by_class[class_type]
        assert node["inputs"][field_name] == expected_name


def _assert_no_renderer_authority(workflow: dict[str, object]) -> None:
    source = json.dumps(workflow, ensure_ascii=False).lower()
    for forbidden in (
        "http://",
        "https://",
        "api_key",
        "apikey",
        "subprocess",
        "powershell",
        "cmd.exe",
        "custom_nodes",
        "partner",
        "cloud",
    ):
        assert forbidden not in source


def test_t2v_template_is_closed_api_graph_with_pinned_models() -> None:
    workflow = _load(T2V)
    _assert_api_format(workflow, ALLOWED_T2V_CLASSES)
    assert _node_classes(workflow) == ALLOWED_T2V_CLASSES
    _assert_pinned_loaders(workflow)
    _assert_no_renderer_authority(workflow)
    assert "LoadImage" not in _node_classes(workflow)


def test_i2v_template_adds_only_trusted_load_image_node() -> None:
    workflow = _load(I2V)
    _assert_api_format(workflow, ALLOWED_I2V_CLASSES)
    assert _node_classes(workflow) == ALLOWED_I2V_CLASSES
    _assert_pinned_loaders(workflow)
    _assert_no_renderer_authority(workflow)
    load_image = next(
        node for node in workflow.values()
        if isinstance(node, dict) and node["class_type"] == "LoadImage"
    )
    assert load_image["inputs"]["image"] == "__PICOTOO_TRUSTED_INPUT_IMAGE__"


def test_workflow_models_match_pinned_bootstrap_manifest() -> None:
    manifest = _load(MODEL_MANIFEST)
    filenames = {
        str(item["filename"])
        for item in manifest["models"]
        if isinstance(item, dict)
    }
    for _, expected_name in PINNED_LOADERS.values():
        assert expected_name in filenames


def test_runtime_mutation_slots_are_explicit_placeholders_only() -> None:
    for path in (T2V, I2V):
        workflow = _load(path)
        source = json.dumps(workflow, ensure_ascii=False)
        for required in (
            "__PICOTOO_POSITIVE_PROMPT__",
            "__PICOTOO_SEED__",
            "__PICOTOO_WIDTH__",
            "__PICOTOO_HEIGHT__",
            "__PICOTOO_LENGTH__",
            "__PICOTOO_FPS__",
            "__PICOTOO_FILENAME_PREFIX__",
        ):
            assert required in source, (path.name, required)
