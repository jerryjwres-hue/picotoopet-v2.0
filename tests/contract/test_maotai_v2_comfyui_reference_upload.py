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
PNG_SIGNATURE   = b"\x89PNG\r\n\x1a\n"


if str(TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOL_ROOT))


def _load_runner(module_name: str):
    """按仓库文件加载 runner，避免 contract test 依赖可编辑安装副作用。"""
    spec = importlib.util.spec_from_file_location(module_name, RUNNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _write_png(path: Path, marker: bytes = b"fixture") -> None:
    """上传 contract 只验证传输边界，因此最小 fixture 仅需要正确 PNG 签名。"""
    path.write_bytes(PNG_SIGNATURE + marker)


def test_multipart_upload_uses_official_comfyui_image_fields(tmp_path: Path) -> None:
    runner = _load_runner("run_maotai_v2_reference_multipart")
    image  = tmp_path / "03_working_happy.png"
    _write_png(image, b"maotai-reference")

    body, content_type = runner.build_multipart_image_upload(
        image,
        subfolder="maotai-v2-references",
        boundary="MAOTAI-BOUNDARY",
    )

    assert content_type == "multipart/form-data; boundary=MAOTAI-BOUNDARY"
    assert b'name="image"; filename="03_working_happy.png"' in body
    assert b"Content-Type: image/png" in body
    assert PNG_SIGNATURE + b"maotai-reference" in body
    assert b'name="overwrite"\r\n\r\ntrue' in body
    assert b'name="type"\r\n\r\ninput' in body
    assert b'name="subfolder"\r\n\r\nmaotai-v2-references' in body
    assert body.endswith(b"--MAOTAI-BOUNDARY--\r\n")


def test_multipart_upload_rejects_non_png_and_unsafe_subfolder(tmp_path: Path) -> None:
    runner = _load_runner("run_maotai_v2_reference_multipart_invalid")
    image  = tmp_path / "reference.png"
    image.write_bytes(b"not-a-png")

    with pytest.raises(ValueError, match="PNG"):
        runner.build_multipart_image_upload(image, subfolder="maotai-v2-references")

    _write_png(image)
    with pytest.raises(ValueError, match="subfolder"):
        runner.build_multipart_image_upload(image, subfolder="../outside")


def test_uploaded_input_response_must_match_expected_name_folder_and_type() -> None:
    runner = _load_runner("run_maotai_v2_reference_response")

    value = runner.normalize_uploaded_input_name(
        {
            "name": "03_working_happy.png",
            "subfolder": "maotai-v2-references",
            "type": "input",
        },
        expected_name="03_working_happy.png",
        expected_subfolder="maotai-v2-references",
    )
    assert value == "maotai-v2-references/03_working_happy.png"

    with pytest.raises(ValueError, match="name"):
        runner.normalize_uploaded_input_name(
            {
                "name": "other.png",
                "subfolder": "maotai-v2-references",
                "type": "input",
            },
            expected_name="03_working_happy.png",
            expected_subfolder="maotai-v2-references",
        )
    with pytest.raises(ValueError, match="subfolder"):
        runner.normalize_uploaded_input_name(
            {
                "name": "03_working_happy.png",
                "subfolder": "other",
                "type": "input",
            },
            expected_name="03_working_happy.png",
            expected_subfolder="maotai-v2-references",
        )
    with pytest.raises(ValueError, match="type"):
        runner.normalize_uploaded_input_name(
            {
                "name": "03_working_happy.png",
                "subfolder": "maotai-v2-references",
                "type": "output",
            },
            expected_name="03_working_happy.png",
            expected_subfolder="maotai-v2-references",
        )


def test_reference_preflight_fails_before_uploading_when_any_required_file_is_missing(
    tmp_path: Path,
) -> None:
    runner = _load_runner("run_maotai_v2_reference_preflight")
    _write_png(tmp_path / "03_working_happy.png")
    plan = {
        "jobs": [
            {"primary_reference": "03_working_happy.png"},
            {"primary_reference": "06_idle_paw.png"},
        ]
    }

    class FakeClient:
        def __init__(self) -> None:
            self.uploaded: list[str] = []

        def upload_input_image(self, path: Path, *, subfolder: str) -> str:
            self.uploaded.append(path.name)
            return f"{subfolder}/{path.name}"

    client = FakeClient()
    with pytest.raises(ValueError, match="06_idle_paw.png"):
        runner.prepare_reference_uploads(plan, tmp_path, client)

    assert client.uploaded == []


def test_reference_uploads_are_unique_and_return_loadimage_values(tmp_path: Path) -> None:
    runner = _load_runner("run_maotai_v2_reference_prepare")
    for name in ("03_working_happy.png", "06_idle_paw.png"):
        _write_png(tmp_path / name, name.encode("utf-8"))

    plan = {
        "jobs": [
            {"primary_reference": "03_working_happy.png"},
            {"primary_reference": "06_idle_paw.png"},
            {"primary_reference": "03_working_happy.png"},
        ]
    }

    class FakeClient:
        def __init__(self) -> None:
            self.uploaded: list[tuple[str, str]] = []

        def upload_input_image(self, path: Path, *, subfolder: str) -> str:
            self.uploaded.append((path.name, subfolder))
            return f"{subfolder}/{path.name}"

    client  = FakeClient()
    mapping = runner.prepare_reference_uploads(
        plan,
        tmp_path,
        client,
        subfolder="maotai-v2-references",
    )

    assert client.uploaded == [
        ("03_working_happy.png", "maotai-v2-references"),
        ("06_idle_paw.png", "maotai-v2-references"),
    ]
    assert mapping == {
        "03_working_happy.png": "maotai-v2-references/03_working_happy.png",
        "06_idle_paw.png": "maotai-v2-references/06_idle_paw.png",
    }


def test_uploaded_reference_mapping_is_used_for_loadimage_binding() -> None:
    runner = _load_runner("run_maotai_v2_reference_binding")
    workflow = {
        "3": {"class_type": "KSampler", "inputs": {"seed": 1}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 64, "height": 64}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "old positive"}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "old negative"}},
        "8": {"class_type": "LoadImage", "inputs": {"image": "old.png"}},
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "old"}},
    }
    bindings = {
        "positive": {"node": "6", "input": "text"},
        "negative": {"node": "7", "input": "text"},
        "width": {"node": "5", "input": "width"},
        "height": {"node": "5", "input": "height"},
        "seed": {"node": "3", "input": "seed"},
        "filename_prefix": {"node": "9", "input": "filename_prefix"},
        "reference_image": {"node": "8", "input": "image"},
    }
    job = {
        "target_file": "ear_left.png",
        "primary_reference": "03_working_happy.png",
        "positive_prompt": "positive fixture",
        "negative_prompt": "negative fixture",
        "output": {"width_px": 136, "height_px": 176},
    }

    rendered = runner.apply_job_to_workflow(
        workflow,
        bindings,
        job,
        seed=4321,
        filename_prefix="maotai-v2/ear_left",
        reference_inputs={
            "03_working_happy.png": "maotai-v2-references/03_working_happy.png",
        },
    )

    assert rendered["8"]["inputs"]["image"] == (
        "maotai-v2-references/03_working_happy.png"
    )
