from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from picotoopet_core.business.repository import BusinessRepository
from picotoopet_core.config.paths import RuntimePaths
from picotoopet_core.creative.execution import CreativeIntelligenceCoordinator
from picotoopet_core.creative.repository import CreativeRepository
from picotoopet_core.creative.service import CreativeIntelligenceService
from picotoopet_core.creative.source import CreativeSourceNormalizer
from picotoopet_core.creative.store import CreativeArtifactStore
from picotoopet_core.db.database import Database
from picotoopet_core.queue.diagnostic_repository import DiagnosticQueueRepository


class FakeCreativeAdapter:
    def __init__(self, responses: list[dict[str, object]]) -> None:
        self.responses = list(responses)
        self.calls = 0

    def run(self, profile, context, *, correction=None):  # type: ignore[no-untyped-def]
        self.calls += 1
        if not self.responses:
            raise AssertionError("unexpected creative model call")
        return self.responses.pop(0)


def _seed_result(database: Database) -> str:
    now = datetime.now(UTC).isoformat()
    work_id = str(uuid4())
    result_id = str(uuid4())
    result = {
        "schema_version": "1.0",
        "analysis_profile": "reviews.voice_of_customer.v1",
        "summary": "Drying time matters.",
        "findings": [
            {"rank": 1, "title": "Drying time", "insight": "Customers mention it.", "confidence": 0.9, "evidence_ids": ["reviews:key:r1"]}
        ],
        "warnings": [],
        "needs_deep_ai": False,
        "needs_human": False,
    }
    database.execute(
        "INSERT INTO business_work_packages(work_package_id,idempotency_key,producer_id,producer_version,project_key,analysis_profile,objective,status,source_digest,compressed_size_bytes,manifest_json,created_at,updated_at,finished_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (work_id, f"worker-{work_id}", "test", "1", "pet-dryer-us", "reviews.voice_of_customer.v1", "x", "Completed", "a" * 64, 1, "{}", now, now, now),
    )
    database.execute(
        "INSERT INTO business_result_packages(result_package_id,work_package_id,analysis_profile,source_digest,preprocess_digest,model_adapter_version,configured_model_id,template_version,quality_outcome,result_digest,package_relpath,result_json,warnings_json,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (result_id, work_id, "reviews.voice_of_customer.v1", "a" * 64, "b" * 64, "loopback-v1", "gpt-oss:20b", "reviews-v1", "PASS", "c" * 64, f"runtime/business/results/{result_id}.zip", json.dumps(result), "[]", now),
    )
    return result_id


def _responses(source_ref: str) -> list[dict[str, object]]:
    ideas = {
        "schema_version": "1.0", "creative_profile": "creative.content_plan.v1",
        "ideas": [
            {"idea_id": f"idea-{i:03d}", "rank": i, "title": f"Idea {i}", "audience_problem": "Slow drying", "hook": "Dry faster", "angle": "time", "value_proposition": "save time", "format_hint": "short video", "confidence": 0.8, "source_finding_refs": [source_ref], "source_evidence_ids": ["reviews:key:r1"], "claim_risk": "LOW", "warnings": []}
            for i in range(1, 4)
        ],
        "needs_deep_ai": False, "needs_human": False,
    }
    brief = {
        "schema_version": "1.0", "creative_profile": "creative.content_plan.v1", "selected_idea_id": "idea-001",
        "target_audience": "large dog owners", "customer_problem": "slow drying", "value_proposition": "save time", "primary_hook": "Dry faster", "emotional_tone": "practical", "content_format": "short video", "duration_min_seconds": 10, "duration_max_seconds": 20, "message_hierarchy": ["problem", "solution"], "required_source_finding_refs": [source_ref], "required_source_evidence_ids": ["reviews:key:r1"], "prohibited_claims": [], "cta_intent": "learn more", "continuity_notes": [], "needs_deep_ai": False, "needs_human": False,
    }
    script = {
        "schema_version": "1.0", "creative_profile": "creative.content_plan.v1", "script_id": "script-001", "title": "Dry faster", "target_duration_seconds": 12,
        "beats": [
            {"beat_id": "beat-001", "order": 1, "duration_seconds": 6, "voiceover": "Bath done.", "on_screen_text": None, "visual_intent": "wet dog", "claim_source_evidence_ids": [], "unsupported_claim": False},
            {"beat_id": "beat-002", "order": 2, "duration_seconds": 6, "voiceover": "Drying time matters.", "on_screen_text": None, "visual_intent": "drying", "claim_source_evidence_ids": ["reviews:key:r1"], "unsupported_claim": False},
        ],
        "cta_beat_id": "beat-002", "warnings": [], "needs_deep_ai": False, "needs_human": False,
    }
    shot = {
        "schema_version": "1.0", "creative_profile": "creative.content_plan.v1",
        "shots": [
            {"shot_id": "shot-001", "beat_id": "beat-001", "order": 1, "duration_seconds": 6, "subject": "wet dog", "environment": "grooming area", "action": "waits", "framing": "medium", "lighting_style": "soft", "continuity_keys": ["dog"], "required_facts": [], "source_evidence_ids": [], "text_reference": None, "production_notes": "renderer-neutral", "render_intent": "GENERATIVE_VIDEO"},
            {"shot_id": "shot-002", "beat_id": "beat-002", "order": 2, "duration_seconds": 6, "subject": "dog drying", "environment": "grooming area", "action": "fur moves", "framing": "close", "lighting_style": "soft", "continuity_keys": ["dog"], "required_facts": ["drying-time relevance"], "source_evidence_ids": ["reviews:key:r1"], "text_reference": None, "production_notes": "renderer-neutral", "render_intent": "GENERATIVE_VIDEO"},
        ],
        "warnings": [], "needs_deep_ai": False, "needs_human": False,
    }
    return [ideas, brief, script, shot]


def _fixture(tmp_path: Path, responses: list[dict[str, object]] | None = None):  # type: ignore[no-untyped-def]
    paths = RuntimePaths.from_root(tmp_path / "runtime")
    database = Database(paths.database_file)
    database.open(); database.apply_migrations()
    result_id = _seed_result(database)
    repository = CreativeRepository(database)
    queue = DiagnosticQueueRepository(database)
    source = CreativeSourceNormalizer(database)
    store = CreativeArtifactStore(paths)
    service = CreativeIntelligenceService(repository=repository, source_normalizer=source, store=store, queue=queue)
    job = service.create_job(source_result_package_ids=[result_id], creative_profile="creative.content_plan.v1", creative_objective="Create a short product education video.", idempotency_key="creative-worker")
    source_set = source.load_persisted_source_set(job.creative_job_id)
    adapter = FakeCreativeAdapter(responses or _responses(source_set.findings[0].source_finding_ref))
    coordinator = CreativeIntelligenceCoordinator(database=database, queue=queue, repository=repository, source_normalizer=source, store=store, adapter=adapter, configured_model_id="gpt-oss:20b")
    task = next(item for item in queue.list(limit=20) if item.resource_tag == f"creative:{job.creative_job_id}")
    return database, service, repository, coordinator, adapter, task, job


def test_creative_worker_completes_four_stages_and_writes_package(tmp_path: Path) -> None:
    database, service, _repository, coordinator, adapter, task, job = _fixture(tmp_path)
    try:
        outcome = coordinator.handler(task)
        final = service.get_job(job.creative_job_id)
        package = service.get_package(job.creative_job_id)
        assert outcome.summary["status"] == "creative_ready"
        assert final.status.value == "creative_ready"
        assert package is not None
        assert adapter.calls == 4
    finally:
        database.close()


def test_second_repairable_stage_failure_stops_at_needs_deep_ai(tmp_path: Path) -> None:
    invalid = {"schema_version": "1.0", "creative_profile": "creative.content_plan.v1", "ideas": []}
    database, service, _repository, coordinator, adapter, task, job = _fixture(tmp_path, [invalid, invalid])
    try:
        outcome = coordinator.handler(task)
        assert outcome.summary["status"] == "NeedsDeepAI"
        assert service.get_job(job.creative_job_id).status.value == "NeedsDeepAI"
        assert adapter.calls == 2
        assert service.get_handoff(job.creative_job_id) is not None
    finally:
        database.close()
