"""The runtime architecture gate must not freeze one release version."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
STAMPER = ROOT / "scripts" / "stamp_windows_goal_integrity.py"


def test_runtime_goal_gate_does_not_hardcode_product_version() -> None:
    source = STAMPER.read_text(encoding="utf-8")
    runtime_gate = source.split("def _runtime_gate(", 1)[1].split(
        "def _inject_runtime_gate(", 1
    )[0]

    assert '_ps_literal("product_version", product_version)' not in runtime_gate
    assert "product_version: str | None" not in runtime_gate


def test_stamper_still_validates_and_records_canonical_product_version() -> None:
    source = STAMPER.read_text(encoding="utf-8")

    assert "def _product_version(" in source
    assert 'manifest["product_version"] = product_version' in source
    assert 'source_report["product_version"] = product_version' in source
    assert '"product_version": product_version' in source
