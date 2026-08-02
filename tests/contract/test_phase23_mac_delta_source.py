"""Phase 2.3 Slice B Mac Core 增量交付源码合同。"""

from __future__ import annotations

from pathlib import Path

from picotoopet_core import __version__

ROOT = Path(__file__).resolve().parents[2]


def test_slice_b_mac_version_identity() -> None:
    """Wheel 版本和运行时健康版本必须明确进入 Slice B。"""

    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'version = "2.3.0.dev1"' in pyproject
    assert __version__ == "2.3.0-slice-b"
