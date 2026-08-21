from __future__ import annotations

import statistics
import sys
from pathlib import Path


ROOT      = Path(__file__).resolve().parents[2]
TOOL_ROOT = ROOT / "windows" / "desktop" / "tools" / "maotai_v2_assets"
if str(TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOL_ROOT))

from diagnostic_build_front_upper_candidate import build_pair  # noqa: E402
from diagnostic_build_torso_candidate import decode_rgba        # noqa: E402


def _silhouette_metrics(path: Path) -> dict[str, float]:
    width, height, pixels = decode_rgba(path)
    rows: list[tuple[int, list[int]]] = []

    for y in range(height):
        xs = [x for x in range(width) if pixels[((y * width) + x) * 4 + 3] > 20]
        if xs:
            rows.append((y, xs))

    assert rows
    first_y = rows[0][0]
    last_y  = rows[-1][0]
    span_y  = max(1, last_y - first_y)

    shoulder: list[int] = []
    shaft: list[int]    = []
    lower: list[int]    = []
    centers: list[float] = []
    top_values: list[float] = []
    bottom_values: list[float] = []

    for y, xs in rows:
        progress = (y - first_y) / span_y
        row_span = xs[-1] - xs[0] + 1
        centers.append((xs[0] + xs[-1]) / 2.0)

        if 0.08 <= progress <= 0.28:
            shoulder.append(row_span)
        elif 0.38 <= progress <= 0.60:
            shaft.append(row_span)
        elif 0.68 <= progress <= 0.88:
            lower.append(row_span)

        for x in xs:
            idx        = ((y * width) + x) * 4
            brightness = (pixels[idx] + pixels[idx + 1] + pixels[idx + 2]) / 3.0
            if progress <= 0.35:
                top_values.append(brightness)
            elif progress >= 0.65:
                bottom_values.append(brightness)

    return {
        "width": float(width),
        "height": float(height),
        "shoulder": float(statistics.median(shoulder)),
        "shaft": float(statistics.median(shaft)),
        "lower": float(statistics.median(lower)),
        "center_drift": max(centers) - min(centers),
        "top_mean": sum(top_values) / len(top_values),
        "bottom_mean": sum(bottom_values) / len(bottom_values),
    }


def test_front_upper_candidate_builder_outputs_mirrored_organic_pair(tmp_path: Path) -> None:
    left_path, right_path = build_pair(tmp_path)

    left_width, left_height, left_pixels    = decode_rgba(left_path)
    right_width, right_height, right_pixels = decode_rgba(right_path)
    assert (left_width, left_height) == (68, 92)
    assert (right_width, right_height) == (68, 92)

    for y in range(left_height):
        for x in range(left_width):
            left_alpha  = left_pixels[((y * left_width) + x) * 4 + 3]
            mirror_x    = right_width - 1 - x
            right_alpha = right_pixels[((y * right_width) + mirror_x) * 4 + 3]
            assert abs(left_alpha - right_alpha) <= 1

    for path in (left_path, right_path):
        metrics = _silhouette_metrics(path)

        # Preserve the existing rig canvas while replacing a straight pillar
        # with broad shoulder overlap, a narrower shaft, and modest lower fur.
        assert (metrics["width"], metrics["height"]) == (68.0, 92.0)
        assert metrics["shoulder"] - metrics["shaft"] >= 9.0
        assert 2.0 <= metrics["lower"] - metrics["shaft"] <= 7.0
        assert metrics["center_drift"] >= 2.5

        # Renderer still stretches Upper toward the paw, so this single runtime
        # asset must retain the charcoal-to-warm-cream material transition.
        assert metrics["bottom_mean"] - metrics["top_mean"] >= 65.0
        assert metrics["bottom_mean"] >= 130.0
