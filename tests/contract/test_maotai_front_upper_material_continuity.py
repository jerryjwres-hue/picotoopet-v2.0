from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
TOOL_ROOT = ROOT / "windows" / "desktop" / "tools" / "maotai_v2_assets"
ASSET_ROOT = ROOT / "windows" / "desktop" / "src" / "PicotooPet.Desktop" / "Assets" / "Maotai" / "V2"
if str(TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOL_ROOT))

from diagnostic_build_torso_candidate import decode_rgba  # noqa: E402


@pytest.mark.parametrize("file_name", ["front_left_upper.png", "front_right_upper.png"])
def test_runtime_front_upper_reads_as_complete_furred_leg(file_name: str) -> None:
    width, height, pixels = decode_rgba(ASSET_ROOT / file_name)
    visible_rows: list[tuple[int, list[int]]] = []

    for y in range(height):
        row = []
        for x in range(width):
            idx = ((y * width) + x) * 4
            if pixels[idx + 3] > 20:
                row.append(x)
        if row:
            visible_rows.append((y, row))

    assert visible_rows
    first_y = visible_rows[0][0]
    last_y  = visible_rows[-1][0]
    span_y  = max(1, last_y - first_y)

    top_values: list[float] = []
    bottom_values: list[float] = []
    row_spans: list[int] = []
    for y, xs in visible_rows:
        row_spans.append(xs[-1] - xs[0] + 1)
        for x in xs:
            idx        = ((y * width) + x) * 4
            brightness = (pixels[idx] + pixels[idx + 1] + pixels[idx + 2]) / 3.0
            progress   = (y - first_y) / span_y
            if progress <= 0.35:
                top_values.append(brightness)
            elif progress >= 0.65:
                bottom_values.append(brightness)

    top_mean    = sum(top_values) / len(top_values)
    bottom_mean = sum(bottom_values) / len(bottom_values)

    # Current Renderer stretches Upper to the paw. The asset therefore must carry
    # a real dark-fur -> warm-cream transition instead of reading as one dark bar.
    assert bottom_mean - top_mean >= 65.0
    assert bottom_mean >= 130.0
    assert max(row_spans) - min(row_spans) >= 14
