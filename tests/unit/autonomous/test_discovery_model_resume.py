"""A local-model timeout must resume Scout without repeating completed read-only research."""

from __future__ import annotations

from datetime import UTC, datetime

from picotoopet_core.autonomous.discovery import ContentDiscoveryCoordinator
from picotoopet_core.autonomous.local_intelligence import (
    LocalAnalysisRequest,
    LocalAnalysisResult,
    LocalIntelligenceError,
)
from picotoopet_core.domain.enums import TaskStatus
from picotoopet_core.domain.models import TaskRecord
from picotoopet_core.research.models import ResearchSearchResult


class _RecordingSearch:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def search(self, *, query: str, limit: int, timeout_seconds: int) -> ResearchSearchResult:
        del timeout_seconds
        self.calls.append(query)
        return ResearchSearchResult(
            query=query,
            limit=limit,
            output=f'{{"documents":[{{"title":"{query}","url":"https://example.test/{len(self.calls)}"}}]}}',
        )


class _TimeoutThenSuccessLocal:
    def __init__(self) -> None:
        self.requests: list[LocalAnalysisRequest] = []

    def analyze(self, request: LocalAnalysisRequest) -> LocalAnalysisResult:
        self.requests.append(request)
        if len(self.requests) == 1:
            raise LocalIntelligenceError("MODEL_RUNNER_TIMEOUT")
        return LocalAnalysisResult(
            role=request.role,
            summary="Scout resumed from completed research evidence.",
            confidence=0.8,
            findings=["bounded finding"],
            recommended_actions=["bounded action"],
            evidence_ids=request.evidence_ids,
        )


def _task() -> TaskRecord:
    now = datetime.now(UTC)
    return TaskRecord(
        task_id="task-resume",
        task_type="autonomous.discovery.v1",
        status=TaskStatus.RUNNING,
        priority=600,
        resource_tag="workflow:wf-resume",
        payload={"objective": "find durable research evidence", "read_only": True},
        attempt_count=1,
        max_attempts=2,
        timeout_seconds=900,
        created_at=now,
        updated_at=now,
    )


def test_model_timeout_retries_only_scout_without_repeating_research() -> None:
    search = _RecordingSearch()
    local = _TimeoutThenSuccessLocal()
    queries = ("q1", "q2", "q3", "q4")
    coordinator = ContentDiscoveryCoordinator(
        search=search,
        local=local,
        seed_queries=queries,
    )

    result = coordinator.handler(_task())

    assert search.calls == list(queries)
    assert len(local.requests) == 2
    assert local.requests[0].text == local.requests[1].text
    assert result.result_document is not None
    assert result.result_document["search_count"] == 4
    assert result.result_document["summary"] == "Scout resumed from completed research evidence."
