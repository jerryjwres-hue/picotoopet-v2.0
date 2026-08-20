from __future__ import annotations

import math
import struct
import sys
import zlib
from pathlib import Path


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


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
    ihdr   = None
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


def build(source: Path, target: Path) -> None:
    width, height, src = decode_rgba(source)
    if (width, height) != (184, 156):
        raise ValueError(f"unexpected torso source size: {width}x{height}")

    left  = [(8, 46), (18, 36), (32, 27), (46, 22), (62, 24), (80, 28), (98, 30), (118, 31), (136, 39), (147, 54)]
    right = [(8, 137), (18, 148), (32, 157), (46, 162), (62, 160), (80, 156), (98, 154), (118, 153), (136, 145), (147, 129)]
    dst   = bytearray(width * height * 4)

    for y in range(height):
        edge_left  = _interp(left, y) + (0.8 * math.sin(y * 0.47))
        edge_right = _interp(right, y) + (0.8 * math.sin((y * 0.43) + 1.1))
        for x in range(width):
            idx = (y * width + x) * 4
            if y < 8 or y > 147 or x < 5 or x > width - 6:
                continue

            if x < edge_left - 3 or x > edge_right + 3:
                alpha = 0.0
            elif x < edge_left + 3:
                alpha = _smoothstep((x - (edge_left - 3)) / 6.0)
            elif x > edge_right - 3:
                alpha = _smoothstep(((edge_right + 3) - x) / 6.0)
            else:
                alpha = 1.0
            if alpha <= 0.0:
                continue

            side     = min(1.0, abs(x - 92.0) / 70.0)
            vertical = min(1.0, max(0.0, (y - 20.0) / 130.0))
            wave     = (
                math.sin((x * 0.41) + (y * 0.17))
                + math.sin((x * 0.13) - (y * 0.37))
            ) * 2.6
            r = 103.0 - (26.0 * side) - (5.0 * vertical) + wave
            g = 91.0 - (24.0 * side) - (5.0 * vertical) + (wave * 0.85)
            b = 100.0 - (20.0 * side) - (3.0 * vertical) + (wave * 0.9)

            # 真实 collar/chest 只在无插口中央区域保留，避免把旧残肢纹理带入候选。
            sr         = src[idx]
            sg         = src[idx + 1]
            sb         = src[idx + 2]
            sa         = src[idx + 3] / 255.0
            brightness = (sr + sg + sb) / 3.0
            safe       = 38 <= x <= 146 and 7 <= y < 122
            if y >= 104:
                safe = safe and 70 <= x <= 116
            for cx, cy, rx, ry in ((27.0, 74.0, 36.0, 25.0), (154.0, 76.0, 36.0, 26.0)):
                if (((x - cx) / rx) ** 2) + (((y - cy) / ry) ** 2) <= 1.0:
                    safe = False
                    break
            if safe and sa > 0.05:
                if brightness > 155.0:
                    weight = 0.94 * sa
                elif brightness > 125.0:
                    weight = 0.58 * sa
                elif y < 60:
                    weight = 0.30 * sa
                else:
                    weight = 0.0
                r = (r * (1.0 - weight)) + (sr * weight)
                g = (g * (1.0 - weight)) + (sg * weight)
                b = (b * (1.0 - weight)) + (sb * weight)

            # 中央奶白胸腹把去掉残肢后的躯干连成完整身体，不制造新的连接环。
            if 52 <= y <= 133:
                t        = (y - 52) / 81.0
                half     = 34.0 - (11.0 * t)
                distance = abs(x - (92.0 + (1.2 * math.sin(y * 0.09))))
                belly    = _smoothstep((half + 4.0 - distance) / 5.0) * 0.32
                r        = (r * (1.0 - belly)) + (224.0 * belly)
                g        = (g * (1.0 - belly)) + (217.0 * belly)
                b        = (b * (1.0 - belly)) + (213.0 * belly)

            # 顶部仅保留浅色毛窝深度，不画 socket、ring 或硬截面。
            opening = math.exp(
                -((((x - 92.0) / 27.0) ** 2) + (((y - 16.0) / 7.0) ** 2))
            ) * 0.55
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
