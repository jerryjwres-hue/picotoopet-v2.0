from __future__ import annotations

import re
from pathlib import Path


_CONST_PATTERN = re.compile(
    r'public\s+const\s+string\s+(?P<symbol>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*"(?P<file>[^"\\/]+\.png)"\s*;'
)
_DESCRIPTOR_PATTERN = re.compile(
    r'(?P<symbol>[A-Za-z_][A-Za-z0-9_]*)\s*=>\s*D\(\s*(?P=symbol)\s*,\s*'
    r'(?P<width>-?\d+(?:\.\d+)?)\s*,\s*'
    r'(?P<height>-?\d+(?:\.\d+)?)\s*,\s*'
    r'(?P<pivot_x>-?\d+(?:\.\d+)?)\s*,\s*'
    r'(?P<pivot_y>-?\d+(?:\.\d+)?)\s*,\s*'
    r'(?P<z_index>-?\d+)\s*,\s*'
    r'(?P<overlap>-?\d+(?:\.\d+)?)\s*\)'
)


class AssetDescriptor:
    """从 C# MaotaiAssetManifest 读取的独立 Raster Skeleton 部件合同。"""

    __slots__ = (
        "file_name",
        "logical_width",
        "logical_height",
        "pivot_x",
        "pivot_y",
        "z_index",
        "joint_overlap_pixels",
    )

    def __init__(
        self,
        file_name: str,
        logical_width: float,
        logical_height: float,
        pivot_x: float,
        pivot_y: float,
        z_index: int,
        joint_overlap_pixels: float,
    ) -> None:
        self.file_name            = file_name
        self.logical_width        = logical_width
        self.logical_height       = logical_height
        self.pivot_x              = pivot_x
        self.pivot_y              = pivot_y
        self.z_index              = z_index
        self.joint_overlap_pixels = joint_overlap_pixels


def parse_manifest(manifest_path: Path | str) -> dict[str, AssetDescriptor]:
    """解析现有 C# manifest；Python 工具不维护第二份文件名、尺寸或 Pivot 真相源。"""
    path = Path(manifest_path)
    text = path.read_text(encoding="utf-8")

    symbol_to_file: dict[str, str] = {}
    for match in _CONST_PATTERN.finditer(text):
        symbol    = match.group("symbol")
        file_name = match.group("file")
        if symbol in symbol_to_file:
            raise ValueError(f"duplicate manifest symbol: {symbol}")
        if file_name in symbol_to_file.values():
            raise ValueError(f"duplicate manifest file name: {file_name}")
        symbol_to_file[symbol] = file_name

    descriptors: dict[str, AssetDescriptor] = {}
    described_symbols: set[str]             = set()
    for match in _DESCRIPTOR_PATTERN.finditer(text):
        symbol = match.group("symbol")
        if symbol not in symbol_to_file:
            raise ValueError(f"descriptor references unknown manifest symbol: {symbol}")

        descriptor = AssetDescriptor(
            file_name=symbol_to_file[symbol],
            logical_width=float(match.group("width")),
            logical_height=float(match.group("height")),
            pivot_x=float(match.group("pivot_x")),
            pivot_y=float(match.group("pivot_y")),
            z_index=int(match.group("z_index")),
            joint_overlap_pixels=float(match.group("overlap")),
        )
        _validate_descriptor(descriptor)
        descriptors[descriptor.file_name] = descriptor
        described_symbols.add(symbol)

    missing_descriptors = [
        symbol
        for symbol in symbol_to_file
        if symbol not in described_symbols
    ]
    if missing_descriptors:
        joined = ", ".join(missing_descriptors)
        raise ValueError(f"manifest constants without descriptor: {joined}")
    if not descriptors:
        raise ValueError(f"no Maotai v2 PNG descriptors found in {path}")

    return descriptors


def _validate_descriptor(descriptor: AssetDescriptor) -> None:
    if descriptor.logical_width <= 0.0 or descriptor.logical_height <= 0.0:
        raise ValueError(f"invalid logical size: {descriptor.file_name}")
    if not (0.0 <= descriptor.pivot_x <= descriptor.logical_width):
        raise ValueError(f"pivot_x outside asset: {descriptor.file_name}")
    if not (0.0 <= descriptor.pivot_y <= descriptor.logical_height):
        raise ValueError(f"pivot_y outside asset: {descriptor.file_name}")
    if descriptor.joint_overlap_pixels < 12.0:
        raise ValueError(f"joint overlap below 12px: {descriptor.file_name}")
