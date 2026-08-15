from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path

from maotai_manifest_contract import AssetDescriptor


PNG_SIGNATURE       = b"\x89PNG\r\n\x1a\n"
MIN_PIXEL_DENSITY   = 2.0
MIN_TRANSPARENT_PAD = 2
MAX_PIXEL_DIMENSION = 8192


class PngMetrics:
    """PNG 解码后的最小质量遥测；不保留整张像素图。"""

    __slots__ = (
        "width",
        "height",
        "visible_count",
        "transparent_count",
        "min_x",
        "min_y",
        "max_x",
        "max_y",
        "border_is_transparent",
    )

    def __init__(
        self,
        width: int,
        height: int,
        visible_count: int,
        transparent_count: int,
        min_x: int,
        min_y: int,
        max_x: int,
        max_y: int,
        border_is_transparent: bool,
    ) -> None:
        self.width                 = width
        self.height                = height
        self.visible_count         = visible_count
        self.transparent_count     = transparent_count
        self.min_x                 = min_x
        self.min_y                 = min_y
        self.max_x                 = max_x
        self.max_y                 = max_y
        self.border_is_transparent = border_is_transparent


def validate_png_asset(path: Path, descriptor: AssetDescriptor) -> list[str]:
    """镜像 WPF pixel Gate：2x 密度、真实 alpha、透明外边界和至少 2px 安全边距。"""
    errors: list[str] = []
    try:
        metrics = decode_png_metrics(path)
    except (OSError, ValueError, zlib.error) as error:
        return [f"{descriptor.file_name}: invalid PNG: {error}"]

    minimum_width  = math.ceil(descriptor.logical_width * MIN_PIXEL_DENSITY)
    minimum_height = math.ceil(descriptor.logical_height * MIN_PIXEL_DENSITY)
    if metrics.width < minimum_width or metrics.height < minimum_height:
        errors.append(
            f"{descriptor.file_name}: below 2x logical density "
            f"({metrics.width}x{metrics.height} < {minimum_width}x{minimum_height})"
        )
    if metrics.visible_count <= 0:
        errors.append(f"{descriptor.file_name}: no visible pixels")
    if metrics.transparent_count <= 0:
        errors.append(f"{descriptor.file_name}: alpha is fully opaque")
    if not metrics.border_is_transparent:
        errors.append(f"{descriptor.file_name}: outer border alpha must be zero")

    if metrics.visible_count > 0:
        right_limit  = metrics.width - MIN_TRANSPARENT_PAD - 1
        bottom_limit = metrics.height - MIN_TRANSPARENT_PAD - 1
        if (
            metrics.min_x < MIN_TRANSPARENT_PAD
            or metrics.min_y < MIN_TRANSPARENT_PAD
            or metrics.max_x > right_limit
            or metrics.max_y > bottom_limit
        ):
            errors.append(
                f"{descriptor.file_name}: visible pixels touch the protected canvas edge"
            )

    return errors


def decode_png_metrics(path: Path) -> PngMetrics:
    data = path.read_bytes()
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError("invalid PNG signature")

    offset                  = len(PNG_SIGNATURE)
    ihdr: bytes | None      = None
    idat_parts: list[bytes] = []
    saw_iend                = False

    while offset < len(data):
        if offset + 12 > len(data):
            raise ValueError("truncated PNG chunk")

        length = struct.unpack(">I", data[offset : offset + 4])[0]
        kind   = data[offset + 4 : offset + 8]
        start  = offset + 8
        end    = start + length
        if end + 4 > len(data):
            raise ValueError("truncated PNG payload")

        payload      = data[start:end]
        expected_crc = struct.unpack(">I", data[end : end + 4])[0]
        actual_crc   = zlib.crc32(kind + payload) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            label = kind.decode("ascii", errors="replace")
            raise ValueError(f"CRC mismatch in {label}")

        if kind == b"IHDR":
            if ihdr is not None or length != 13:
                raise ValueError("invalid IHDR")
            ihdr = payload
        elif kind == b"IDAT":
            idat_parts.append(payload)
        elif kind == b"IEND":
            saw_iend = True
            break

        offset = end + 4

    if ihdr is None:
        raise ValueError("missing IHDR")
    if not idat_parts:
        raise ValueError("missing IDAT")
    if not saw_iend:
        raise ValueError("missing IEND")

    (
        width,
        height,
        bit_depth,
        color_type,
        compression_method,
        filter_method,
        interlace_method,
    ) = struct.unpack(">IIBBBBB", ihdr)

    if width <= 0 or height <= 0:
        raise ValueError("invalid pixel dimensions")
    if width > MAX_PIXEL_DIMENSION or height > MAX_PIXEL_DIMENSION:
        raise ValueError("pixel dimensions exceed production safety limit")
    if bit_depth != 8:
        raise ValueError("only 8-bit production PNGs are accepted")
    if color_type not in (4, 6):
        raise ValueError("alpha channel required; expected PNG color type 4 or 6")
    if compression_method != 0 or filter_method != 0:
        raise ValueError("unsupported PNG compression/filter method")
    if interlace_method != 0:
        raise ValueError("interlaced PNGs are not accepted for deterministic staging")

    bytes_per_pixel = 2 if color_type == 4 else 4
    alpha_offset    = 1 if color_type == 4 else 3
    stride          = width * bytes_per_pixel
    expected_bytes  = height * (stride + 1)
    raw             = zlib.decompress(b"".join(idat_parts))
    if len(raw) != expected_bytes:
        raise ValueError(
            f"unexpected decompressed size: {len(raw)} != {expected_bytes}"
        )

    previous_row          = bytearray(stride)
    visible_count         = 0
    transparent_count     = 0
    min_x                 = width
    min_y                 = height
    max_x                 = -1
    max_y                 = -1
    border_is_transparent = True
    cursor                = 0

    for y in range(height):
        filter_type = raw[cursor]
        cursor     += 1
        row         = bytearray(raw[cursor : cursor + stride])
        cursor     += stride
        _unfilter_row(row, previous_row, bytes_per_pixel, filter_type)

        for x in range(width):
            alpha = row[(x * bytes_per_pixel) + alpha_offset]
            if alpha == 0:
                transparent_count += 1
                continue

            visible_count += 1
            min_x = min(min_x, x)
            min_y = min(min_y, y)
            max_x = max(max_x, x)
            max_y = max(max_y, y)
            if x == 0 or x == width - 1 or y == 0 or y == height - 1:
                border_is_transparent = False

        previous_row = row

    return PngMetrics(
        width,
        height,
        visible_count,
        transparent_count,
        min_x,
        min_y,
        max_x,
        max_y,
        border_is_transparent,
    )


def _unfilter_row(
    row: bytearray,
    previous_row: bytearray,
    bytes_per_pixel: int,
    filter_type: int,
) -> None:
    if filter_type == 0:
        return
    if filter_type == 1:
        for index in range(len(row)):
            left       = row[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
            row[index] = (row[index] + left) & 0xFF
        return
    if filter_type == 2:
        for index in range(len(row)):
            row[index] = (row[index] + previous_row[index]) & 0xFF
        return
    if filter_type == 3:
        for index in range(len(row)):
            left       = row[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
            up         = previous_row[index]
            row[index] = (row[index] + ((left + up) // 2)) & 0xFF
        return
    if filter_type == 4:
        for index in range(len(row)):
            left    = row[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
            up      = previous_row[index]
            up_left = previous_row[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
            row[index] = (row[index] + _paeth(left, up, up_left)) & 0xFF
        return

    raise ValueError(f"unsupported PNG filter type: {filter_type}")


def _paeth(left: int, up: int, up_left: int) -> int:
    estimate         = left + up - up_left
    left_distance    = abs(estimate - left)
    up_distance      = abs(estimate - up)
    up_left_distance = abs(estimate - up_left)
    if left_distance <= up_distance and left_distance <= up_left_distance:
        return left
    if up_distance <= up_left_distance:
        return up
    return up_left
