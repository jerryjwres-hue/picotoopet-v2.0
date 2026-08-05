"""The runtime architecture gate must not freeze one release version."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
STAMPER = ROOT / "scripts" / "stamp_windows_goal_integrity.py"
VERIFIER = ROOT / "scripts" / "verify_project_goal_integrity.py"


def test_runtime_goal_gate_does_not_hardcode_product_version() -> None:
    source = STAMPER.read_text(encoding="utf-8")
    runtime_gate = source.split("def _runtime_gate(", 1)[1].split(
        "def _inject_runtime_gate(", 1
    )[0]

    assert '_ps_literal("product_version", product_version)' not in runtime_gate
    assert "product_version: str | None" not in runtime_gate


def test_independent_verifier_does_not_require_version_literal_in_runtime_gate() -> None:
    source = VERIFIER.read_text(encoding="utf-8")
    runtime_gate_check = source.split("def _require_runtime_goal_gates(", 1)[1].split(
        "def verify_windows_package(", 1
    )[0]

    assert '_powershell_literal("product_version", product_version)' not in runtime_gate_check
    assert "product_version: str | None" not in runtime_gate_check


def test_release_integrity_still_validates_and_records_canonical_product_version() -> None:
    stamper = STAMPER.read_text(encoding="utf-8")
    verifier = VERIFIER.read_text(encoding="utf-8")

    assert "def _product_version(" in stamper
    assert 'manifest["product_version"] = product_version' in stamper
    assert 'source_report["product_version"] = product_version' in stamper
    assert '"product_version": product_version' in stamper

    assert "def _product_version(" in verifier
    assert 'manifest.get("product_version")' in verifier
    assert '"product_version": product_version' in verifier
