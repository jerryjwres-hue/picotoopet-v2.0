"""Canonical user-facing product version loading and validation."""

from __future__ import annotations

import re
from importlib.resources import files

_PRODUCT_VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$")


def parse_product_version(raw: str) -> str:
    """Return a normalized four-part numeric version or fail closed."""

    value = raw.strip()
    if not _PRODUCT_VERSION_PATTERN.fullmatch(value):
        raise ValueError(f"产品版本必须是四段数字：{raw!r}")
    return value


PRODUCT_VERSION = parse_product_version(
    files("picotoopet_core")
    .joinpath("product-version.txt")
    .read_text(encoding="utf-8")
)
