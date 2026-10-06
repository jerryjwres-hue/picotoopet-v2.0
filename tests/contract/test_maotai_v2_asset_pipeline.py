from __future__ import annotations

import importlib.util
import struct
import zlib
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR_PATH   = (
    REPOSITORY_ROOT
    / "windows"
    / "desktop"
    / "tools"
    / "maotai_v2_assets"
    / "validate_maotai_v2_assets.py"
)


def _load_validator():
    """按仓库路径加载生产工具，避免测试依赖可编辑安装的模块搜索路径。"""
    spec = importlib.util.spec_from_file_location(
        "validate_maotai_v2_assets",
        VALIDATOR_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_manifest(path: Path) -> None:
    """创建最小 C# manifest fixture；生产工具必须从同一语法读取尺寸与文件名。"""
    path.write_text(
        """
internal static class MaotaiAssetManifest
{
    public const string TorsoNeutral = "torso_neutral.png";
    public const string Head         = "head.png";

    public static bool TryGetDescriptor(string fileName, out object descriptor)
    {
        descriptor = fileName switch
        {
            TorsoNeutral => D(TorsoNeutral, 4, 4, 2, 2, 20, 12),
            Head         => D(Head, 5, 4, 2.5, 2, 60, 14),
            _            => default,
        };
        return descriptor is not null;
    }
}
""".strip(),
        encoding="utf-8",
    )


def _write_png(
    path: Path,
    width: int,
    height: int,
    *,
    color_type: int = 6,
    visible_box: tuple[int, int, int, int] = (2, 2, 6, 6),
) -> None:
    """仅用标准库生成 8-bit 非交错 PNG，便于精确构造 alpha 边界 fixture。"""
    if color_type == 6:
        bytes_per_pixel = 4
    elif color_type == 2:
        bytes_per_pixel = 3
    else:
        raise ValueError(f"unsupported fixture color type: {color_type}")

    left, top, right, bottom = visible_box
    rows: list[bytes] = []
    for y in range(height):
        row = bytearray(width * bytes_per_pixel)
        for x in range(width):
            visible = left <= x < right and top <= y < bottom
            offset  = x * bytes_per_pixel
            row[offset]     = 122 if visible else 0
            row[offset + 1] = 91 if visible else 0
            row[offset + 2] = 73 if visible else 0
            if color_type == 6:
                row[offset + 3] = 255 if visible else 0
        rows.append(b"\x00" + bytes(row))

    def chunk(kind: bytes, payload: bytes) -> bytes:
        body = kind + payload
        return (
            struct.pack(">I", len(payload))
            + body
            + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    data = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(b"".join(rows)))
        + chunk(b"IEND", b"")
    )
    path.write_bytes(data)


def _write_valid_asset_set(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    _write_png(root / "torso_neutral.png", 12, 12, visible_box=(2, 2, 10, 10))
    _write_png(root / "head.png", 12, 12, visible_box=(2, 2, 10, 10))


def test_manifest_parser_uses_csharp_manifest_as_the_single_source_of_truth(tmp_path: Path) -> None:
    validator = _load_validator()
    manifest  = tmp_path / "MaotaiAssetManifest.cs"
    _write_manifest(manifest)

    descriptors = validator.parse_manifest(manifest)

    assert list(descriptors) == ["torso_neutral.png", "head.png"]
    assert descriptors["torso_neutral.png"].logical_width == 4.0
    assert descriptors["torso_neutral.png"].logical_height == 4.0
    assert descriptors["head.png"].pivot_x == 2.5
    assert descriptors["head.png"].joint_overlap_pixels == 14.0


def test_validator_accepts_exact_rgba_set_with_density_and_transparent_border(tmp_path: Path) -> None:
    validator = _load_validator()
    manifest  = tmp_path / "MaotaiAssetManifest.cs"
    asset_root = tmp_path / "assets"
    _write_manifest(manifest)
    _write_valid_asset_set(asset_root)

    report = validator.validate_asset_directory(asset_root, manifest)

    assert report.ok
    assert report.errors == ()
    assert report.asset_count == 2


def test_validator_rejects_rgb_missing_and_unexpected_assets(tmp_path: Path) -> None:
    validator  = _load_validator()
    manifest   = tmp_path / "MaotaiAssetManifest.cs"
    asset_root = tmp_path / "assets"
    _write_manifest(manifest)
    asset_root.mkdir()
    _write_png(
        asset_root / "torso_neutral.png",
        12,
        12,
        color_type=2,
        visible_box=(2, 2, 10, 10),
    )
    _write_png(asset_root / "unexpected_full_dog.png", 12, 12)

    report = validator.validate_asset_directory(asset_root, manifest)
    text   = "\n".join(report.errors)

    assert not report.ok
    assert "head.png" in text and "missing" in text.lower()
    assert "unexpected_full_dog.png" in text and "unexpected" in text.lower()
    assert "torso_neutral.png" in text and "alpha" in text.lower()


def test_validator_rejects_visible_pixels_that_touch_the_canvas_border(tmp_path: Path) -> None:
    validator  = _load_validator()
    manifest   = tmp_path / "MaotaiAssetManifest.cs"
    asset_root = tmp_path / "assets"
    _write_manifest(manifest)
    _write_valid_asset_set(asset_root)
    _write_png(
        asset_root / "head.png",
        12,
        12,
        visible_box=(0, 2, 10, 10),
    )

    report = validator.validate_asset_directory(asset_root, manifest)
    text   = "\n".join(report.errors)

    assert not report.ok
    assert "head.png" in text
    assert "border" in text.lower() or "edge" in text.lower()


def test_validator_rejects_assets_below_two_times_logical_density(tmp_path: Path) -> None:
    validator  = _load_validator()
    manifest   = tmp_path / "MaotaiAssetManifest.cs"
    asset_root = tmp_path / "assets"
    _write_manifest(manifest)
    _write_valid_asset_set(asset_root)
    _write_png(
        asset_root / "head.png",
        9,
        9,
        visible_box=(2, 2, 7, 7),
    )

    report = validator.validate_asset_directory(asset_root, manifest)
    text   = "\n".join(report.errors)

    assert not report.ok
    assert "head.png" in text
    assert "2x" in text.lower()


def test_staging_is_fail_closed_and_preserves_destination_on_invalid_source(tmp_path: Path) -> None:
    validator   = _load_validator()
    manifest    = tmp_path / "MaotaiAssetManifest.cs"
    source_root = tmp_path / "incoming"
    destination = tmp_path / "V2"
    _write_manifest(manifest)
    _write_valid_asset_set(source_root)
    destination.mkdir()
    marker = destination / "README.md"
    marker.write_text("keep-me", encoding="utf-8")

    # 故意破坏一个源文件；stage 必须在碰目标目录之前 fail closed。
    _write_png(
        source_root / "head.png",
        9,
        9,
        visible_box=(2, 2, 7, 7),
    )

    report = validator.stage_asset_directory(source_root, destination, manifest)

    assert not report.ok
    assert marker.read_text(encoding="utf-8") == "keep-me"
    assert not (destination / "torso_neutral.png").exists()


def test_staging_replaces_png_set_only_after_full_validation(tmp_path: Path) -> None:
    validator   = _load_validator()
    manifest    = tmp_path / "MaotaiAssetManifest.cs"
    source_root = tmp_path / "incoming"
    destination = tmp_path / "V2"
    _write_manifest(manifest)
    _write_valid_asset_set(source_root)
    destination.mkdir()
    marker = destination / "README.md"
    marker.write_text("keep-me", encoding="utf-8")
    _write_png(destination / "stale.png", 12, 12)

    report = validator.stage_asset_directory(source_root, destination, manifest)

    assert report.ok
    assert marker.read_text(encoding="utf-8") == "keep-me"
    assert sorted(path.name for path in destination.glob("*.png")) == [
        "head.png",
        "torso_neutral.png",
    ]
