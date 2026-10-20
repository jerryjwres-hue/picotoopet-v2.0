"""Shared loaders for the Video Bible contract tests (synthetic fixtures only)."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from video_bible_reference import BibleReport, VideoBible, lint_bible

GOLDEN = Path(__file__).resolve().parent / "golden"
FIXTURE_IDS = sorted(path.stem for path in GOLDEN.glob("*.json"))


def load(fixture_id: str) -> dict[str, Any]:
    return json.loads((GOLDEN / f"{fixture_id}.json").read_text(encoding="utf-8"))


def stages(fixture: dict[str, Any]) -> dict[str, Any]:
    return fixture["creative_package_manifest"]["stage_results"]


def run_lint(
    fixture: dict[str, Any],
    *,
    bible: VideoBible | None = None,
    brief: dict[str, Any] | None = None,
    script: dict[str, Any] | None = None,
    shot_plan: dict[str, Any] | None = None,
    evidence_ids: set[str] | None = None,
    trusted_assets: dict[str, str] | None = None,
) -> BibleReport:
    parts = stages(fixture)
    return lint_bible(
        bible or VideoBible.model_validate(fixture["video_bible"]),
        brief=brief or parts["creative_brief.v1"],
        script=script or parts["script.v1"],
        shot_plan=shot_plan or parts["shot_plan.v1"],
        evidence_ids=evidence_ids if evidence_ids is not None else set(fixture["source_evidence"]),
        source_set_digest=fixture["creative_package_manifest"]["source_set_digest"],
        trusted_assets=trusted_assets,
    )


def mutated(fixture: dict[str, Any]) -> dict[str, Any]:
    return deepcopy(fixture)


def rebuild(raw_bible: dict[str, Any]) -> VideoBible:
    """Re-validate a mutated bible and reseal so only the lint rule under test can fire."""

    raw = dict(raw_bible)
    raw["bible_digest"] = None
    return VideoBible.model_validate(raw).sealed()
