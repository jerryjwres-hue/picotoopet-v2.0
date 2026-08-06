"""Independent release integrity must bind the canonical product version end to end."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "contracts" / "release" / "project-goal-invariants.json"
STAMPER = ROOT / "scripts" / "stamp_windows_goal_integrity.py"
VERIFIER = ROOT / "scripts" / "verify_project_goal_integrity.py"


def test_goal_contract_names_canonical_product_version_source_and_payload() -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    version = contract["windows"]["product_version"]

    assert version == {
        "value": "2.3.12.4",
        "source_path": "src/picotoopet_core/product-version.txt",
        "payload_path": "product-version.txt",
    }


def test_stamper_rejects_product_version_drift_and_records_it() -> None:
    source = STAMPER.read_text(encoding="utf-8")
    for required in (
        "def _product_version(",
        'product_contract.get("source_path")',
        'product_contract.get("payload_path")',
        'manifest.get("product_version")',
        'source_report["product_version"]',
        '"product_version": product_version',
        'manifest["product_version"] = product_version',
    ):
        assert required in source


def test_independent_verifier_recomputes_product_version_from_zip_payload() -> None:
    source = VERIFIER.read_text(encoding="utf-8")
    for required in (
        "def _product_version(",
        'product_contract.get("payload_path")',
        'manifest.get("product_version")',
        "package_path.name",
        "archive.read(member)",
        '"product_version": product_version',
    ):
        assert required in source
