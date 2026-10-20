"""The video-quality rubric must stay honest about what the existing QA actually proves.

These tests guard the rubric against drift and overclaiming. They do not look at pixels and
they never produce a visual PASS: the rubric itself forbids that for perceptual criteria.
"""

from __future__ import annotations

import importlib
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs" / "p0_video_quality"
RUBRIC = json.loads((DOCS / "quality_rubric.v1.json").read_text(encoding="utf-8"))
QA_CONTRACTS = (
    ROOT / "windows/desktop/src/PicotooPet.Desktop/Services/FinalVideoQaContracts.cs"
)
EVIDENCE_CLASSES = {"MACHINE_OBJECTIVE", "MACHINE_ADVISORY", "HUMAN_PERCEPTUAL"}


def _c011_check_ids() -> list[str]:
    source = QA_CONTRACTS.read_text(encoding="utf-8")
    match = re.search(r"Checks\s*=\s*Array\.AsReadOnly<string>\(\[(.*?)\]\)", source, re.S)
    assert match, "FinalQaIdentity.Checks list not found in C011 contracts"
    return re.findall(r'"([^"]+)"', match.group(1))


def _numbers(value: object) -> list[object]:
    if isinstance(value, bool):
        return []
    if isinstance(value, (int, float)):
        return [value]
    if isinstance(value, dict):
        return [n for item in value.values() for n in _numbers(item)]
    if isinstance(value, list):
        return [n for item in value for n in _numbers(item)]
    return []


def test_verdict_vocabulary_is_closed() -> None:
    assert RUBRIC["verdicts"] == ["ACCEPT", "REVIEW", "REGENERATE", "BLOCKED"]
    for scope in ("shot", "video"):
        rules = " ".join(RUBRIC["decision_rules"][scope])
        for verdict in RUBRIC["verdicts"]:
            assert verdict in rules, f"{scope} rules never mention {verdict}"


def test_rubric_defines_no_numeric_thresholds() -> None:
    # No invented thresholds: calibration needs real labelled media and is out of scope.
    assert RUBRIC["calibration_status"] == "UNCALIBRATED"
    assert _numbers(RUBRIC) == []


def test_only_machine_objective_criteria_may_auto_pass() -> None:
    ids = [item["id"] for item in RUBRIC["criteria"]]
    assert len(ids) == len(set(ids))
    for item in RUBRIC["criteria"]:
        assert item["evidence_class"] in EVIDENCE_CLASSES, item["id"]
        assert item["on_fail"] in RUBRIC["verdicts"], item["id"]
        if item["evidence_class"] != "MACHINE_OBJECTIVE":
            assert item["machine_pass_allowed"] is False, item["id"]
        if item["machine_pass_allowed"]:
            assert item["covered_by"], f"{item['id']} claims machine PASS without coverage"
        if item["evidence_class"] == "MACHINE_ADVISORY":
            # Uncalibrated signals can ask for a look, never order a GPU re-render.
            assert item["on_fail"] == "REVIEW", item["id"]


def test_every_c011_check_is_classified_and_none_is_invented() -> None:
    actual = _c011_check_ids()
    claimed = [
        entry["check"]
        for item in RUBRIC["criteria"]
        for entry in item["covered_by"]
        if entry["layer"] == "c011_qa"
    ]
    unknown = set(claimed) - set(actual)
    assert not unknown, f"rubric cites unknown C011 checks: {unknown}"
    # A new C011 check must be classified in the rubric before anyone relies on it.
    unclassified = set(actual) - set(claimed)
    assert not unclassified, f"unclassified C011 checks: {unclassified}"


def test_c011_checks_cover_only_technical_criteria() -> None:
    perceptual_with_c011 = {
        item["id"]
        for item in RUBRIC["criteria"]
        if item["evidence_class"] == "HUMAN_PERCEPTUAL"
        for entry in item["covered_by"]
        if entry["layer"] == "c011_qa"
    }
    # audio-contract / overlay-provenance are partial technical evidence for human criteria.
    for criterion_id in perceptual_with_c011:
        item = next(c for c in RUBRIC["criteria"] if c["id"] == criterion_id)
        assert item["machine_pass_allowed"] is False
        assert "does_not_prove" in item, criterion_id


@pytest.mark.parametrize(("name", "path"), sorted(RUBRIC["identity"].items()))
def test_identity_fields_exist_in_current_contracts(name: str, path: str) -> None:
    module_name, class_name, field = path.rsplit(".", 2)
    model = getattr(importlib.import_module(module_name), class_name)
    assert field in model.model_fields, f"{name}: {path} no longer exists"


def test_acceptance_doc_mentions_every_criterion() -> None:
    doc = (DOCS / "QUALITY_ACCEPTANCE.md").read_text(encoding="utf-8")
    missing = [item["id"] for item in RUBRIC["criteria"] if item["id"] not in doc]
    assert missing == []
