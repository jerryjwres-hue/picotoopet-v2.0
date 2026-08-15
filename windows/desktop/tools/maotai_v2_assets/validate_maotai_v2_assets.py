from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Iterable


_TOOL_DIRECTORY = str(Path(__file__).resolve().parent)
if _TOOL_DIRECTORY not in sys.path:
    sys.path.insert(0, _TOOL_DIRECTORY)

from maotai_manifest_contract import AssetDescriptor, parse_manifest  # noqa: E402
from maotai_png_validation import validate_png_asset                 # noqa: E402


class ValidationReport:
    """可序列化的 fail-closed 校验结果；errors 为空才允许 staging。"""

    __slots__ = ("ok", "errors", "asset_count")

    def __init__(
        self,
        ok: bool,
        errors: Iterable[str],
        asset_count: int,
    ) -> None:
        self.ok          = ok
        self.errors      = tuple(errors)
        self.asset_count = asset_count

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "asset_count": self.asset_count,
            "errors": list(self.errors),
        }


def validate_asset_directory(
    asset_root: Path | str,
    manifest_path: Path | str,
) -> ValidationReport:
    """校验完整独立 PNG 集合；缺失、额外或像素合同失败都会阻止 staging。"""
    root = Path(asset_root)
    try:
        descriptors = parse_manifest(manifest_path)
    except (OSError, ValueError) as error:
        return ValidationReport(False, (f"manifest error: {error}",), 0)

    expected = set(descriptors)
    actual: set[str]  = set()
    errors: list[str] = []

    if not root.is_dir():
        return ValidationReport(False, (f"asset directory missing: {root}",), 0)

    for path in root.iterdir():
        if path.is_file() and path.suffix.lower() == ".png":
            actual.add(path.name)

    for file_name in sorted(expected - actual):
        errors.append(f"missing asset: {file_name}")
    for file_name in sorted(actual - expected):
        errors.append(f"unexpected PNG asset: {file_name}")

    for file_name, descriptor in descriptors.items():
        path = root / file_name
        if path.is_file():
            errors.extend(validate_png_asset(path, descriptor))

    return ValidationReport(not errors, errors, len(actual))


def stage_asset_directory(
    source_root: Path | str,
    destination_root: Path | str,
    manifest_path: Path | str,
) -> ValidationReport:
    """先完整校验 incoming，再原子替换目标 PNG；失败时目标目录保持原样。"""
    source      = Path(source_root)
    destination = Path(destination_root)
    report      = validate_asset_directory(source, manifest_path)
    if not report.ok:
        return report

    descriptors = parse_manifest(manifest_path)
    destination.parent.mkdir(parents=True, exist_ok=True)

    temporary    = Path(tempfile.mkdtemp(prefix=".maotai-v2-stage-", dir=destination.parent))
    backup       = destination.with_name(f".{destination.name}.backup-{os.getpid()}")
    had_existing = destination.exists()

    try:
        if had_existing:
            _copy_non_png_entries(destination, temporary)
        for file_name in descriptors:
            shutil.copy2(source / file_name, temporary / file_name)

        staged_report = validate_asset_directory(temporary, manifest_path)
        if not staged_report.ok:
            return staged_report

        if backup.exists():
            shutil.rmtree(backup)
        if had_existing:
            destination.rename(backup)

        try:
            temporary.rename(destination)
        except Exception:
            if had_existing and backup.exists() and not destination.exists():
                backup.rename(destination)
            raise

        if backup.exists():
            shutil.rmtree(backup)
        return staged_report
    except OSError as error:
        return ValidationReport(False, (f"staging failed: {error}",), report.asset_count)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)
        if backup.exists() and destination.exists():
            shutil.rmtree(backup, ignore_errors=True)


def _copy_non_png_entries(source: Path, destination: Path) -> None:
    """保留 README 等非 PNG 生产说明；旧 PNG 永远不穿透一次新的 staging。"""
    for entry in source.iterdir():
        if entry.is_file() and entry.suffix.lower() == ".png":
            continue

        target = destination / entry.name
        if entry.is_dir():
            shutil.copytree(entry, target)
        elif entry.is_file():
            shutil.copy2(entry, target)


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _default_manifest_path() -> Path:
    return (
        _repository_root()
        / "windows"
        / "desktop"
        / "src"
        / "PicotooPet.Desktop"
        / "Views"
        / "Controls"
        / "MaotaiMotion"
        / "MaotaiAssetManifest.cs"
    )


def _default_asset_root() -> Path:
    return (
        _repository_root()
        / "windows"
        / "desktop"
        / "src"
        / "PicotooPet.Desktop"
        / "Assets"
        / "Maotai"
        / "V2"
    )


def _write_report(report: ValidationReport, report_path: Path | None) -> None:
    payload = json.dumps(report.to_dict(), ensure_ascii=False, indent=2)
    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(payload + "\n", encoding="utf-8")
    print(payload)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate and stage PicotooPet Maotai v2 independent transparent raster parts.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=_default_manifest_path(),
        help="Path to MaotaiAssetManifest.cs (single source of truth).",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Optional JSON report path.",
    )

    commands = parser.add_subparsers(dest="command", required=True)
    check    = commands.add_parser("check", help="Validate assets without modifying files.")
    check.add_argument("asset_root", type=Path, nargs="?", default=_default_asset_root())

    stage = commands.add_parser("stage", help="Validate incoming assets and atomically stage them into V2.")
    stage.add_argument("source_root", type=Path)
    stage.add_argument("--destination", type=Path, default=_default_asset_root())
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "check":
        report = validate_asset_directory(args.asset_root, args.manifest)
    else:
        report = stage_asset_directory(args.source_root, args.destination, args.manifest)

    _write_report(report, args.report)
    return 0 if report.ok else 1


__all__ = [
    "AssetDescriptor",
    "ValidationReport",
    "parse_manifest",
    "stage_asset_directory",
    "validate_asset_directory",
]


if __name__ == "__main__":
    sys.exit(main())
