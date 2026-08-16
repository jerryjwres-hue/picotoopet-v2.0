from __future__ import annotations

import importlib.util
import sys
import zipfile
from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TOOL_ROOT       = (
    REPOSITORY_ROOT
    / "windows"
    / "desktop"
    / "tools"
    / "maotai_v2_assets"
)
RUNNER_PATH     = TOOL_ROOT / "run_maotai_v2_comfyui_jobs.py"
PNG_SIGNATURE   = b"\x89PNG\r\n\x1a\n"


if str(TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOL_ROOT))


def _load_runner(module_name: str):
    """按仓库文件加载 runner，避免测试依赖可编辑安装或全局模块副作用。"""
    spec = importlib.util.spec_from_file_location(module_name, RUNNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _plan(*references: str) -> dict[str, object]:
    """创建只包含主参考图的最小 art-plan fixture。"""
    return {
        "jobs": [
            {
                "target_file": f"fixture-{index}.png",
                "primary_reference": reference,
            }
            for index, reference in enumerate(references, start=1)
        ]
    }


def _png(marker: bytes = b"fixture") -> bytes:
    """ZIP ingest 只校验参考图传输边界，因此 fixture 只需要合法 PNG 签名。"""
    return PNG_SIGNATURE + marker


def _write_zip(path: Path, entries: dict[str, bytes]) -> None:
    """按显式 archive member 写入，便于覆盖嵌套目录、重复 basename 与 traversal。"""
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for member_name, payload in entries.items():
            archive.writestr(member_name, payload)


def test_materialize_reference_zip_writes_only_required_basenames(tmp_path: Path) -> None:
    runner      = _load_runner("run_maotai_v2_reference_zip_happy")
    archive     = tmp_path / "handoff.zip"
    destination = tmp_path / "references"
    _write_zip(
        archive,
        {
            "PicotooPet-Handoff/03_MAOTAI_ART_REFERENCES/03_working_happy.png": _png(b"happy"),
            "PicotooPet-Handoff/03_MAOTAI_ART_REFERENCES/06_idle_paw.png": _png(b"paw"),
            "PicotooPet-Handoff/03_MAOTAI_ART_REFERENCES/unused.png": _png(b"unused"),
            "PicotooPet-Handoff/04_HANDOFF/HANDOFF_PROMPT.txt": b"ignore-me",
        },
    )

    materialized = runner.materialize_reference_zip(
        _plan("03_working_happy.png", "06_idle_paw.png", "03_working_happy.png"),
        archive,
        destination,
    )

    assert materialized == destination
    assert sorted(path.name for path in destination.iterdir()) == [
        "03_working_happy.png",
        "06_idle_paw.png",
    ]
    assert (destination / "03_working_happy.png").read_bytes() == _png(b"happy")
    assert (destination / "06_idle_paw.png").read_bytes() == _png(b"paw")
    assert not (destination / "unused.png").exists()


def test_materialize_reference_zip_preflights_missing_reference_before_any_write(
    tmp_path: Path,
) -> None:
    runner      = _load_runner("run_maotai_v2_reference_zip_missing")
    archive     = tmp_path / "handoff.zip"
    destination = tmp_path / "references"
    destination.mkdir()
    marker = destination / "keep.txt"
    marker.write_text("keep-me", encoding="utf-8")
    _write_zip(
        archive,
        {
            "pkg/03_MAOTAI_ART_REFERENCES/03_working_happy.png": _png(b"happy"),
        },
    )

    with pytest.raises(ValueError, match="06_idle_paw.png"):
        runner.materialize_reference_zip(
            _plan("03_working_happy.png", "06_idle_paw.png"),
            archive,
            destination,
        )

    assert marker.read_text(encoding="utf-8") == "keep-me"
    assert sorted(path.name for path in destination.iterdir()) == ["keep.txt"]


def test_materialize_reference_zip_rejects_duplicate_required_basename(tmp_path: Path) -> None:
    runner      = _load_runner("run_maotai_v2_reference_zip_duplicate")
    archive     = tmp_path / "handoff.zip"
    destination = tmp_path / "references"
    _write_zip(
        archive,
        {
            "a/03_MAOTAI_ART_REFERENCES/03_working_happy.png": _png(b"one"),
            "b/03_MAOTAI_ART_REFERENCES/03_working_happy.png": _png(b"two"),
        },
    )

    with pytest.raises(ValueError, match="duplicate|03_working_happy.png"):
        runner.materialize_reference_zip(
            _plan("03_working_happy.png"),
            archive,
            destination,
        )

    assert not destination.exists() or list(destination.iterdir()) == []


def test_materialize_reference_zip_rejects_invalid_png_before_any_write(tmp_path: Path) -> None:
    runner      = _load_runner("run_maotai_v2_reference_zip_invalid_png")
    archive     = tmp_path / "handoff.zip"
    destination = tmp_path / "references"
    _write_zip(
        archive,
        {
            "pkg/03_MAOTAI_ART_REFERENCES/03_working_happy.png": b"not-a-png",
            "pkg/03_MAOTAI_ART_REFERENCES/06_idle_paw.png": _png(b"paw"),
        },
    )

    with pytest.raises(ValueError, match="PNG|03_working_happy.png"):
        runner.materialize_reference_zip(
            _plan("03_working_happy.png", "06_idle_paw.png"),
            archive,
            destination,
        )

    assert not destination.exists() or list(destination.iterdir()) == []


def test_materialize_reference_zip_rejects_unsafe_archive_paths(tmp_path: Path) -> None:
    runner      = _load_runner("run_maotai_v2_reference_zip_traversal")
    archive     = tmp_path / "handoff.zip"
    destination = tmp_path / "references"
    _write_zip(
        archive,
        {
            "../../03_working_happy.png": _png(b"traversal"),
        },
    )

    with pytest.raises(ValueError, match="unsafe|archive|path"):
        runner.materialize_reference_zip(
            _plan("03_working_happy.png"),
            archive,
            destination,
        )

    assert not destination.exists() or list(destination.iterdir()) == []


def test_materialize_reference_zip_rejects_reference_above_size_limit(tmp_path: Path) -> None:
    runner      = _load_runner("run_maotai_v2_reference_zip_size")
    archive     = tmp_path / "handoff.zip"
    destination = tmp_path / "references"
    _write_zip(
        archive,
        {
            "pkg/03_MAOTAI_ART_REFERENCES/03_working_happy.png": _png(b"0123456789"),
        },
    )

    with pytest.raises(ValueError, match="size|large|limit"):
        runner.materialize_reference_zip(
            _plan("03_working_happy.png"),
            archive,
            destination,
            max_reference_bytes=12,
        )

    assert not destination.exists() or list(destination.iterdir()) == []


def test_reference_source_cli_requires_directory_or_zip_not_both() -> None:
    runner = _load_runner("run_maotai_v2_reference_zip_cli")
    parser = runner._build_parser()

    base_args = [
        "--plan",
        "plan.json",
        "--workflow",
        "workflow.json",
        "--incoming",
        "incoming",
    ]

    directory = parser.parse_args(base_args + ["--reference-dir", "refs"])
    assert directory.reference_dir == Path("refs")
    assert directory.reference_zip is None

    archive = parser.parse_args(base_args + ["--reference-zip", "handoff.zip"])
    assert archive.reference_zip == Path("handoff.zip")
    assert archive.reference_dir is None

    with pytest.raises(SystemExit):
        parser.parse_args(
            base_args
            + [
                "--reference-dir",
                "refs",
                "--reference-zip",
                "handoff.zip",
            ]
        )
