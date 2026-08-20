from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TOOL_ROOT = ROOT / "windows" / "desktop" / "tools" / "maotai_v2_assets"
if str(TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOL_ROOT))

from maotai_connector_geometry import validate_visible_connector_geometry  # noqa: E402
from maotai_manifest_contract import AssetDescriptor  # noqa: E402


QUALITY = {
    "gate": "organic_silhouette",
    "reject_rectangular_plate": False,
    "require_soft_alpha_edge": False,
    "forbid_visible_connector_geometry": True,
}


def _descriptor() -> AssetDescriptor:
    return AssetDescriptor(
        file_name="torso_neutral.png",
        logical_width=80.0,
        logical_height=100.0,
        pivot_x=40.0,
        pivot_y=50.0,
        z_index=20,
        joint_overlap_pixels=16.0,
    )


def _inside_ellipse(
    x: int,
    y: int,
    center_x: float,
    center_y: float,
    radius_x: float,
    radius_y: float,
) -> bool:
    dx = (x - center_x) / radius_x
    dy = (y - center_y) / radius_y
    return (dx * dx) + (dy * dy) <= 1.0


def _write_rgba_png(path: Path, *, with_connector_lobes: bool) -> None:
    width = 160
    height = 200
    scanlines = bytearray()

    for y in range(height):
        scanlines.append(0)
        for x in range(width):
            visible = _inside_ellipse(x, y, 80.0, 108.0, 45.0, 78.0)
            if with_connector_lobes:
                shoulder_lobe = (
                    _inside_ellipse(x, y, 34.0, 70.0, 19.0, 15.0)
                    or _inside_ellipse(x, y, 126.0, 70.0, 19.0, 15.0)
                )
                shoulder_neck = 35 <= y <= 78 and (38 <= x <= 58 or 102 <= x <= 122)
                visible = visible or shoulder_lobe or shoulder_neck

            alpha = 255 if visible else 0
            scanlines.extend((90, 90, 96, alpha))

    compressed = zlib.compress(bytes(scanlines), level=9)

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", compressed)
        + chunk(b"IEND", b"")
    )
    path.write_bytes(png)


def test_torso_connector_lobes_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "torso_neutral.png"
    _write_rgba_png(path, with_connector_lobes=True)

    errors = validate_visible_connector_geometry(path, _descriptor(), QUALITY)

    assert any("connector" in error.lower() or "stump" in error.lower() for error in errors)


def test_smooth_torso_silhouette_has_no_connector_error(tmp_path: Path) -> None:
    path = tmp_path / "torso_neutral.png"
    _write_rgba_png(path, with_connector_lobes=False)

    errors = validate_visible_connector_geometry(path, _descriptor(), QUALITY)

    assert not any("connector" in error.lower() or "stump" in error.lower() for error in errors)
