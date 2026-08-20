from __future__ import annotations

import importlib.util
import struct
import sys
import zlib
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TOOL_ROOT       = REPOSITORY_ROOT / "windows" / "desktop" / "tools" / "maotai_v2_assets"
PNG_TOOL_PATH   = TOOL_ROOT / "maotai_png_validation.py"


if str(TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOL_ROOT))


def _load_png_tool():
    """按仓库路径加载 PNG gate，验证生成后的结构件而不依赖安装态模块。"""
    spec = importlib.util.spec_from_file_location("maotai_v2_structural_png_gate", PNG_TOOL_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _descriptor(tool, file_name: str, width: int, height: int):
    return tool.AssetDescriptor(
        file_name=file_name,
        logical_width=width / 2.0,
        logical_height=height / 2.0,
        pivot_x=width / 4.0,
        pivot_y=height / 8.0,
        z_index=20,
        joint_overlap_pixels=12.0,
    )


def _quality_contract() -> dict[str, object]:
    return {
        "gate": "organic_silhouette",
        "reject_rectangular_plate": True,
        "require_soft_alpha_edge": True,
        "forbid_visible_connector_geometry": True,
        "assembly_preview_required": True,
    }


def _write_rgba_png(path: Path, width: int, height: int, alpha_at) -> None:
    """仅用标准库写 RGBA fixture；RGB 有轻微纹理，alpha 由测试控制。"""
    rows: list[bytes] = []
    for y in range(height):
        row = bytearray(width * 4)
        for x in range(width):
            offset          = x * 4
            row[offset]     = 70 + ((x + y) % 40)
            row[offset + 1] = 68 + ((x * 3 + y) % 35)
            row[offset + 2] = 75 + ((x + y * 2) % 30)
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


def test_structural_gate_rejects_a_texture_plate_even_when_alpha_and_padding_are_valid(
    tmp_path: Path,
) -> None:
    tool   = _load_png_tool()
    path   = tmp_path / "front_left_upper.png"
    width  = 80
    height = 112

    def rectangle_alpha(x: int, y: int) -> int:
        if 8 <= x < width - 8 and 8 <= y < height - 8:
            return 180 if x in {8, width - 9} or y in {8, height - 9} else 255
        return 0

    _write_rgba_png(path, width, height, rectangle_alpha)
    descriptor = _descriptor(tool, path.name, width, height)

    errors = tool.validate_structural_art_quality(path, descriptor, _quality_contract())
    text   = "\n".join(errors).lower()

    assert errors
    assert "rectangular" in text or "plate" in text or "silhouette" in text


def test_structural_gate_accepts_a_tapered_soft_edge_limb_fixture(tmp_path: Path) -> None:
    tool   = _load_png_tool()
    path   = tmp_path / "front_left_upper.png"
    width  = 80
    height = 112

    def tapered_alpha(x: int, y: int) -> int:
        if y < 7 or y >= height - 7:
            return 0
        t           = (y - 7) / (height - 15)
        half_width  = 22.0 - (6.0 * t) + (2.0 * abs(0.5 - t))
        center_x    = (width - 1) / 2.0
        distance    = abs(x - center_x)
        if distance <= half_width - 2.0:
            return 255
        if distance <= half_width:
            return 128
        return 0

    _write_rgba_png(path, width, height, tapered_alpha)
    descriptor = _descriptor(tool, path.name, width, height)

    errors = tool.validate_structural_art_quality(path, descriptor, _quality_contract())

    assert errors == []


def test_structural_gate_rejects_hard_alpha_tail_without_fur_edge(tmp_path: Path) -> None:
    tool   = _load_png_tool()
    path   = tmp_path / "tail_base.png"
    width  = 112
    height = 88

    def hard_tail_alpha(x: int, y: int) -> int:
        dx = (x - 58) / 44.0
        dy = (y - 44) / 30.0
        return 255 if (dx * dx) + (dy * dy) <= 1.0 else 0

    _write_rgba_png(path, width, height, hard_tail_alpha)
    descriptor = _descriptor(tool, path.name, width, height)

    errors = tool.validate_structural_art_quality(path, descriptor, _quality_contract())
    text   = "\n".join(errors).lower()

    assert errors
    assert "soft" in text or "alpha" in text or "fur" in text


def test_standard_overlay_contract_does_not_apply_structural_shape_rejection(tmp_path: Path) -> None:
    tool   = _load_png_tool()
    path   = tmp_path / "eye_left_open.png"
    width  = 64
    height = 48

    def overlay_alpha(x: int, y: int) -> int:
        return 255 if 8 <= x < width - 8 and 8 <= y < height - 8 else 0

    _write_rgba_png(path, width, height, overlay_alpha)
    descriptor = _descriptor(tool, path.name, width, height)
    contract   = {
        "gate": "standard_overlay",
        "reject_rectangular_plate": False,
        "require_soft_alpha_edge": False,
        "forbid_visible_connector_geometry": False,
        "assembly_preview_required": True,
    }

    errors = tool.validate_structural_art_quality(path, descriptor, contract)

    assert errors == []
