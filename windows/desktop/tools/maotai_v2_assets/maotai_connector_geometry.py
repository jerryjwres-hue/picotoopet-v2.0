from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path
from typing import Mapping

from maotai_manifest_contract import AssetDescriptor
from maotai_png_validation import MAX_PIXEL_DIMENSION, PNG_SIGNATURE, _unfilter_row


_TORSO_SIDE_LOBE_RETURN_LIMIT = 0.12


def validate_visible_connector_geometry(
    path: Path,
    descriptor: AssetDescriptor,
    quality_contract: Mapping[str, object],
) -> list[str]:
    """拒绝 torso 上会读成肩/髋插口或截肢残根的侧向凸起轮廓。"""
    if not bool(quality_contract.get("forbid_visible_connector_geometry")):
        return []
    if not descriptor.file_name.startswith("torso_"):
        return []

    try:
        return_ratio = measure_torso_side_lobe_return_ratio(path)
    except (OSError, ValueError, zlib.error) as error:
        return [f"{descriptor.file_name}: connector geometry decode failed: {error}"]

    if return_ratio < _TORSO_SIDE_LOBE_RETURN_LIMIT:
        return []

    return [
        f"{descriptor.file_name}: visible connector/stump geometry detected "
        f"(side_lobe_return={return_ratio:.3f} >= {_TORSO_SIDE_LOBE_RETURN_LIMIT:.3f})"
    ]


def measure_torso_side_lobe_return_ratio(path: Path) -> float:
    """量化上半身侧凸后快速回缩；插口/残根会形成明显局部峰值，连续躯干不会。"""
    row_spans = _decode_visible_row_spans(path)
    if len(row_spans) < 8:
        return 0.0

    maximum_span = max(row_spans)
    if maximum_span <= 0:
        return 0.0

    row_count       = len(row_spans)
    search_start    = max(0, int(math.floor(row_count * 0.15)))
    search_end      = min(row_count - 1, int(math.floor(row_count * 0.55)))
    lookahead_rows  = max(3, int(math.ceil(row_count * 0.20)))
    strongest_ratio = 0.0

    for index in range(search_start, search_end + 1):
        end = min(row_count, index + lookahead_rows + 1)
        if index + 1 >= end:
            continue

        peak_span   = row_spans[index]
        return_span = min(row_spans[index + 1 : end])
        if return_span >= peak_span:
            continue

        ratio = (peak_span - return_span) / float(maximum_span)
        strongest_ratio = max(strongest_ratio, ratio)

    return strongest_ratio


def _decode_visible_row_spans(path: Path) -> list[int]:
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

    if ihdr is None or not idat_parts or not saw_iend:
        raise ValueError("incomplete PNG structure")

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
    if bit_depth != 8 or color_type not in (4, 6):
        raise ValueError("8-bit alpha PNG required")
    if compression_method != 0 or filter_method != 0 or interlace_method != 0:
        raise ValueError("unsupported production PNG encoding")

    bytes_per_pixel = 2 if color_type == 4 else 4
    alpha_offset    = 1 if color_type == 4 else 3
    stride          = width * bytes_per_pixel
    raw             = zlib.decompress(b"".join(idat_parts))
    expected_bytes  = height * (stride + 1)
    if len(raw) != expected_bytes:
        raise ValueError(f"unexpected decompressed size: {len(raw)} != {expected_bytes}")

    previous_row         = bytearray(stride)
    row_spans: list[int] = []
    cursor               = 0

    for _ in range(height):
        filter_type = raw[cursor]
        cursor     += 1
        row         = bytearray(raw[cursor : cursor + stride])
        cursor     += stride
        _unfilter_row(row, previous_row, bytes_per_pixel, filter_type)

        minimum_x = width
        maximum_x = -1
        for x in range(width):
            alpha = row[(x * bytes_per_pixel) + alpha_offset]
            if alpha == 0:
                continue
            minimum_x = min(minimum_x, x)
            maximum_x = max(maximum_x, x)

        if maximum_x >= minimum_x:
            row_spans.append(maximum_x - minimum_x + 1)
        previous_row = row

    return row_spans
