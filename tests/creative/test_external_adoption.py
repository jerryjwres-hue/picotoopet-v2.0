from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from picotoopet_core.config.paths import RuntimePaths
from picotoopet_core.creative.repository import CreativeRepository
from picotoopet_core.creative.service import CreativeIntelligenceService
from picotoopet_core.creative.source import (
    CreativeSourceFinding,
    CreativeSourceNormalizer,
    NormalizedCreativeSourceSet,
)
from picotoopet_core.creative.store import CreativeArtifactStore
from picotoopet_core.db.database import Database
from picotoopet_core.queue.diagnostic_repository import DiagnosticQueueRepository


def _source() -> NormalizedCreativeSourceSet:
    result_id = "11111111-1111-4111-8111-111111111111"
    finding = CreativeSourceFinding(
        source_finding_ref=f"{result_id}:finding:1",
        result_package_id=result_id,
        result_digest="a" * 64,
        work_package_id="22222222-2222-4222-8222-222222222222",
        finding_rank=1,
        finding_digest="b" * 64,
        finding={"rank": 1, "insight": "Drying time matters."},
        evidence_ids=["handoff:evidence:1"],
    )
    return NormalizedCreativeSourceSet(
        project_key="goal:goal-001",
        result_package_ids=[result_id],
        result_digests=[finding.result_digest],
        findings=[finding],
        evidence_ids=["handoff:evidence:1"],
        source_set_digest="c" * 64,
    )


def _stages(source_ref: str) -> dict[str, dict[str, object]]:
    ideas = {
        "schema_version": "1.0",
        "creative_profile": "creative.content_plan.v1",
        "ideas": [
            {
                "idea_id": f"idea-{index:03d}",
                "rank": index,
                "title": f"Idea {index}",
                "audience_problem": "Slow drying",
                "hook": "Dry faster",
                "angle": "time",
                "value_proposition": "save time",
                "format_hint": "short video",
                "confidence": 0.8,
                "source_finding_refs": [source_ref],
                "source_evidence_ids": ["handoff:evidence:1"],
                "claim_risk": "LOW",
                "warnings": [],
            }
            for index in range(1, 4)
        ],
        "needs_deep_ai": False,
        "needs_human": False,
    }
    brief = {
        "schema_version": "1.0",
        "creative_profile": "creative.content_plan.v1",
        "selected_idea_id": "idea-001",
        "target_audience": "dog owners",
        "customer_problem": "slow drying",
        "value_proposition": "save time",
        "primary_hook": "Dry faster",
        "emotional_tone": "practical",
        "content_format": "short video",
        "duration_min_seconds": 10,
        "duration_max_seconds": 20,
        "message_hierarchy": ["problem", "solution"],
        "required_source_finding_refs": [source_ref],
        "required_source_evidence_ids": ["handoff:evidence:1"],
        "prohibited_claims": [],
        "cta_intent": "learn more",
        "continuity_notes": [],
        "needs_deep_ai": False,
        "needs_human": False,
    }
    script = {
        "schema_version": "1.0",
        "creative_profile": "creative.content_plan.v1",
        "script_id": "script-001",
        "title": "Dry faster",
        "target_duration_seconds": 12,
        "beats": [
            {
                "beat_id": "beat-001",
                "order": 1,
                "duration_seconds": 12,
                "voiceover": "Drying time matters.",
                "on_screen_text": None,
                "visual_intent": "A dog being dried",
                "claim_source_evidence_ids": ["handoff:evidence:1"],
                "unsupported_claim": False,
            }
        ],
        "cta_beat_id": "beat-001",
        "warnings": [],
        "needs_deep_ai": False,
        "needs_human": False,
    }
    shot = {
        "schema_version": "1.0",
        "creative_profile": "creative.content_plan.v1",
        "shots": [
            {
                "shot_id": "shot-001",
                "beat_id": "beat-001",
                "order": 1,
                "duration_seconds": 12,
                "subject": "dog",
                "environment": "grooming room",
                "action": "being dried",
                "framing": "medium",
                "lighting_style": "soft",
                "continuity_keys": ["dog"],
                "required_facts": ["drying time matters"],
                "source_evidence_ids": ["handoff:evidence:1"],
                "text_reference": None,
                "production_notes": "renderer-neutral",
                "render_intent": "GENERATIVE_VIDEO",
            }
        ],
        "warnings": [],
        "needs_deep_ai": False,
        "needs_human": False,
    }
    return {
        "idea_ranking.v1": ideas,
        "creative_brief.v1": brief,
        "script.v1": script,
        "shot_plan.v1": shot,
    }


def _fixture(tmp_path: Path) -> tuple[Database, CreativeIntelligenceService, CreativeRepository]:
    paths = RuntimePaths.from_root(tmp_path / "runtime")
    database = Database(paths.database_file)
    database.open()
    database.apply_migrations()
    repository = CreativeRepository(database)
    service = CreativeIntelligenceService(
        repository=repository,
        source_normalizer=CreativeSourceNormalizer(database),
        store=CreativeArtifactStore(paths),
        queue=DiagnosticQueueRepository(database),
    )
    return database, service, repository


def test_external_adoption_uses_quality_gate_and_is_restart_idempotent(tmp_path: Path) -> None:
    database, service, repository = _fixture(tmp_path)
    source = _source()
    provenance = {
        "goal_id": "goal-001",
        "handoff_sha256": "d" * 64,
        "prompt_version": "goal-video-v1",
        "return_sha256": "e" * 64,
        "verified_fact_ids": ["handoff:evidence:1"],
    }
    try:
        first = service.adopt_external(
            source_set=source,
            stage_results=_stages(source.findings[0].source_finding_ref),
            creative_objective="Create a short video.",
            idempotency_key="goal-video:goal-001",
            provenance=provenance,
            completed_at=datetime(2026, 10, 5, tzinfo=UTC),
        )
        second = service.adopt_external(
            source_set=source,
            stage_results=_stages(source.findings[0].source_finding_ref),
            creative_objective="Create a short video.",
            idempotency_key="goal-video:goal-001",
            provenance=provenance,
            completed_at=datetime(2026, 10, 5, tzinfo=UTC),
        )

        assert second.creative_package_id == first.creative_package_id
        assert second.package_digest == first.package_digest
        assert first.manifest["quality_outcome"] == "PASS"
        assert first.manifest["external_provenance"] == provenance
        job = repository.get_job(first.creative_job_id)
        assert job.status.value == "creative_ready"
        stages = database.fetchall(
            "SELECT status,quality_outcome FROM creative_stage_runs WHERE creative_job_id=?",
            (job.creative_job_id,),
        )
        assert len(stages) == 4
        assert {(row["status"], row["quality_outcome"]) for row in stages} == {
            ("Completed", "PASS")
        }
        assert database.fetchone("SELECT COUNT(*) AS count FROM tasks")["count"] == 0
    finally:
        database.close()


def test_external_adoption_rejects_unknown_evidence_before_creating_job(tmp_path: Path) -> None:
    database, service, _repository = _fixture(tmp_path)
    source = _source()
    stages = _stages(source.findings[0].source_finding_ref)
    stages["idea_ranking.v1"]["ideas"][0]["source_evidence_ids"] = ["invented:evidence"]  # type: ignore[index]
    try:
        with pytest.raises(ValueError, match="UNKNOWN_SOURCE_EVIDENCE_ID"):
            service.adopt_external(
                source_set=source,
                stage_results=stages,
                creative_objective="Create a short video.",
                idempotency_key="goal-video:goal-001",
                provenance={"goal_id": "goal-001"},
                completed_at=datetime(2026, 10, 5, tzinfo=UTC),
            )
        assert database.fetchone("SELECT COUNT(*) AS count FROM creative_jobs")["count"] == 0
    finally:
        database.close()
