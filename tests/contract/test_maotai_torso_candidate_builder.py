from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
TOOL_ROOT = ROOT / "windows" / "desktop" / "tools" / "maotai_v2_assets"
ASSET_ROOT = ROOT / "windows" / "desktop" / "src" / "PicotooPet.Desktop" / "Assets" / "Maotai" / "V2"
if str(TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOL_ROOT))

from diagnostic_build_torso_candidate import build  # noqa: E402
from maotai_connector_geometry import validate_visible_connector_geometry  # noqa: E402
from maotai_manifest_contract import AssetDescriptor  # noqa: E402


QUALITY = {
    "gate": "organic_silhouette",
    "reject_rectangular_plate": False,
    "require_soft_alpha_edge": False,
    "forbid_visible_connector_geometry": True,
}


@pytest.mark.parametrize(
    ("file_name", "expected_size"),
    [
        ("torso_neutral.png", (184, 156)),
        ("torso_crouch.png", (192, 144)),
        ("torso_stretch.png", (180, 172)),
    ],
)
def test_torso_candidate_builder_supports_runtime_family(
    tmp_path: Path,
    file_name: str,
    expected_size: tuple[int, int],
) -> None:
    source = ASSET_ROOT / file_name
    target = tmp_path / file_name

    build(source, target)

    descriptor = AssetDescriptor(
        file_name=file_name,
        logical_width=float(expected_size[0] / 2),
        logical_height=float(expected_size[1] / 2),
        pivot_x=float(expected_size[0] / 4),
        pivot_y=float(expected_size[1] / 4),
        z_index=20,
        joint_overlap_pixels=16.0,
    )
    errors = validate_visible_connector_geometry(target, descriptor, QUALITY)

    assert target.is_file()
    assert not errors
