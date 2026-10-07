from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from picotoopet_core.autonomous.goal_handoff_access import GoalHandoffAccess
from picotoopet_core.autonomous.handoff import WebGptHandoffBuilder
from picotoopet_core.autonomous.models import (
    GoalOrigin,
    GoalRecord,
    GoalStatus,
    PriorityClass,
)
from picotoopet_core.autonomous.video_return import (
    GoalVideoReturnError,
    GoalVideoReturnV1,
    validate_goal_video_return,
)
from picotoopet_core.config.paths import RuntimePaths
from picotoopet_core.creative.repository import CreativeRepository
from picotoopet_core.creative.service import CreativeIntelligenceService
from picotoopet_core.creative.source import CreativeSourceNormalizer
from picotoopet_core.creative.store import CreativeArtifactStore
from picotoopet_core.db.database import Database
from picotoopet_core.production.repository import ProductionRepository
from picotoopet_core.production.service import ProductionService
from picotoopet_core.production.store import ProductionArtifactStore
from picotoopet_core.queue.diagnostic_repository import DiagnosticQueueRepository

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


def _goal() -> GoalRecord:
    return GoalRecord(
        goal_id="goal-video-1",
        workflow_id="workflow-1",
        origin=GoalOrigin.HUMAN,
        intent_type="product.research_to_video",
        priority_class=PriorityClass.P1,
        objective="研究产品并生成视频",
        constraints={"read_only_research": True},
        budget_class="local-first",
        pinned=False,
        status=GoalStatus.COMPLETED,
        idempotency_key="human:video-1",
        created_at=NOW,
        updated_at=NOW,
    )


class _Goals:
    def get(self, goal_id: str) -> GoalRecord:
        assert goal_id == "goal-video-1"
        return _goal()


class _Workflows:
    def get_workflow(self, workflow_id: str):  # type: ignore[no-untyped-def]
        assert workflow_id == "workflow-1"
        return SimpleNamespace(
            steps=[
                SimpleNamespace(
                    step_key="web-gpt-handoff",
                    task_id="handoff-task",
                    status="Succeeded",
                )
            ]
        )


class _Records:
    def __init__(self, object_hash: str) -> None:
        self.object_hash = object_hash

    def get_for_task(self, task_id: str):  # type: ignore[no-untyped-def]
        assert task_id == "handoff-task"
        return SimpleNamespace(
            object_hash=self.object_hash,
            result_type="autonomous.goal_handoff.v1",
        )


class _Results:
    def __init__(self, object_hash: str, document: dict[str, object]) -> None:
        self.object_hash = object_hash
        self.document = document

    def read_json(self, object_hash: str, *, max_bytes: int) -> dict[str, object]:
        assert object_hash == self.object_hash
        assert max_bytes <= 128 * 1024
        return dict(self.document)


def _access(tmp_path: Path, assets: object | None = None) -> GoalHandoffAccess:
    paths = RuntimePaths.from_root(tmp_path / "runtime")
    paths.ensure()
    package = WebGptHandoffBuilder(paths, clock=lambda: NOW).build(
        goal=_goal(),
        analysis={"executive_summary": "summary", "validated_facts": []},
        evidence=[
            {"evidence_id": "ev-001", "source_id": "src-001", "text": "fact one"},
            {"evidence_id": "ev-002", "source_id": "src-002", "text": "fact two"},
        ],
        sources=[
            {"source_id": "src-001", "url": "https://example.com/1"},
            {"source_id": "src-002", "url": "https://example.com/2"},
        ],
        creative_brief={"target": "video"},
    )
    package_bytes = package.read_bytes()
    object_hash = "a" * 64
    document: dict[str, object] = {
        "schema_version": "1.0",
        "goal_id": "goal-video-1",
        "handoff_ready": True,
        "package_name": package.name,
        "package_sha256": hashlib.sha256(package_bytes).hexdigest(),
        "package_size_bytes": len(package_bytes),
        "prompt_version": "web-gpt-master-v1.0",
        "manual_web_gpt_upload_required": True,
    }
    return GoalHandoffAccess(
        paths=paths,
        goals=_Goals(),
        workflows=_Workflows(),
        result_records=_Records(object_hash),
        result_store=_Results(object_hash, document),
        assets=assets,  # type: ignore[arg-type]
    )


def _payload(context) -> dict[str, object]:  # type: ignore[no-untyped-def]
    finding = context.source_finding_refs["ev-001"]
    ideas = [
        {
            "idea_id": f"idea-{index}",
            "rank": index,
            "title": f"Idea {index}",
            "audience_problem": "The audience needs a clear product story.",
            "hook": "Show the problem immediately.",
            "angle": "evidence-grounded demonstration",
            "value_proposition": "Explain the product clearly.",
            "format_hint": "short video",
            "confidence": 0.8,
            "source_finding_refs": [finding],
            "source_evidence_ids": ["ev-001"],
            "claim_risk": "LOW",
            "warnings": [],
        }
        for index in range(1, 4)
    ]
    return {
        "schema_version": "1.0",
        "goal_id": "goal-video-1",
        "handoff_sha256": context.package_sha256,
        "prompt_version": "web-gpt-master-v1.0",
        "generated_at": NOW.isoformat(),
        "selected_direction": "idea-1",
        "reasoning_summary": "Evidence supports this direction.",
        "verified_fact_ids": ["ev-001"],
        "inference_summary": "The format may improve comprehension.",
        "creative_summary": "A concise product demonstration.",
        "image_prompt_summary": "Consistent product appearance.",
        "video_prompt_summary": "One continuous product demonstration.",
        "continuity_constraints": ["same product color"],
        "unresolved_questions": [],
        "recommended_next_actions": ["render the validated shot"],
        "idea_ranking": {
            "schema_version": "1.0",
            "creative_profile": "creative.content_plan.v1",
            "ideas": ideas,
            "needs_deep_ai": False,
            "needs_human": False,
        },
        "creative_brief": {
            "schema_version": "1.0",
            "creative_profile": "creative.content_plan.v1",
            "selected_idea_id": "idea-1",
            "target_audience": "product researchers",
            "customer_problem": "The value is difficult to understand.",
            "value_proposition": "A clear evidence-grounded explanation.",
            "primary_hook": "See the problem and solution.",
            "emotional_tone": "clear",
            "content_format": "short video",
            "duration_min_seconds": 5,
            "duration_max_seconds": 10,
            "message_hierarchy": ["problem", "solution"],
            "required_source_finding_refs": [finding],
            "required_source_evidence_ids": ["ev-001"],
            "prohibited_claims": ["unverified performance claims"],
            "cta_intent": "learn more",
            "continuity_notes": ["same product"],
            "needs_deep_ai": False,
            "needs_human": False,
        },
        "script": {
            "schema_version": "1.0",
            "creative_profile": "creative.content_plan.v1",
            "script_id": "script-1",
            "title": "Clear product story",
            "target_duration_seconds": 5,
            "beats": [
                {
                    "beat_id": "beat-1",
                    "order": 1,
                    "duration_seconds": 5,
                    "voiceover": "See the product solve the stated problem.",
                    "on_screen_text": None,
                    "visual_intent": "show the product in use",
                    "claim_source_evidence_ids": ["ev-001"],
                    "unsupported_claim": False,
                }
            ],
            "cta_beat_id": "beat-1",
            "warnings": [],
            "needs_deep_ai": False,
            "needs_human": False,
        },
        "shot_plan": {
            "schema_version": "1.0",
            "creative_profile": "creative.content_plan.v1",
            "shots": [
                {
                    "shot_id": "shot-1",
                    "beat_id": "beat-1",
                    "order": 1,
                    "duration_seconds": 5,
                    "subject": "the product",
                    "environment": "clean studio",
                    "action": "demonstrates the product",
                    "framing": "medium shot",
                    "lighting_style": "soft daylight",
                    "continuity_keys": ["same product color"],
                    "required_facts": ["evidence-grounded product context"],
                    "source_evidence_ids": ["ev-001"],
                    "text_reference": None,
                    "production_notes": "renderer-neutral",
                    "render_intent": "GENERATIVE_VIDEO",
                }
            ],
            "warnings": [],
            "needs_deep_ai": False,
            "needs_human": False,
        },
    }


def test_context_reads_only_verified_manifest_and_derives_stable_finding_refs(
    tmp_path: Path,
) -> None:
    access = _access(tmp_path)

    first = access.context("goal-video-1")
    second = access.context("goal-video-1")

    assert first.evidence_ids == ["ev-001", "ev-002"]
    assert first.source_finding_refs == second.source_finding_refs
    assert first.source_finding_refs["ev-001"].endswith(":finding:1")
    assert first.workflow_id == "workflow-1"
    assert first.handoff_task_id == "handoff-task"


def test_return_prompt_supplies_exact_binding_refs_and_machine_schema(tmp_path: Path) -> None:
    access = _access(tmp_path)
    context = access.context("goal-video-1")

    prompt = access.return_prompt("goal-video-1")

    assert "PICOTOO_RETURN_JSON" in prompt
    assert context.package_sha256 in prompt
    assert context.source_finding_refs["ev-001"] in prompt
    assert '"idea_ranking"' in prompt
    assert '"creative_brief"' in prompt
    assert '"shot_plan"' in prompt


def test_return_contract_forbids_extra_provider_or_renderer_authority(tmp_path: Path) -> None:
    context = _access(tmp_path).context("goal-video-1")
    payload = _payload(context)
    payload["provider"] = "arbitrary-provider"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        GoalVideoReturnV1.model_validate(payload)


def test_return_validation_rejects_stale_binding_unknown_evidence_and_unsafe_values(
    tmp_path: Path,
) -> None:
    context = _access(tmp_path).context("goal-video-1")

    stale = GoalVideoReturnV1.model_validate({**_payload(context), "handoff_sha256": "0" * 64})
    with pytest.raises(GoalVideoReturnError, match="HANDOFF_BINDING_MISMATCH"):
        validate_goal_video_return(stale, context)

    forged_payload = _payload(context)
    forged_payload["verified_fact_ids"] = ["ev-forged"]
    forged = GoalVideoReturnV1.model_validate(forged_payload)
    with pytest.raises(GoalVideoReturnError, match="EVIDENCE_REFERENCE_INVALID"):
        validate_goal_video_return(forged, context)

    unsafe_payload = _payload(context)
    unsafe_payload["creative_summary"] = "Run powershell.exe to prepare the renderer."
    unsafe = GoalVideoReturnV1.model_validate(unsafe_payload)
    with pytest.raises(GoalVideoReturnError, match="FORBIDDEN_AUTHORITY"):
        validate_goal_video_return(unsafe, context)


def test_valid_return_produces_canonical_digest_source_set_and_stage_results(
    tmp_path: Path,
) -> None:
    context = _access(tmp_path).context("goal-video-1")
    payload = GoalVideoReturnV1.model_validate(_payload(context))

    validated = validate_goal_video_return(payload, context)

    assert len(validated.return_digest) == 64
    assert validated.source_set.evidence_ids == ["ev-001", "ev-002"]
    assert validated.source_set.source_set_digest != context.package_sha256
    assert set(validated.stage_results) == {
        "idea_ranking.v1",
        "creative_brief.v1",
        "script.v1",
        "shot_plan.v1",
    }


def _continuation_services(tmp_path: Path):  # type: ignore[no-untyped-def]
    from picotoopet_core.autonomous.video_continuation import GoalVideoContinuationService

    paths = RuntimePaths.from_root(tmp_path / "continuation-runtime")
    database = Database(paths.database_file)
    database.open()
    database.apply_migrations()
    creative_repository = CreativeRepository(database)
    creative = CreativeIntelligenceService(
        repository=creative_repository,
        source_normalizer=CreativeSourceNormalizer(database),
        store=CreativeArtifactStore(paths),
        queue=DiagnosticQueueRepository(database),
    )
    production = ProductionService(
        repository=ProductionRepository(database),
        creative_repository=creative_repository,
        store=ProductionArtifactStore(paths),
    )
    service = GoalVideoContinuationService(
        database=database,
        handoffs=_access(tmp_path),
        creative=creative,
        production=production,
    )
    return database, service, creative, production


def test_valid_goal_return_reaches_existing_production_job_and_replays_idempotently(
    tmp_path: Path,
) -> None:
    database, service, _creative, production = _continuation_services(tmp_path)
    context = _access(tmp_path).context("goal-video-1")
    payload = GoalVideoReturnV1.model_validate(_payload(context))
    try:
        first = service.submit("goal-video-1", payload)
        second = service.submit("goal-video-1", payload)

        assert second == first
        assert first.production_status == "Ready"
        plan = production.get_plan(first.production_job_id)
        assert plan.production_profile == "production.comfyui.v1"
        assert plan.creative_package_digest == first.creative_package_digest
        assert service.status("goal-video-1") == first
    finally:
        database.close()


def test_conflicting_replay_is_rejected_and_restart_reconciles_existing_creative(
    tmp_path: Path,
) -> None:
    from picotoopet_core.autonomous.video_continuation import GoalVideoContinuationService

    database, service, creative, production = _continuation_services(tmp_path)
    context = _access(tmp_path).context("goal-video-1")
    payload = GoalVideoReturnV1.model_validate(_payload(context))
    validated = validate_goal_video_return(payload, context)
    try:
        package = creative.adopt_external(
            source_set=validated.source_set,
            stage_results=validated.stage_results,
            creative_objective=payload.selected_direction,
            idempotency_key="goal-video:goal-video-1",
            provenance={
                "goal_id": payload.goal_id,
                "handoff_sha256": payload.handoff_sha256,
                "prompt_version": payload.prompt_version,
                "return_sha256": validated.return_digest,
                "verified_fact_ids": payload.verified_fact_ids,
                "generated_at": payload.generated_at.isoformat(),
            },
        )
        assert database.scalar("SELECT COUNT(*) FROM production_jobs") == 0

        restarted = GoalVideoContinuationService(
            database=database,
            handoffs=_access(tmp_path),
            creative=creative,
            production=production,
        )
        reconciled = restarted.submit("goal-video-1", payload)
        assert reconciled.creative_package_id == package.creative_package_id
        assert database.scalar("SELECT COUNT(*) FROM production_jobs") == 1

        conflicting_raw = _payload(context)
        conflicting_raw["creative_summary"] = "A different but schema-valid direction."
        with pytest.raises(ValueError, match="idempotency key conflict"):
            service.submit(
                "goal-video-1",
                GoalVideoReturnV1.model_validate(conflicting_raw),
            )
    finally:
        database.close()


ASSET_A = "11111111-1111-5111-8111-111111111111"
ASSET_B = "22222222-2222-5222-8222-222222222222"


class _FakeAssets:
    """Stands in for TrustedAssetService; records the exact scope queried."""

    def __init__(self, *asset_ids: str) -> None:
        self.queries: list[tuple[str, str]] = []
        self._records = [
            SimpleNamespace(
                asset_id=asset_id,
                media_type="image/png",
                width=640,
                height=360,
                sha256=("a" if index == 0 else "b") * 64,
                managed_relpath="PicotooPet/assets/v1/aa/secret-location.png",
            )
            for index, asset_id in enumerate(asset_ids)
        ]

    def list(self, scope_kind: str, scope_id: str, limit: int = 50):  # type: ignore[no-untyped-def]
        self.queries.append((scope_kind, scope_id))
        return self._records


def _asset_shot_payload(context, asset_ref: str | None) -> dict[str, object]:  # type: ignore[no-untyped-def]
    payload = _payload(context)
    shot = payload["shot_plan"]["shots"][0]  # type: ignore[index]
    shot["render_intent"] = "EXISTING_ASSET"
    if asset_ref is not None:
        shot["existing_asset_ref"] = asset_ref
    return payload


def test_context_lists_only_safe_same_goal_assets_and_empty_when_none(tmp_path: Path) -> None:
    empty = _access(tmp_path / "empty").context("goal-video-1")
    assert empty.trusted_assets == []

    fake = _FakeAssets(ASSET_B, ASSET_A)
    context = _access(tmp_path / "with", fake).context("goal-video-1")

    assert fake.queries == [("autonomous_goal", "goal-video-1")]
    assert [item.asset_id for item in context.trusted_assets] == [ASSET_A, ASSET_B]
    assert set(context.trusted_assets[0].model_dump()) == {
        "asset_id",
        "media_type",
        "width",
        "height",
        "sha256",
    }


def test_return_prompt_binds_safe_asset_metadata_without_locations(tmp_path: Path) -> None:
    prompt = _access(tmp_path, _FakeAssets(ASSET_A)).return_prompt("goal-video-1")

    assert ASSET_A in prompt
    assert '"trusted_assets"' in prompt
    assert '"media_type":"image/png"' in prompt
    assert "existing_asset_ref" in prompt
    assert (
        "managed_relpath" not in prompt.split("PicotooPet 严格回导合同")[1].split("JSON Schema")[0]
    )
    assert "secret-location" not in prompt
    assert "PicotooPet/assets" not in prompt

    no_assets = _access(tmp_path / "none").return_prompt("goal-video-1")
    assert '"trusted_assets":[]' in no_assets


def test_source_set_digest_binds_trusted_asset_allowlist(tmp_path: Path) -> None:
    def digest_for(*asset_ids: str) -> tuple[str, list[str]]:
        context = _access(
            tmp_path / "-".join(asset_ids or ("none",)), _FakeAssets(*asset_ids)
        ).context("goal-video-1")
        validated = validate_goal_video_return(
            GoalVideoReturnV1.model_validate(_payload(context)), context
        )
        return validated.source_set.source_set_digest, validated.source_set.trusted_asset_ids

    none_digest, none_ids = digest_for()
    one_digest, one_ids = digest_for(ASSET_A)
    two_digest, two_ids = digest_for(ASSET_A, ASSET_B)

    assert none_ids == [] and one_ids == [ASSET_A] and two_ids == [ASSET_A, ASSET_B]
    assert len({none_digest, one_digest, two_digest}) == 3


def test_external_return_with_allowlisted_asset_passes_and_invented_fails(tmp_path: Path) -> None:
    from picotoopet_core.creative.models import CreativeStageKind
    from picotoopet_core.creative.profiles import creative_profile_definition
    from picotoopet_core.creative.quality import CreativeQualityGate

    context = _access(tmp_path, _FakeAssets(ASSET_A)).context("goal-video-1")
    profile = creative_profile_definition("creative.content_plan.v1")

    def evaluate(asset_ref: str | None, source_set):  # type: ignore[no-untyped-def]
        payload = GoalVideoReturnV1.model_validate(_asset_shot_payload(context, asset_ref))
        validated = validate_goal_video_return(payload, context)
        decision, parsed = CreativeQualityGate().evaluate(
            stage_kind=CreativeStageKind.SHOT_PLAN,
            profile=profile,
            source_set=source_set,
            previous_stages={"script.v1": validated.stage_results["script.v1"]},
            raw_result=validated.stage_results["shot_plan.v1"],
        )
        return decision, parsed, validated

    probe = validate_goal_video_return(GoalVideoReturnV1.model_validate(_payload(context)), context)
    ok, parsed, _ = evaluate(ASSET_A, probe.source_set)
    assert ok.outcome.value == "PASS" and parsed is not None
    assert parsed.shots[0].existing_asset_ref == ASSET_A  # type: ignore[attr-defined]

    invented, _, _ = evaluate(ASSET_B, probe.source_set)
    assert invented.outcome.value == "RETRY"
    assert invented.reasons == ["UNKNOWN_TRUSTED_ASSET_REF"]
    assert ASSET_B not in (invented.correction_instruction or "")


def test_old_return_payload_without_asset_field_still_validates(tmp_path: Path) -> None:
    context = _access(tmp_path).context("goal-video-1")
    payload = GoalVideoReturnV1.model_validate(_payload(context))

    validated = validate_goal_video_return(payload, context)

    assert "existing_asset_ref" not in validated.stage_results["shot_plan.v1"]["shots"][0]  # type: ignore[index]
