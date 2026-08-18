"""Content discovery must clean crawler evidence before Scout while preserving legacy Gateway output."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from picotoopet_core.autonomous.discovery import ContentDiscoveryCoordinator
from picotoopet_core.autonomous.local_intelligence import (
    LocalAnalysisRequest,
    LocalAnalysisResult,
)
from picotoopet_core.domain.enums import TaskStatus
from picotoopet_core.domain.models import TaskRecord
from picotoopet_core.research.models import ResearchSearchResult


class SequenceSearch:
    def __init__(self, outputs: list[str]) -> None:
        self.outputs = list(outputs)
        self.calls = 0

    def search(self, *, query: str, limit: int, timeout_seconds: int) -> ResearchSearchResult:
        output = self.outputs[self.calls]
        self.calls += 1
        return ResearchSearchResult(query=query, limit=limit, output=output)


class RecordingLocal:
    def __init__(self) -> None:
        self.requests: list[LocalAnalysisRequest] = []

    def analyze(self, request: LocalAnalysisRequest) -> LocalAnalysisResult:
        self.requests.append(request)
        return LocalAnalysisResult(
            role=request.role,
            summary="Scout kept the evidence-grounded candidate.",
            confidence=0.74,
            findings=["one candidate remains after deterministic dedupe"],
            recommended_actions=["retain for later metric validation"],
            evidence_ids=request.evidence_ids,
        )


def _task(*, max_candidates: int = 20) -> TaskRecord:
    now = datetime.now(UTC)
    return TaskRecord(
        task_id="task-radar-integration",
        task_type="autonomous.discovery.v1",
        status=TaskStatus.RUNNING,
        priority=600,
        resource_tag="workflow:wf-radar",
        payload={
            "objective": "find evidence-grounded pet content opportunities",
            "read_only": True,
            "max_candidates": max_candidates,
        },
        attempt_count=1,
        max_attempts=2,
        timeout_seconds=300,
        created_at=now,
        updated_at=now,
    )


def _envelope(*, url: str, title: str, markdown: str) -> str:
    return json.dumps(
        {
            "schema_version": "1.0",
            "query": "pet trend",
            "search_output": "bounded search metadata",
            "documents": [
                {
                    "title": title,
                    "url": url,
                    "source": "example.com",
                    "markdown": markdown,
                    "provider": "crawl4ai",
                    "status_code": 200,
                }
            ],
        },
        ensure_ascii=False,
    )


def test_enriched_crawl_documents_are_normalized_deduped_before_scout() -> None:
    search = SequenceSearch(
        [
            _envelope(
                url="https://Example.com/story?id=7&utm_source=first#comments",
                title="Dog office comedy trend",
                markdown="Dog office comedy short video trend is repeatedly discussed.",
            ),
            _envelope(
                url="https://example.com/story?utm_medium=second&id=7",
                title="Dog office comedy trend",
                markdown="Dog office comedy short video trend is repeatedly discussed.",
            ),
        ]
    )
    local = RecordingLocal()
    coordinator = ContentDiscoveryCoordinator(
        search=search,
        local=local,
        seed_queries=("pet office trend", "pet short video trend"),
    )

    result = coordinator.handler(_task())

    assert len(local.requests) == 1
    scout = local.requests[0]
    assert scout.evidence_ids == ["search-01", "search-02"]
    assert scout.text.count("https://example.com/story?id=7") == 1
    assert "utm_source" not in scout.text
    assert "utm_medium" not in scout.text

    assert result.result_document is not None
    radar = result.result_document["content_radar"]
    assert radar["candidate_count"] == 1
    assert radar["cluster_count"] == 1
    assert radar["candidates"][0]["canonical_url"] == "https://example.com/story?id=7"
    assert radar["candidates"][0]["evidence_ids"] == ["search-01", "search-02"]
    assert radar["clusters"][0]["evidence_ids"] == ["search-01", "search-02"]

    # Web crawl content has no explicit velocity/resonance/business metrics.
    # The deterministic score therefore stays at zero instead of inventing numbers from prose.
    assert radar["scores"][0]["score"]["total"] == 0.0
    assert radar["scores"][0]["score"]["coverage"] == 0.0
    assert radar["scores"][0]["score"]["decision"] == "retain_signal"
    assert radar["research_stop"]["stop"] is False
    assert radar["research_stop"]["next_round"] == 1

    # Raw bounded search evidence stays in the ResultStore document for audit/provenance.
    assert result.result_document["search_count"] == 2
    assert len(result.result_document["search_evidence"]) == 2


def test_legacy_plain_text_gateway_output_remains_supported_without_fake_candidates() -> None:
    search = SequenceSearch(["legacy raw search output with no typed documents"])
    local = RecordingLocal()
    coordinator = ContentDiscoveryCoordinator(
        search=search,
        local=local,
        seed_queries=("legacy source",),
    )

    result = coordinator.handler(_task(max_candidates=5))

    assert len(local.requests) == 1
    assert "legacy raw search output" in local.requests[0].text
    assert local.requests[0].evidence_ids == ["search-01"]
    assert result.result_document is not None
    radar = result.result_document["content_radar"]
    assert radar["candidate_count"] == 0
    assert radar["cluster_count"] == 0
    assert radar["candidates"] == []
    assert radar["clusters"] == []
    assert radar["scores"] == []
    assert radar["research_stop"]["next_round"] == 1
