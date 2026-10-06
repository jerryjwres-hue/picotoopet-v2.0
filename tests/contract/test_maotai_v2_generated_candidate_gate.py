from __future__ import annotations

import importlib.util
import json
import struct
import sys
import zlib
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TOOL_ROOT       = REPOSITORY_ROOT / "windows" / "desktop" / "tools" / "maotai_v2_assets"
GATE_PATH       = TOOL_ROOT / "validate_maotai_v2_generated_candidates.py"


if str(TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOL_ROOT))


def _load_gate():
    """直接加载仓库生产 gate，避免依赖安装态模块搜索路径。"""
    spec = importlib.util.spec_from_file_location("maotai_v2_generated_candidate_gate", GATE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_manifest(path: Path) -> None:
    """最小 manifest fixture：一个结构腿件和一个普通 overlay。"""
    path.write_text(
        '''
internal static class MaotaiAssetManifest
{
    public const string FrontLeftUpper = "front_left_upper.png";
    public const string EyeLeftOpen    = "eye_left_open.png";

    public static bool TryGetDescriptor(string fileName, out object descriptor)
    {
        descriptor = fileName switch
        {
            FrontLeftUpper => D(FrontLeftUpper, 40, 56, 20, 12, 42, 20),
            EyeLeftOpen    => D(EyeLeftOpen, 32, 24, 16, 12, 80, 12),
            _              => default,
        };
        return descriptor is not null;
    }
}
'''.strip(),
        encoding="utf-8",
    )


def _write_plan(path: Path, manifest: Path) -> None:
    """候选 gate 从 art-plan 读取每个 job 的结构质量合同，不维护第二套角色分类。"""
    path.write_text(
        json.dumps(
            {
                "source_of_truth": str(manifest),
                "jobs": [
                    {
                        "target_file": "front_left_upper.png",
                        "structural_quality": {
                            "gate": "organic_silhouette",
                            "reject_rectangular_plate": True,
                            "require_soft_alpha_edge": True,
                            "forbid_visible_connector_geometry": True,
                            "assembly_preview_required": True,
                        },
                    },
                    {
                        "target_file": "eye_left_open.png",
                        "structural_quality": {
                            "gate": "standard_overlay",
                            "reject_rectangular_plate": False,
                            "require_soft_alpha_edge": False,
                            "forbid_visible_connector_geometry": False,
                            "assembly_preview_required": True,
                        },
                    },
                ],
            }
        ),
        encoding="utf-8",
    )


def _write_rgba_png(path: Path, width: int, height: int, alpha_at) -> None:
    """标准库 RGBA fixture；RGB 保留轻微纹理，alpha 由测试定义。"""
    rows: list[bytes] = []
    for y in range(height):
        row = bytearray(width * 4)
        for x in range(width):
            offset          = x * 4
            row[offset]     = 72 + ((x + y) % 45)
            row[offset + 1] = 70 + ((x * 2 + y) % 37)
            row[offset + 2] = 80 + ((x + y * 3) % 31)
            row[offset + 3] = int(alpha_at(x, y))
        rows.append(b"\x00" + bytes(row))

    def chunk(kind: bytes, payload: bytes) -> bytes:
        body = kind + payload
        return (
            struct.pack(">I", len(payload))
            + body
            + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(b"".join(rows)))
        + chunk(b"IEND", b"")
    )


def _tapered_alpha(width: int, height: int):
    def alpha_at(x: int, y: int) -> int:
        if y < 7 or y >= height - 7:
            return 0
        t          = (y - 7) / (height - 15)
        half_width = 22.0 - (6.0 * t) + (2.0 * abs(0.5 - t))
        center_x   = (width - 1) / 2.0
        distance   = abs(x - center_x)
        if distance <= half_width - 2.0:
            return 255
        if distance <= half_width:
            return 128
        return 0

    return alpha_at


def _plate_alpha(width: int, height: int):
    def alpha_at(x: int, y: int) -> int:
        if 8 <= x < width - 8 and 8 <= y < height - 8:
            edge = x in {8, width - 9} or y in {8, height - 9}
            return 160 if edge else 255
        return 0

    return alpha_at


def test_partial_candidate_gate_accepts_one_good_structural_family_without_requiring_all_44(
    tmp_path: Path,
) -> None:
    gate      = _load_gate()
    manifest  = tmp_path / "MaotaiAssetManifest.cs"
    plan      = tmp_path / "art-plan.json"
    candidates = tmp_path / "candidates"
    candidates.mkdir()
    _write_manifest(manifest)
    _write_plan(plan, manifest)
    _write_rgba_png(
        candidates / "front_left_upper.png",
        80,
        112,
        _tapered_alpha(80, 112),
    )

    report = gate.validate_generated_candidates(candidates, plan)

    assert report.ok
    assert report.checked_files == ("front_left_upper.png",)
    assert report.errors == ()


def test_partial_candidate_gate_rejects_rectangular_structural_plate(tmp_path: Path) -> None:
    gate       = _load_gate()
    manifest   = tmp_path / "MaotaiAssetManifest.cs"
    plan       = tmp_path / "art-plan.json"
    candidates = tmp_path / "candidates"
    candidates.mkdir()
    _write_manifest(manifest)
    _write_plan(plan, manifest)
    _write_rgba_png(
        candidates / "front_left_upper.png",
        80,
        112,
        _plate_alpha(80, 112),
    )

    report = gate.validate_generated_candidates(candidates, plan)
    text   = "\n".join(report.errors).lower()

    assert not report.ok
    assert "front_left_upper.png" in text
    assert "rectangular" in text or "plate" in text or "silhouette" in text


def test_partial_candidate_gate_rejects_unplanned_png_instead_of_silently_promoting_it(
    tmp_path: Path,
) -> None:
    gate       = _load_gate()
    manifest   = tmp_path / "MaotaiAssetManifest.cs"
    plan       = tmp_path / "art-plan.json"
    candidates = tmp_path / "candidates"
    candidates.mkdir()
    _write_manifest(manifest)
    _write_plan(plan, manifest)
    _write_rgba_png(
        candidates / "unexpected_full_dog.png",
        80,
        112,
        _tapered_alpha(80, 112),
    )

    report = gate.validate_generated_candidates(candidates, plan)
    text   = "\n".join(report.errors).lower()

    assert not report.ok
    assert "unexpected_full_dog.png" in text
    assert "unplanned" in text or "unexpected" in text
