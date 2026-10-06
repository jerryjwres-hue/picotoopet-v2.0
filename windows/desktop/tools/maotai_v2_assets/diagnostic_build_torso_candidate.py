from __future__ import annotations

import math
import struct
import sys
import zlib
from pathlib import Path
from typing import Any


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


_PROFILES: dict[str, dict[str, Any]] = {
    "torso_neutral.png": {
        "size": (184, 156),
        "left": [(8, 46), (18, 36), (32, 27), (46, 22), (62, 24), (80, 28), (98, 30), (118, 31), (136, 39), (147, 54)],
        "right": [(8, 137), (18, 148), (32, 157), (46, 162), (62, 160), (80, 156), (98, 154), (118, 153), (136, 145), (147, 129)],
        "safe_x": (38, 146),
        "lower_y": 104,
        "lower_safe_x": (70, 116),
        "exclude": ((27.0, 74.0, 36.0, 25.0), (154.0, 76.0, 36.0, 26.0)),
        "belly": (52, 133, 0.31, 0.32),
    },
    "torso_crouch.png": {
        "size": (192, 144),
        "left": [(6, 56), (18, 42), (34, 29), (52, 23), (72, 25), (92, 26), (112, 23), (128, 29), (137, 45)],
        "right": [(6, 136), (18, 151), (34, 164), (52, 169), (72, 167), (92, 166), (112, 169), (128, 163), (137, 147)],
        "safe_x": (54, 126),
        "lower_y": 100,
        "lower_safe_x": (78, 114),
        "exclude": (),
        "belly": (48, 130, 0.29, 0.25),
    },
    "torso_stretch.png": {
        "size": (180, 172),
        "left": [(7, 47), (24, 34), (44, 25), (67, 20), (92, 22), (118, 25), (145, 27), (164, 43)],
        "right": [(7, 133), (24, 146), (44, 155), (67, 160), (92, 158), (118, 155), (145, 153), (164, 137)],
        "safe_x": (49, 124),
        "lower_y": 116,
        "lower_safe_x": (74, 110),
        "exclude": (),
        "belly": (47, 154, 0.27, 0.24),
    },
}


def _paeth(left: int, up: int, up_left: int) -> int:
    estimate = left + up - up_left
    dl       = abs(estimate - left)
    du       = abs(estimate - up)
    dul      = abs(estimate - up_left)
    if dl <= du and dl <= dul:
        return left
    if du <= dul:
        return up
    return up_left


def _unfilter(row: bytearray, previous: bytearray, bpp: int, filter_type: int) -> None:
    if filter_type == 0:
        return
    if filter_type == 1:
        for i in range(len(row)):
            left   = row[i - bpp] if i >= bpp else 0
            row[i] = (row[i] + left) & 0xFF
        return
    if filter_type == 2:
        for i in range(len(row)):
            row[i] = (row[i] + previous[i]) & 0xFF
        return
    if filter_type == 3:
        for i in range(len(row)):
            left   = row[i - bpp] if i >= bpp else 0
            up     = previous[i]
            row[i] = (row[i] + ((left + up) // 2)) & 0xFF
        return
    if filter_type == 4:
        for i in range(len(row)):
            left    = row[i - bpp] if i >= bpp else 0
            up      = previous[i]
            up_left = previous[i - bpp] if i >= bpp else 0
            row[i]  = (row[i] + _paeth(left, up, up_left)) & 0xFF
        return
    raise ValueError(f"unsupported PNG filter: {filter_type}")


def decode_rgba(path: Path) -> tuple[int, int, bytearray]:
    data = path.read_bytes()
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError("not a PNG")

    offset = len(PNG_SIGNATURE)
    ihdr: bytes | None = None
    idat: list[bytes] = []
    while offset < len(data):
        length   = struct.unpack(">I", data[offset : offset + 4])[0]
        kind     = data[offset + 4 : offset + 8]
        start    = offset + 8
        end      = start + length
        payload  = data[start:end]
        expected = struct.unpack(">I", data[end : end + 4])[0]
        actual   = zlib.crc32(kind + payload) & 0xFFFFFFFF
        if expected != actual:
            raise ValueError(f"CRC mismatch in {kind!r}")
        if kind == b"IHDR":
            ihdr = payload
        elif kind == b"IDAT":
            idat.append(payload)
        elif kind == b"IEND":
            break
        offset = end + 4

    if ihdr is None:
        raise ValueError("missing IHDR")
    width, height, bit_depth, color_type, compression, filter_method, interlace = struct.unpack(
        ">IIBBBBB", ihdr
    )
    if (bit_depth, color_type, compression, filter_method, interlace) != (8, 6, 0, 0, 0):
        raise ValueError("expected non-interlaced RGBA8 PNG")

    raw      = zlib.decompress(b"".join(idat))
    stride   = width * 4
    previous = bytearray(stride)
    pixels   = bytearray(width * height * 4)
    cursor   = 0
    out      = 0
    for _ in range(height):
        filter_type = raw[cursor]
        cursor     += 1
        row         = bytearray(raw[cursor : cursor + stride])
        cursor     += stride
        _unfilter(row, previous, 4, filter_type)
        pixels[out : out + stride] = row
        out      += stride
        previous  = row
    return width, height, pixels


def _chunk(kind: bytes, payload: bytes) -> bytes:
    crc = zlib.crc32(kind + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", crc)


def encode_rgba(path: Path, width: int, height: int, pixels: bytearray) -> None:
    stride = width * 4
    scan   = bytearray()
    for y in range(height):
        scan.append(0)
        start = y * stride
        scan.extend(pixels[start : start + stride])
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    png  = (
        PNG_SIGNATURE
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", zlib.compress(bytes(scan), 9))
        + _chunk(b"IEND", b"")
    )
    path.write_bytes(png)


def _smoothstep(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return value * value * (3.0 - (2.0 * value))


def _interp(points: list[tuple[int, float]], y: int) -> float:
    if y <= points[0][0]:
        return points[0][1]
    if y >= points[-1][0]:
        return points[-1][1]
    for (y0, x0), (y1, x1) in zip(points, points[1:]):
        if y0 <= y <= y1:
            t = _smoothstep((y - y0) / float(y1 - y0))
            return x0 + ((x1 - x0) * t)
    return points[-1][1]


def _inside_excluded_connector(
    x: int,
    y: int,
    regions: tuple[tuple[float, float, float, float], ...],
) -> bool:
    for center_x, center_y, radius_x, radius_y in regions:
        dx = (x - center_x) / radius_x
        dy = (y - center_y) / radius_y
        if (dx * dx) + (dy * dy) <= 1.0:
            return True
    return False


def build(source: Path, target: Path) -> None:
    profile = _PROFILES.get(source.name)
    if profile is None:
        raise ValueError(f"unsupported torso source: {source.name}")

    width, height, src = decode_rgba(source)
    expected_size = profile["size"]
    if (width, height) != expected_size:
        raise ValueError(
            f"unexpected {source.name} source size: {width}x{height}; "
            f"expected {expected_size[0]}x{expected_size[1]}"
        )

    left: list[tuple[int, float]]  = profile["left"]
    right: list[tuple[int, float]] = profile["right"]
    safe_x: tuple[int, int]        = profile["safe_x"]
    lower_safe_x: tuple[int, int]  = profile["lower_safe_x"]
    lower_y: int                   = profile["lower_y"]
    excluded                       = profile["exclude"]
    belly_y0, belly_y1, belly_half, belly_amount = profile["belly"]
    dst = bytearray(width * height * 4)

    for y in range(height):
        if y < left[0][0] or y > left[-1][0]:
            continue

        edge_left  = _interp(left, y) + (0.7 * math.sin(y * 0.47))
        edge_right = _interp(right, y) + (0.7 * math.sin((y * 0.43) + 1.1))
        center_x   = (edge_left + edge_right) / 2.0
        half_width = max(1.0, (edge_right - edge_left) / 2.0)

        for x in range(width):
            idx = (y * width + x) * 4
            if x < edge_left - 3 or x > edge_right + 3:
                continue

            if x < edge_left + 3:
                alpha = _smoothstep((x - (edge_left - 3)) / 6.0)
            elif x > edge_right - 3:
                alpha = _smoothstep(((edge_right + 3) - x) / 6.0)
            else:
                alpha = 1.0
            if alpha <= 0.0:
                continue

            side     = min(1.0, abs(x - center_x) / half_width)
            vertical = min(1.0, max(0.0, (y - 15.0) / max(1.0, height - 25.0)))
            wave     = (
                math.sin((x * 0.41) + (y * 0.17))
                + math.sin((x * 0.13) - (y * 0.37))
                + (0.55 * math.sin((x * 0.82) + (y * 0.23)))
            ) * 2.3
            strand = 1.6 * math.sin((y * 0.65) + (x * 0.09)) * (1.0 - side)
            r = 104.0 - (28.0 * side) - (5.0 * vertical) + wave + strand
            g = 92.0 - (25.0 * side) - (5.0 * vertical) + (wave * 0.84) + (strand * 0.80)
            b = 101.0 - (21.0 * side) - (3.0 * vertical) + (wave * 0.90) + (strand * 0.85)

            use_source = safe_x[0] <= x <= safe_x[1]
            if y >= lower_y:
                use_source = use_source and lower_safe_x[0] <= x <= lower_safe_x[1]
            if _inside_excluded_connector(x, y, excluded):
                use_source = False

            sr         = src[idx]
            sg         = src[idx + 1]
            sb         = src[idx + 2]
            sa         = src[idx + 3] / 255.0
            brightness = (sr + sg + sb) / 3.0
            if use_source and sa > 0.05:
                if brightness > 155.0:
                    weight = 0.94 * sa
                elif brightness > 130.0:
                    weight = 0.60 * sa
                elif y < 55:
                    weight = 0.25 * sa
                else:
                    weight = 0.0
                r = (r * (1.0 - weight)) + (sr * weight)
                g = (g * (1.0 - weight)) + (sg * weight)
                b = (b * (1.0 - weight)) + (sb * weight)

            if belly_y0 <= y <= belly_y1:
                t        = (y - belly_y0) / float(max(1, belly_y1 - belly_y0))
                half     = (belly_half - (0.08 * t)) * (edge_right - edge_left)
                distance = abs(x - center_x)
                belly    = _smoothstep((half + 5.0 - distance) / 7.0) * belly_amount
                r        = (r * (1.0 - belly)) + (226.0 * belly)
                g        = (g * (1.0 - belly)) + (220.0 * belly)
                b        = (b * (1.0 - belly)) + (216.0 * belly)

            if y <= 28:
                opening = math.exp(
                    -((((x - center_x) / 27.0) ** 2) + (((y - 16.0) / 7.0) ** 2))
                ) * 0.48
                r = (r * (1.0 - opening)) + (92.0 * opening)
                g = (g * (1.0 - opening)) + (80.0 * opening)
                b = (b * (1.0 - opening)) + (90.0 * opening)

            dst[idx]     = max(0, min(255, round(r)))
            dst[idx + 1] = max(0, min(255, round(g)))
            dst[idx + 2] = max(0, min(255, round(b)))
            dst[idx + 3] = max(0, min(255, round(alpha * 255.0)))

    encode_rgba(target, width, height, dst)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: diagnostic_build_torso_candidate.py SOURCE TARGET")
    build(Path(sys.argv[1]), Path(sys.argv[2]))
