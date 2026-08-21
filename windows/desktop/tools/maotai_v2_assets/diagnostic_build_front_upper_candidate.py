from __future__ import annotations

import math
import sys
from pathlib import Path

from diagnostic_build_torso_candidate import encode_rgba


WIDTH  = 68
HEIGHT = 92

_CENTER_POINTS: tuple[tuple[int, float], ...] = (
    (3, 34.0),
    (14, 33.6),
    (28, 32.3),
    (44, 31.2),
    (58, 31.4),
    (72, 32.4),
    (88, 33.2),
)
_HALF_WIDTH_POINTS: tuple[tuple[int, float], ...] = (
    (3, 18.5),
    (14, 17.2),
    (28, 13.7),
    (44, 10.5),
    (58, 10.9),
    (72, 11.8),
    (88, 12.5),
)


def _smoothstep(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return value * value * (3.0 - (2.0 * value))


def _lerp(start: float, end: float, amount: float) -> float:
    return start + ((end - start) * amount)


def _profile(points: tuple[tuple[int, float], ...], y: int) -> float:
    if y <= points[0][0]:
        return points[0][1]
    if y >= points[-1][0]:
        return points[-1][1]

    for (y0, value0), (y1, value1) in zip(points, points[1:]):
        if y0 <= y <= y1:
            amount = _smoothstep((y - y0) / float(y1 - y0))
            return _lerp(value0, value1, amount)
    return points[-1][1]


def _bump(y: float, center: float, sigma: float, amplitude: float) -> float:
    distance = (y - center) / sigma
    return amplitude * math.exp(-0.5 * distance * distance)


def _build_one(path: Path, *, mirror: bool) -> None:
    pixels = bytearray(WIDTH * HEIGHT * 4)

    for y in range(HEIGHT):
        if y < 3 or y > 88:
            continue

        center_x = _profile(_CENTER_POINTS, y)
        if mirror:
            center_x = (WIDTH - 1) - center_x
        half_width = _profile(_HALF_WIDTH_POINTS, y)

        # Low-frequency edge motion plus a few broad tufts keeps the outline
        # organic without creating a sawtooth or another symmetric hourglass.
        left_wave  = (0.45 * math.sin((y * 0.19) + 0.6)) + (0.28 * math.sin(y * 0.37))
        right_wave = (0.38 * math.sin((y * 0.17) + 1.8)) + (0.24 * math.sin((y * 0.31) + 0.4))
        outer_tuft = _bump(y, 14, 5, 2.6) + _bump(y, 23, 4, 1.5) + _bump(y, 66, 5, 1.7)
        inner_tuft = _bump(y, 10, 4, 1.3) + _bump(y, 55, 5, 1.0) + _bump(y, 78, 4, 1.6)

        if not mirror:
            edge_left  = center_x - half_width - left_wave - outer_tuft
            edge_right = center_x + half_width + right_wave + inner_tuft
        else:
            edge_left  = center_x - half_width - right_wave - inner_tuft
            edge_right = center_x + half_width + left_wave + outer_tuft

        row_center = (edge_left + edge_right) / 2.0
        row_half   = max(1.0, (edge_right - edge_left) / 2.0)
        progress   = (y - 3) / 85.0

        for x in range(WIDTH):
            if x < edge_left - 3.0 or x > edge_right + 3.0:
                continue

            if x < edge_left + 2.5:
                alpha = _smoothstep((x - (edge_left - 3.0)) / 5.5)
            elif x > edge_right - 2.5:
                alpha = _smoothstep(((edge_right + 3.0) - x) / 5.5)
            else:
                alpha = 1.0
            if alpha <= 0.0:
                continue

            side    = min(1.0, abs(x - row_center) / row_half)
            texture = (
                math.sin((x * 0.47) + (y * 0.23))
                + (0.45 * math.sin((x * 0.18) - (y * 0.41)))
                + (0.30 * math.sin((x * 0.91) + (y * 0.13)))
            )
            dark = (
                82.0 - (20.0 * side) + (3.4 * texture),
                76.0 - (18.0 * side) + (3.0 * texture),
                82.0 - (15.0 * side) + (3.2 * texture),
            )
            cream = (
                224.0 - (31.0 * side) + (3.8 * texture),
                217.0 - (29.0 * side) + (3.4 * texture),
                210.0 - (26.0 * side) + (3.5 * texture),
            )

            # The warm-cream transition follows an inner-fur wedge instead of
            # a horizontal band, which prevents a painted sock/cuff appearance.
            inner_coordinate = (x - row_center) / row_half
            wedge            = 0.055 * inner_coordinate * (-1.0 if mirror else 1.0)
            cream_mix        = _smoothstep((progress - 0.48 + wedge) / 0.34)
            if not mirror:
                inner_weight = _smoothstep((inner_coordinate + 0.05) / 0.95)
            else:
                inner_weight = _smoothstep((-inner_coordinate + 0.05) / 0.95)
            inner_lock = 0.12 * inner_weight * _bump(progress, 0.53, 0.10, 1.0)
            cream_mix = min(1.0, cream_mix + inner_lock)

            highlight = ((1.0 - side) ** 1.8) * 6.0
            red       = _lerp(dark[0], cream[0], cream_mix) + highlight
            green     = _lerp(dark[1], cream[1], cream_mix) + highlight
            blue      = _lerp(dark[2], cream[2], cream_mix) + highlight

            idx             = ((y * WIDTH) + x) * 4
            pixels[idx]     = max(0, min(255, round(red)))
            pixels[idx + 1] = max(0, min(255, round(green)))
            pixels[idx + 2] = max(0, min(255, round(blue)))
            pixels[idx + 3] = max(0, min(255, round(alpha * 255.0)))

    encode_rgba(path, WIDTH, HEIGHT, pixels)


def build_pair(output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    left_path  = output_dir / "front_left_upper.png"
    right_path = output_dir / "front_right_upper.png"
    _build_one(left_path, mirror=False)
    _build_one(right_path, mirror=True)
    return left_path, right_path


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: diagnostic_build_front_upper_candidate.py OUTPUT_DIR")
    build_pair(Path(sys.argv[1]))
