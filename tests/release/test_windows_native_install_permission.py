from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILDER = ROOT / "windows" / "desktop" / "scripts" / "Build-Phase2WindowsRelease.ps1"


def test_builder_only_allows_install_after_native_ci_verification() -> None:
    """构建器本身不得生成 native=false、install=true 的危险声明。"""

    source = BUILDER.read_text(encoding="utf-8-sig")

    assert "user_install_allowed = $nativeCiVerified" in source
    assert "user_install_allowed = $true" not in source
