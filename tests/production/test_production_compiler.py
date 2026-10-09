from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest

from picotoopet_core.assets.service import NOT_FOUND, TrustedAssetError
from picotoopet_core.production.compiler import compile_production_plan
from picotoopet_core.production.models import (
    ProductionTaskPlan,
    ProductionTrustedAssetSnapshotV1,
)
from picotoopet_core.production.service import ProductionService


def _creative_manifest(
    render_intent: str = "GENERATIVE_VIDEO",
    *,
    duration_seconds: float = 3.0,
    output_profile_id: str | None = "video.landscape.v1",
    script_duration_seconds: float | None = None,
    text_reference: str | None = None,
    on_screen_text: str | None = None,
) -> dict[str, object]:
    brief: dict[str, object] = {
        "schema_version": "1.0",
        "creative_profile": "creative.content_plan.v1",
        "selected_idea_id": "idea-001",
        "target_audience": "pet owners",
        "customer_problem": "slow drying",
        "value_proposition": "save time",
        "primary_hook": "Dry faster",
        "emotional_tone": "practical",
        "content_format": "short video",
        "duration_min_seconds": 3,
        "duration_max_seconds": 20,
        "message_hierarchy": ["problem", "solution"],
        "required_source_finding_refs": ["result:finding:1"],
        "required_source_evidence_ids": ["reviews:key:r1"],
        "prohibited_claims": [],
        "cta_intent": "learn more",
        "continuity_notes": [],
        "needs_deep_ai": False,
        "needs_human": False,
    }
    if output_profile_id is not None:
        brief["output_profile_id"] = output_profile_id
    target = duration_seconds if script_duration_seconds is None else script_duration_seconds
    return {
        "schema_version": "1.0",
        "creative_package_id": str(uuid4()),
        "creative_job_id": str(uuid4()),
        "project_key": "pet-dryer-us",
        "creative_profile": "creative.content_plan.v1",
        "source_set_digest": "a" * 64,
        "quality_outcome": "PASS",
        "stage_results": {
            "creative_brief.v1": brief,
            "script.v1": {
                "schema_version": "1.0",
                "creative_profile": "creative.content_plan.v1",
                "script_id": "script-001",
                "title": "Dry faster",
                "target_duration_seconds": target,
                "beats": [
                    {
                        "beat_id": "beat-001",
                        "order": 1,
                        "duration_seconds": target,
                        "voiceover": "Drying time matters.",
                        "on_screen_text": on_screen_text,
                        "visual_intent": "A compact dryer in use",
                        "claim_source_evidence_ids": ["reviews:key:r1"],
                        "unsupported_claim": False,
                    }
                ],
                "cta_beat_id": "beat-001",
                "warnings": [],
                "needs_deep_ai": False,
                "needs_human": False,
            },
            "shot_plan.v1": {
                "schema_version": "1.0",
                "creative_profile": "creative.content_plan.v1",
                "shots": [
                    {
                        "shot_id": "shot-001",
                        "beat_id": "beat-001",
                        "order": 1,
                        "duration_seconds": duration_seconds,
                        "subject": "compact pet dryer",
                        "environment": "clean home grooming area",
                        "action": "dryer turns while airflow is demonstrated",
                        "framing": "medium product shot",
                        "lighting_style": "soft daylight",
                        "continuity_keys": ["blue body", "same table"],
                        "required_facts": ["portable size"],
                        "source_evidence_ids": ["reviews:key:r1"],
                        "text_reference": text_reference,
                        "production_notes": "renderer-neutral",
                        "render_intent": render_intent,
                    }
                ],
                "warnings": [],
                "needs_deep_ai": False,
                "needs_human": False,
            },
        },
    }


def test_three_second_shot_compiles_to_nearest_compatible_frame_count() -> None:
    plan = compile_production_plan(str(uuid4()), _creative_manifest(), "b" * 64)
    task = plan.tasks[0]

    assert plan.output_profile_id == "video.landscape.v1"
    assert plan.target_runtime_ms == 3000
    assert task.target_duration_ms == 3000
    assert task.execution_disposition == "Executable"
    assert task.execution_backend == "comfy"
    assert task.execution_profile_id == "comfy.wan22.ti2v5b.t2v.v1"
    assert task.local_media is None
    assert task.workflow_id == "comfy.wan22.ti2v5b.t2v.v1"
    assert task.width == 832
    assert task.height == 480
    assert task.fps == 24
    assert task.frame_count == 73
    assert task.frame_count % 4 == 1
    assert abs(task.frame_count / task.fps - 3.0) <= 2 / task.fps


def test_legacy_trusted_local_assets_no_longer_authorize_new_i2v_compile() -> None:
    manifest = _creative_manifest("IMAGE_TO_VIDEO")
    manifest["trusted_local_assets"] = {"shot-001": "ingress/shot-001.png"}

    task = compile_production_plan(str(uuid4()), manifest, "b" * 64).tasks[0]

    assert task.execution_disposition == "NeedsHuman"
    assert task.execution_backend is None
    assert task.execution_profile_id is None
    assert task.workflow_id is None
    assert task.trusted_input_asset_ref is None


@pytest.mark.parametrize(("duration_seconds", "frame_count"), [(0.5, 13), (5.0, 121)])
def test_short_and_normal_supported_durations_remain_executable(
    duration_seconds: float,
    frame_count: int,
) -> None:
    plan = compile_production_plan(
        str(uuid4()),
        _creative_manifest(duration_seconds=duration_seconds),
        "b" * 64,
    )

    assert plan.tasks[0].execution_disposition == "Executable"
    assert plan.tasks[0].frame_count == frame_count


@pytest.mark.parametrize(
    ("profile_id", "width", "height"),
    [
        ("video.landscape.v1", 832, 480),
        ("video.vertical.v1", 480, 832),
        ("video.square.v1", 640, 640),
    ],
)
def test_closed_output_profiles_freeze_every_task(
    profile_id: str,
    width: int,
    height: int,
) -> None:
    manifest = _creative_manifest(output_profile_id=profile_id)
    shot_plan = manifest["stage_results"]["shot_plan.v1"]  # type: ignore[index]
    second = deepcopy(shot_plan["shots"][0])  # type: ignore[index]
    second["shot_id"] = "shot-002"
    second["beat_id"] = "beat-002"
    second["order"] = 2
    shot_plan["shots"].append(second)  # type: ignore[index]
    script = manifest["stage_results"]["script.v1"]  # type: ignore[index]
    script["beats"].append(  # type: ignore[index]
        {
            "beat_id": "beat-002",
            "order": 2,
            "duration_seconds": 3,
            "voiceover": None,
            "on_screen_text": None,
            "visual_intent": "Second shot",
            "claim_source_evidence_ids": [],
            "unsupported_claim": False,
        }
    )
    script["target_duration_seconds"] = 6  # type: ignore[index]

    plan = compile_production_plan(str(uuid4()), manifest, "b" * 64)

    assert plan.output_profile_id == profile_id
    assert plan.target_runtime_ms == 6000
    assert {(task.width, task.height, task.fps) for task in plan.tasks} == {(width, height, 24)}


def test_legacy_brief_without_profile_defaults_to_landscape() -> None:
    plan = compile_production_plan(
        str(uuid4()),
        _creative_manifest(output_profile_id=None),
        "b" * 64,
    )

    assert plan.output_profile_id == "video.landscape.v1"
    assert (plan.tasks[0].width, plan.tasks[0].height, plan.tasks[0].fps) == (832, 480, 24)


def test_unknown_profile_and_raw_renderer_authority_are_rejected() -> None:
    unknown = _creative_manifest(output_profile_id="video.custom.v1")
    with pytest.raises(ValueError, match="PRODUCTION_CREATIVE_BRIEF_INVALID"):
        compile_production_plan(str(uuid4()), unknown, "b" * 64)

    injected = _creative_manifest()
    injected["stage_results"]["creative_brief.v1"]["width"] = 1920  # type: ignore[index]
    injected["stage_results"]["creative_brief.v1"]["fps"] = 60  # type: ignore[index]
    with pytest.raises(ValueError, match="PRODUCTION_CREATIVE_BRIEF_INVALID"):
        compile_production_plan(str(uuid4()), injected, "b" * 64)


def test_over_limit_duration_fails_closed_without_executable_truncation() -> None:
    plan = compile_production_plan(
        str(uuid4()),
        _creative_manifest(duration_seconds=6.0),
        "b" * 64,
    )
    task = plan.tasks[0]

    assert task.target_duration_ms == 6000
    assert task.execution_disposition == "NeedsHuman"
    assert task.workflow_id is None


def test_script_and_shot_timeline_mismatch_beyond_existing_tolerance_is_rejected() -> None:
    with pytest.raises(ValueError, match="PRODUCTION_TIMELINE_MISMATCH"):
        compile_production_plan(
            str(uuid4()),
            _creative_manifest(duration_seconds=3.0, script_duration_seconds=9.0),
            "b" * 64,
        )


def test_identical_inputs_produce_identical_complete_plan() -> None:
    job_id = str(uuid4())
    manifest = _creative_manifest(output_profile_id="video.vertical.v1")

    first = compile_production_plan(job_id, manifest, "b" * 64)
    second = compile_production_plan(job_id, manifest, "b" * 64)

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.tasks[0].seed == second.tasks[0].seed
    first_digest = hashlib.sha256(
        json.dumps(
            first.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    second_digest = hashlib.sha256(
        json.dumps(
            second.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    assert first_digest == second_digest


def test_text_card_prefers_shot_text_and_freezes_local_media_payload() -> None:
    plan = compile_production_plan(
        str(uuid4()),
        _creative_manifest(
            "TEXT_CARD",
            text_reference="  Save time with gentle airflow.  ",
            on_screen_text="Fallback text",
            output_profile_id="video.vertical.v1",
        ),
        "b" * 64,
    )
    task = plan.tasks[0]

    assert task.execution_disposition == "Executable"
    assert task.execution_backend == "local_media"
    assert task.execution_profile_id == "production.local.text-card.v1"
    assert task.workflow_id is None
    assert task.local_media is not None
    assert task.local_media.text_content == "Save time with gentle airflow."
    assert task.local_media.text_profile_id == "production.local.text-card.v1"
    assert (
        task.local_media.text_digest
        == hashlib.sha256(b"Save time with gentle airflow.").hexdigest()
    )
    assert (task.width, task.height, task.fps, task.frame_count) == (480, 832, 24, 73)


def test_text_card_falls_back_to_matching_script_beat_text() -> None:
    plan = compile_production_plan(
        str(uuid4()),
        _creative_manifest("TEXT_CARD", on_screen_text="A trusted script caption"),
        "b" * 64,
    )

    assert plan.tasks[0].local_media is not None
    assert plan.tasks[0].local_media.text_content == "A trusted script caption"


def test_text_card_ignores_blank_shot_text_before_script_fallback() -> None:
    plan = compile_production_plan(
        str(uuid4()),
        _creative_manifest(
            "TEXT_CARD",
            text_reference="   ",
            on_screen_text="A trusted script caption",
        ),
        "b" * 64,
    )

    assert plan.tasks[0].local_media is not None
    assert plan.tasks[0].local_media.text_content == "A trusted script caption"


def test_text_card_without_valid_text_fails_closed_to_needs_human() -> None:
    plan = compile_production_plan(
        str(uuid4()),
        _creative_manifest("TEXT_CARD", text_reference="   ", on_screen_text=None),
        "b" * 64,
    )
    task = plan.tasks[0]

    assert task.execution_disposition == "NeedsHuman"
    assert task.execution_backend is None
    assert task.execution_profile_id is None
    assert task.workflow_id is None
    assert task.local_media is None


@pytest.mark.parametrize(
    "render_intent",
    ["GENERATIVE_IMAGE", "PRODUCT_ASSET_COMPOSITE"],
)
def test_c006a_excluded_render_intents_remain_needs_human(render_intent: str) -> None:
    plan = compile_production_plan(
        str(uuid4()),
        _creative_manifest(render_intent),
        "b" * 64,
    )

    assert plan.tasks[0].execution_disposition == "NeedsHuman"
    assert plan.tasks[0].execution_backend is None
    assert plan.tasks[0].execution_profile_id is None


def test_existing_asset_with_required_ref_remains_needs_human_when_duration_unsupported() -> None:
    manifest = _creative_manifest("EXISTING_ASSET", duration_seconds=6.0)
    shot_plan = manifest["stage_results"]["shot_plan.v1"]  # type: ignore[index]
    shot_plan["shots"][0]["existing_asset_ref"] = str(uuid4())  # type: ignore[index]

    task = compile_production_plan(str(uuid4()), manifest, "b" * 64).tasks[0]

    assert task.execution_disposition == "NeedsHuman"
    assert task.execution_backend is None
    assert task.execution_profile_id is None


def _existing_asset_case() -> tuple[dict[str, object], ProductionTrustedAssetSnapshotV1]:
    asset_id = str(uuid4())
    manifest = _creative_manifest("EXISTING_ASSET")
    manifest["project_key"] = "autonomous-goal:goal-001"
    shot_plan = manifest["stage_results"]["shot_plan.v1"]  # type: ignore[index]
    shot_plan["shots"][0]["existing_asset_ref"] = asset_id  # type: ignore[index]
    snapshot = ProductionTrustedAssetSnapshotV1(
        asset_id=asset_id,
        scope_kind="autonomous_goal",
        scope_id="goal-001",
        managed_root_id="windows.comfy-input.v1",
        managed_relpath=f"PicotooPet/assets/v1/aa/{'a' * 64}.png",
        sha256="a" * 64,
        size_bytes=321,
        media_type="image/png",
        width=1200,
        height=800,
    )
    return manifest, snapshot


def test_existing_asset_compiles_from_closed_frozen_snapshot() -> None:
    manifest, snapshot = _existing_asset_case()

    task = compile_production_plan(
        str(uuid4()), manifest, "b" * 64, trusted_assets={snapshot.asset_id: snapshot}
    ).tasks[0]

    assert task.execution_disposition == "Executable"
    assert task.execution_backend == "local_media"
    assert task.execution_profile_id == "production.local.existing-image.v1"
    assert task.workflow_id is None
    assert task.local_media is None
    assert task.trusted_asset == snapshot
    assert task.trusted_input_asset_ref is None


def test_image_to_video_compiles_with_same_closed_frozen_snapshot() -> None:
    manifest, snapshot = _existing_asset_case()
    shot = manifest["stage_results"]["shot_plan.v1"]["shots"][0]  # type: ignore[index]
    shot["render_intent"] = "IMAGE_TO_VIDEO"  # type: ignore[index]
    manifest["trusted_local_assets"] = {"shot-001": "../../legacy-ignored.png"}

    task = compile_production_plan(
        str(uuid4()), manifest, "b" * 64, trusted_assets={snapshot.asset_id: snapshot}
    ).tasks[0]

    assert task.execution_disposition == "Executable"
    assert task.execution_backend == "comfy"
    assert task.execution_profile_id == "comfy.wan22.ti2v5b.i2v.v1"
    assert task.workflow_id == "comfy.wan22.ti2v5b.i2v.v1"
    assert task.trusted_asset == snapshot
    assert task.trusted_input_asset_ref is None
    assert task.local_media is None


def test_legacy_frozen_i2v_plan_stays_loadable_but_t2v_cannot_carry_snapshot() -> None:
    manifest, snapshot = _existing_asset_case()
    ordinary = compile_production_plan(str(uuid4()), _creative_manifest(), "b" * 64).tasks[0]
    legacy = ordinary.model_dump(mode="json")
    legacy.update(
        render_intent="IMAGE_TO_VIDEO",
        execution_profile_id="comfy.wan22.ti2v5b.i2v.v1",
        workflow_id="comfy.wan22.ti2v5b.i2v.v1",
        trusted_input_asset_ref="PicotooPet/assets/legacy.png",
    )
    assert ProductionTaskPlan.model_validate(legacy).trusted_asset is None

    t2v_with_asset = ordinary.model_dump(mode="json")
    t2v_with_asset["trusted_asset"] = snapshot.model_dump(mode="json")
    with pytest.raises(ValueError, match="trusted asset"):
        ProductionTaskPlan.model_validate(t2v_with_asset)


def test_existing_asset_missing_snapshot_fails_closed() -> None:
    manifest, _snapshot = _existing_asset_case()

    with pytest.raises(ValueError, match="PRODUCTION_TRUSTED_ASSET_NOT_FOUND"):
        compile_production_plan(str(uuid4()), manifest, "b" * 64, trusted_assets={})


def test_trusted_snapshot_changes_plan_digest_material() -> None:
    manifest, snapshot = _existing_asset_case()
    job_id = str(uuid4())
    first = compile_production_plan(
        job_id, manifest, "b" * 64, trusted_assets={snapshot.asset_id: snapshot}
    )
    changed = snapshot.model_copy(update={"size_bytes": snapshot.size_bytes + 1})
    second = compile_production_plan(
        job_id, manifest, "b" * 64, trusted_assets={changed.asset_id: changed}
    )

    assert first.model_dump(mode="json") != second.model_dump(mode="json")


def test_trusted_snapshot_rejects_wrong_root_mime_duration_and_scope() -> None:
    manifest, snapshot = _existing_asset_case()
    payload = snapshot.model_dump(mode="json")
    for update in (
        {"managed_root_id": "caller.root"},
        {"media_type": "image/gif"},
        {"duration_ms": 3000},
    ):
        with pytest.raises(ValueError):
            ProductionTrustedAssetSnapshotV1.model_validate(payload | update)

    cross_goal = snapshot.model_copy(update={"scope_id": "goal-002"})
    with pytest.raises(ValueError, match="PRODUCTION_TRUSTED_ASSET_SCOPE_INVALID"):
        compile_production_plan(
            str(uuid4()),
            manifest,
            "b" * 64,
            trusted_assets={cross_goal.asset_id: cross_goal},
        )


def test_non_existing_asset_cannot_carry_trusted_snapshot_and_old_plan_stays_loadable() -> None:
    _manifest, snapshot = _existing_asset_case()
    ordinary = compile_production_plan(str(uuid4()), _creative_manifest(), "b" * 64).tasks[0]
    payload = ordinary.model_dump(mode="json")
    assert ProductionTaskPlan.model_validate(payload) == ordinary

    payload["trusted_asset"] = snapshot.model_dump(mode="json")
    with pytest.raises(ValueError, match="trusted asset"):
        ProductionTaskPlan.model_validate(payload)


def test_service_resolves_existing_asset_only_through_exact_goal_scope() -> None:
    manifest, snapshot = _existing_asset_case()
    calls: list[tuple[str, str | None, str | None]] = []

    class Assets:
        def get(self, asset_id: str, *, scope_kind: str | None = None, scope_id: str | None = None):
            calls.append((asset_id, scope_kind, scope_id))
            return SimpleNamespace(**snapshot.model_dump(mode="python"), duration_ms=None)

    service = ProductionService(
        repository=None,  # type: ignore[arg-type]
        creative_repository=None,  # type: ignore[arg-type]
        store=None,  # type: ignore[arg-type]
        trusted_assets=Assets(),  # type: ignore[arg-type]
    )

    resolved = service._resolve_trusted_assets(manifest, "autonomous-goal:goal-001")

    assert resolved == {snapshot.asset_id: snapshot}
    assert calls == [(snapshot.asset_id, "autonomous_goal", "goal-001")]


def test_service_hides_unknown_and_cross_goal_assets_behind_bounded_failure() -> None:
    manifest, _snapshot = _existing_asset_case()

    class MissingAssets:
        def get(self, asset_id: str, *, scope_kind: str | None = None, scope_id: str | None = None):
            raise TrustedAssetError(NOT_FOUND)

    service = ProductionService(
        repository=None,  # type: ignore[arg-type]
        creative_repository=None,  # type: ignore[arg-type]
        store=None,  # type: ignore[arg-type]
        trusted_assets=MissingAssets(),  # type: ignore[arg-type]
    )

    with pytest.raises(ValueError, match="^PRODUCTION_TRUSTED_ASSET_NOT_FOUND$"):
        service._resolve_trusted_assets(manifest, "autonomous-goal:goal-001")
    with pytest.raises(ValueError, match="^PRODUCTION_TRUSTED_ASSET_SCOPE_INVALID$"):
        service._resolve_trusted_assets(manifest, "project-001")


def test_service_resolves_i2v_ref_through_same_goal_scoped_registry() -> None:
    manifest, snapshot = _existing_asset_case()
    shot = manifest["stage_results"]["shot_plan.v1"]["shots"][0]  # type: ignore[index]
    shot["render_intent"] = "IMAGE_TO_VIDEO"  # type: ignore[index]

    class Assets:
        def get(self, asset_id: str, *, scope_kind: str | None = None, scope_id: str | None = None):
            assert (asset_id, scope_kind, scope_id) == (
                snapshot.asset_id,
                "autonomous_goal",
                "goal-001",
            )
            return SimpleNamespace(**snapshot.model_dump(mode="python"), duration_ms=None)

    service = ProductionService(
        repository=None,  # type: ignore[arg-type]
        creative_repository=None,  # type: ignore[arg-type]
        store=None,  # type: ignore[arg-type]
        trusted_assets=Assets(),  # type: ignore[arg-type]
    )

    assert service._resolve_trusted_assets(manifest, "autonomous-goal:goal-001") == {
        snapshot.asset_id: snapshot
    }
