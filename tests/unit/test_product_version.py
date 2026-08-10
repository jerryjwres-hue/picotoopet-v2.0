"""Canonical user-facing product version regression."""

from __future__ import annotations

from pathlib import Path

import pytest

from picotoopet_core import __version__
from picotoopet_core.versioning import PRODUCT_VERSION, parse_product_version


ROOT = Path(__file__).resolve().parents[2]
VERSION_FILE = ROOT / "src" / "picotoopet_core" / "product-version.txt"


def test_canonical_product_version_is_23181() -> None:
    assert VERSION_FILE.read_text(encoding="utf-8").strip() == "2.3.18.1"
    assert PRODUCT_VERSION == "2.3.18.1"
    assert __version__ == PRODUCT_VERSION


@pytest.mark.parametrize(
    "value",
    ["2.3.13", "2.3.13.1.0", "v2.3.13.1", "2.3.x.1", ""],
)
def test_rejects_non_four_part_product_versions(value: str) -> None:
    with pytest.raises(ValueError, match="四段"):
        parse_product_version(value)
