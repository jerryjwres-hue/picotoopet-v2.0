"""Connected Maotai/Browser evidence must feed Goal discovery without fuzzy cross-product mixing."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from picotoopet_core.autonomous.connected_evidence import ConnectedEvidenceRepository
from picotoopet_core.autonomous.discovery import ContentDiscoveryCoordinator
from picotoopet_core.autonomous.local_intelligence import (
    LocalAnalysisResult,
    LocalAnalysisRole,
)
from picotoopet_core.db.database import Database
from picotoopet_core.domain.enums import TaskStatus
from picotoopet_core.domain.models import TaskRecord
from picotoopet_core.research.models import ResearchSearchResult


class FakeSearch:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def search(self, *, query: str, limit: int, timeout_seconds: int) -> ResearchSearchResult:
        self.calls.append(query)
        return ResearchSearchResult(
            query=query,
            limit=limit,
            output="Public search mentions durability and fragment concerns.",
        )


class CapturingLocal:
    def __init__(self) -> None:
        self.requests = []

    def analyze(self, request):  # type: ignore[no-untyped-def]
        self.requests.append(request)
        return LocalAnalysisResult(
            role=LocalAnalysisRole.SCOUT,
            summary="已有评论和公开搜索都指向耐久与尺寸问题。",
            confidence=0.86,
            findings=["手柄尺寸对大型犬用户不友好", "耐久寿命是反复出现的主题"],
            recommended_actions=["先围绕大型犬尺寸适配做内容验证"],
            evidence_ids=request.evidence_ids,
        )


def _task() -> TaskRecord:
    now = datetime.now(UTC)
    return TaskRecord(
        task_id="connected-discovery-task",
        task_type="autonomous.discovery.v1",
        status=TaskStatus.RUNNING,
        priority=100,
        resource_tag="workflow:connected-evidence",
        payload={
            "objective": "研究 Large Dog Chew Toy X9 的消费者痛点并生成内容方向",
            "read_only": True,
            "max_candidates": 12,
        },
        attempt_count=1,
        max_attempts=2,
        timeout_seconds=420,
        created_at=now,
        updated_at=now,
    )


def test_unique_product_match_injects_existing_connected_evidence_before_web_search(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    repository = ConnectedEvidenceRepository(database)
    repository.upsert_product(
        product_key="legacy41:p-1",
        title="Large Dog Chew Toy X9",
        brand="Maotai Test",
        category="dog toy",
        origin="maotai41_import",
        external_ref_type="maotai41.product",
        external_ref_id="p-1",
    )
    repository.put_evidence(
        evidence_id="legacy41-e-1",
        product_key="legacy41:p-1",
        evidence_type="consumer_review",
        source="amazon",
        platform="amazon",
        source_url="https://www.amazon.com/dp/B0TESTX9",
        source_entity_id="review-1",
        text_value="Strong toy, but the handle is too small for my malamute.",
        raw_hash="a" * 64,
        trust_level="B",
        confidence=0.91,
        captured_at="2026-08-17T12:00:00+00:00",
        origin="maotai41_import",
        external_ref_type="maotai41.consumer_signal",
        external_ref_id="review-1",
        idempotency_key="legacy41:test:review-1",
        provenance={"machine_analysis_imported": False},
    )

    search = FakeSearch()
    local = CapturingLocal()
    coordinator = ContentDiscoveryCoordinator(
        search=search,
        local=local,
        seed_queries=("large dog chew toy x9 complaints",),
        connected_evidence=repository,
    )

    result = coordinator.handler(_task())

    assert search.calls == ["large dog chew toy x9 complaints"]
    assert len(local.requests) == 1
    request = local.requests[0]
    assert request.role is LocalAnalysisRole.SCOUT
    assert request.evidence_ids == ["legacy41-e-1", "search-01"]
    assert "Strong toy, but the handle is too small for my malamute." in request.text
    assert "Trust: B" in request.text

    assert result.result_document is not None
    assert result.result_document["connected_evidence_count"] == 1
    assert result.result_document["connected_evidence"][0]["evidence_id"] == "legacy41-e-1"
    assert result.result_document["connected_evidence"][0]["origin"] == "maotai41_import"
    assert result.result_document["evidence_ids"] == ["legacy41-e-1", "search-01"]
    database.close()
