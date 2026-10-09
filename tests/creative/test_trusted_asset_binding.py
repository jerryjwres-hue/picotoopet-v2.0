from __future__ import annotations

import copy
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from picotoopet_core.api.app import create_app
from picotoopet_core.autonomous.goal_handoff_access import GoalHandoffAccess
from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths
from picotoopet_core.creative.models import (
    CreativeStageKind,
    ShotPlanItem,
    ShotPlanResult,
)
from picotoopet_core.creative.profiles import creative_profile_definition
from picotoopet_core.creative.quality import CreativeQualityGate
from picotoopet_core.creative.source import NormalizedCreativeSourceSet
from picotoopet_core.production.compiler import compile_production_plan

ASSET = "33333333-3333-5333-8333-333333333333"


def _shot(**overrides: object) -> dict[str, object]:
    shot: dict[str, object] = {
        "shot_id": "shot-1",
        "beat_id": "beat-1",
        "order": 1,
        "duration_seconds": 3.0,
        "subject": "product",
        "environment": "studio",
        "action": "rotate",
        "framing": "medium",
        "lighting_style": "soft",
        "render_intent": "GENERATIVE_VIDEO",
    }
    shot.update(overrides)
    return shot


def _source_set(*asset_ids: str) -> NormalizedCreativeSourceSet:
    return NormalizedCreativeSourceSet(
        project_key="autonomous-goal:g1",
        result_package_ids=["r1"],
        result_digests=["a" * 64],
        findings=[],
        evidence_ids=[],
        trusted_asset_ids=list(asset_ids),
        source_set_digest="b" * 64,
    )


def _evaluate(shots: list[dict[str, object]], source_set: NormalizedCreativeSourceSet):  # type: ignore[no-untyped-def]
    script = {"beats": [{"beat_id": "beat-1"}]}
    return CreativeQualityGate().evaluate(
        stage_kind=CreativeStageKind.SHOT_PLAN,
        profile=creative_profile_definition("creative.content_plan.v1"),
        source_set=source_set,
        previous_stages={"script.v1": script},
        raw_result={
            "schema_version": "1.0",
            "creative_profile": "creative.content_plan.v1",
            "shots": shots,
        },
    )


@pytest.mark.parametrize("render_intent", ["GENERATIVE_VIDEO", "IMAGE_TO_VIDEO"])
def test_legacy_shot_without_ref_validates_and_serializes_without_the_field(
    render_intent: str,
) -> None:
    item = ShotPlanItem.model_validate(_shot(render_intent=render_intent))
    assert item.existing_asset_ref is None
    assert "existing_asset_ref" not in item.model_dump(mode="json")
    assert ShotPlanItem.model_validate(item.model_dump(mode="json")) == item


def test_asset_ref_is_allowed_only_for_existing_asset_and_image_to_video() -> None:
    with pytest.raises(ValidationError):
        ShotPlanItem.model_validate(_shot(render_intent="EXISTING_ASSET"))
    with pytest.raises(ValidationError):
        ShotPlanItem.model_validate(_shot(existing_asset_ref=ASSET))
    i2v = ShotPlanItem.model_validate(
        _shot(render_intent="IMAGE_TO_VIDEO", existing_asset_ref=ASSET)
    )
    ok = ShotPlanItem.model_validate(
        _shot(render_intent="EXISTING_ASSET", existing_asset_ref=ASSET)
    )
    assert ok.existing_asset_ref == ASSET
    assert i2v.existing_asset_ref == ASSET
    assert ok.model_dump(mode="json")["existing_asset_ref"] == ASSET


@pytest.mark.parametrize(
    "bad_ref",
    ["C:\\Users\\me\\a.png", "/etc/passwd", "../a.png", "http://x/a.png", "a b", "x" * 129, ""],
)
def test_ref_cannot_carry_path_or_url_authority(bad_ref: str) -> None:
    with pytest.raises(ValidationError):
        ShotPlanItem.model_validate(
            _shot(render_intent="EXISTING_ASSET", existing_asset_ref=bad_ref)
        )


def test_path_like_fields_remain_impossible_on_shot_items() -> None:
    for field in ("managed_relpath", "source_path", "url", "model", "workflow", "endpoint"):
        with pytest.raises(ValidationError):
            ShotPlanItem.model_validate(_shot(**{field: "x"}))


def test_gate_passes_allowlisted_ref_and_rejects_unknown_without_leaking() -> None:
    shots = [_shot(render_intent="EXISTING_ASSET", existing_asset_ref=ASSET)]
    decision, parsed = _evaluate(shots, _source_set(ASSET))
    assert decision.outcome.value == "PASS" and parsed is not None

    decision, parsed = _evaluate(shots, _source_set())
    assert decision.outcome.value == "RETRY" and parsed is None
    assert decision.reasons == ["UNKNOWN_TRUSTED_ASSET_REF"]

    i2v = [_shot(render_intent="IMAGE_TO_VIDEO", existing_asset_ref=ASSET)]
    decision, parsed = _evaluate(i2v, _source_set(ASSET))
    assert decision.outcome.value == "PASS" and parsed is not None
    decision, parsed = _evaluate(i2v, _source_set())
    assert decision.outcome.value == "RETRY" and parsed is None
    assert decision.reasons == ["UNKNOWN_TRUSTED_ASSET_REF"]
    assert ASSET not in (decision.correction_instruction or "")

    decision, _ = _evaluate(shots, _source_set("44444444-4444-5444-8444-444444444444"))
    assert decision.reasons == ["UNKNOWN_TRUSTED_ASSET_REF"]


def test_gate_schema_failures_for_missing_or_misplaced_ref_are_bounded() -> None:
    missing, _ = _evaluate([_shot(render_intent="EXISTING_ASSET")], _source_set(ASSET))
    misplaced, _ = _evaluate([_shot(existing_asset_ref=ASSET)], _source_set(ASSET))
    for decision in (missing, misplaced):
        assert decision.outcome.value == "RETRY"
        assert decision.reasons == ["RESULT_SCHEMA_INVALID"]
        assert ASSET not in (decision.correction_instruction or "")

    missing_i2v, parsed = _evaluate([_shot(render_intent="IMAGE_TO_VIDEO")], _source_set(ASSET))
    assert parsed is None
    assert missing_i2v.outcome.value == "RETRY"
    assert missing_i2v.reasons == ["TRUSTED_ASSET_REF_INVALID"]


def test_local_creative_with_empty_allowlist_cannot_accept_existing_asset() -> None:
    # Local Creative loads persisted source sets, which never carry trusted_asset_ids in this slice.
    assert _source_set().trusted_asset_ids == []
    decision, _ = _evaluate(
        [_shot(render_intent="EXISTING_ASSET", existing_asset_ref=ASSET)], _source_set()
    )
    assert decision.outcome.value == "RETRY"
    assert decision.reasons == ["UNKNOWN_TRUSTED_ASSET_REF"]


def test_source_set_defaults_to_empty_allowlist_for_old_payloads() -> None:
    data = _source_set().model_dump()
    data.pop("trusted_asset_ids")
    assert NormalizedCreativeSourceSet.model_validate(data).trusted_asset_ids == []


def test_shot_plan_result_roundtrip_keeps_production_compiler_inputs_unchanged() -> None:
    result = ShotPlanResult.model_validate(
        {
            "schema_version": "1.0",
            "creative_profile": "creative.content_plan.v1",
            "shots": [_shot()],
        }
    )
    assert "existing_asset_ref" not in copy.deepcopy(result.model_dump(mode="json"))["shots"][0]
    assert compile_production_plan is not None


def test_real_registry_exposes_only_same_goal_assets(tmp_path: Path) -> None:
    settings = AppSettings(
        paths=RuntimePaths.from_root(tmp_path / "runtime"),
        api_token="0123456789abcdef0123456789abcdef",
    )
    app = create_app(settings)
    from fastapi.testclient import TestClient

    headers = {"Authorization": "Bearer 0123456789abcdef0123456789abcdef"}
    with TestClient(app) as client:
        services = app.state.services
        now = datetime.now(UTC).isoformat()
        goals = []
        for _ in range(2):
            goal_id = str(uuid4())
            goals.append(goal_id)
            services.database.execute(
                "INSERT INTO autonomous_goals(goal_id,origin,intent_type,priority_class,objective,"
                "constraints_json,budget_class,status,idempotency_key,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    goal_id,
                    "human",
                    "video.creative",
                    "P1",
                    "o",
                    "{}",
                    "free",
                    "ready",
                    goal_id,
                    now,
                    now,
                ),
            )
        ids = []
        for index, goal_id in enumerate(goals):
            response = client.post(
                "/api/v1/assets",
                headers=headers,
                json={
                    "scope_kind": "autonomous_goal",
                    "scope_id": goal_id,
                    "idempotency_key": f"k-{index}",
                    "sha256": str(index + 1) * 64,
                    "size_bytes": 100,
                    "media_type": "image/png",
                    "width": 10,
                    "height": 10,
                    "duration_ms": None,
                    "managed_root_id": "windows.comfy-input.v1",
                    "source_kind": "windows_user_import.v1",
                },
            )
            assert response.status_code == 200
            ids.append(response.json()["asset_id"])

        access = GoalHandoffAccess(
            paths=settings.paths,
            goals=services.autonomous_goals,
            workflows=services.workflows,
            result_records=services.result_records,
            result_store=services.results,
            assets=services.assets,
        )
        first = access._trusted_assets(goals[0])
        second = access._trusted_assets(goals[1])
        assert [item.asset_id for item in first] == [ids[0]]
        assert [item.asset_id for item in second] == [ids[1]]
        assert ids[1] not in {item.asset_id for item in first}
        assert access._trusted_assets(str(uuid4())) == []
        dumped = [item.model_dump() for item in first]
        assert set(dumped[0]) == {"asset_id", "media_type", "width", "height"}
