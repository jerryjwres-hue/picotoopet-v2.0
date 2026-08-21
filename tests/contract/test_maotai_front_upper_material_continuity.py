from __future__ import annotations

import statistics
import sys
from pathlib import Path

import pytest


ROOT       = Path(__file__).resolve().parents[2]
TOOL_ROOT  = ROOT / "windows" / "desktop" / "tools" / "maotai_v2_assets"
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

    top_values: list[float]    = []
    bottom_values: list[float] = []
    row_spans: list[int]       = []
    shoulder_spans: list[int]  = []
    shaft_spans: list[int]     = []
    lower_spans: list[int]     = []
    row_centers: list[float]   = []

    for y, xs in visible_rows:
        progress = (y - first_y) / span_y
        row_span = xs[-1] - xs[0] + 1
        row_spans.append(row_span)
        row_centers.append((xs[0] + xs[-1]) / 2.0)

        if 0.08 <= progress <= 0.28:
            shoulder_spans.append(row_span)
        elif 0.38 <= progress <= 0.60:
            shaft_spans.append(row_span)
        elif 0.68 <= progress <= 0.88:
            lower_spans.append(row_span)

        for x in xs:
            idx        = ((y * width) + x) * 4
            brightness = (pixels[idx] + pixels[idx + 1] + pixels[idx + 2]) / 3.0
            if progress <= 0.35:
                top_values.append(brightness)
            elif progress >= 0.65:
                bottom_values.append(brightness)

    top_mean       = sum(top_values) / len(top_values)
    bottom_mean    = sum(bottom_values) / len(bottom_values)
    shoulder_width = statistics.median(shoulder_spans)
    shaft_width    = statistics.median(shaft_spans)
    lower_width    = statistics.median(lower_spans)
    center_drift   = max(row_centers) - min(row_centers)

    # Renderer still stretches Upper toward the paw, so material continuity must
    # live in the asset instead of falling back to one dark rectangular bar.
    assert bottom_mean - top_mean >= 65.0
    assert bottom_mean >= 130.0
    assert max(row_spans) - min(row_spans) >= 14

    # The upper limb must also read as anatomy: a broad shoulder overlap narrows
    # into the foreleg, then only modestly flares into lower fur. Requiring a
    # small centerline excursion prevents a mathematically straight pillar while
    # preserving the existing pivot and canvas semantics.
    assert shoulder_width - shaft_width >= 9
    assert 2 <= lower_width - shaft_width <= 7
    assert center_drift >= 2.5
