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
    (28, 31.3),
    (44, 28.8),
    (58, 29.3),
    (72, 31.3),
    (88, 32.4),
)
_HALF_WIDTH_POINTS: tuple[tuple[int, float], ...] = (
    (3, 18.6),
    (14, 17.0),
    (28, 13.3),
    (44, 10.0),
    (58, 9.8),
    (72, 10.3),
    (88, 10.7),
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
        left_wave  = (0.32 * math.sin((y * 0.18) + 0.6)) + (0.18 * math.sin(y * 0.34))
        right_wave = (0.30 * math.sin((y * 0.16) + 1.8)) + (0.16 * math.sin((y * 0.29) + 0.4))
        outer_tuft = _bump(y, 14, 5, 2.4) + _bump(y, 25, 4.5, 1.2) + _bump(y, 63, 5.5, 1.1)
        inner_tuft = _bump(y, 10, 4.5, 1.1) + _bump(y, 54, 5.5, 0.7) + _bump(y, 78, 4.5, 0.9)

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

            if x < edge_left + 2.3:
                alpha = _smoothstep((x - (edge_left - 3.0)) / 5.3)
            elif x > edge_right - 2.3:
                alpha = _smoothstep(((edge_right + 3.0) - x) / 5.3)
            else:
                alpha = 1.0
            if alpha <= 0.0:
                continue

            side    = min(1.0, abs(x - row_center) / row_half)
            texture = (
                math.sin((x * 0.45) + (y * 0.22))
                + (0.42 * math.sin((x * 0.17) - (y * 0.39)))
                + (0.28 * math.sin((x * 0.88) + (y * 0.12)))
            )
            dark = (
                82.0 - (20.0 * side) + (3.3 * texture),
                76.0 - (18.0 * side) + (2.9 * texture),
                82.0 - (15.0 * side) + (3.1 * texture),
            )
            cream = (
                225.0 - (30.0 * side) + (3.7 * texture),
                218.0 - (28.0 * side) + (3.3 * texture),
                211.0 - (25.0 * side) + (3.4 * texture),
            )

            # Delay the warm-cream transition and break it into longitudinal
            # fur strands so the lower leg does not read as a horizontal sock.
            inner_coordinate = (x - row_center) / row_half
            wedge            = 0.045 * inner_coordinate * (-1.0 if mirror else 1.0)
            strand_phase     = 1.1 if mirror else 0.0
            strand           = 0.035 * math.sin((x * 0.42) + (y * 0.12) + strand_phase)
            cream_mix        = _smoothstep((progress - 0.52 + wedge + strand) / 0.38)
            if not mirror:
                inner_weight = _smoothstep((inner_coordinate + 0.05) / 0.95)
            else:
                inner_weight = _smoothstep((-inner_coordinate + 0.05) / 0.95)
            inner_lock = 0.08 * inner_weight * _bump(progress, 0.58, 0.11, 1.0)
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
