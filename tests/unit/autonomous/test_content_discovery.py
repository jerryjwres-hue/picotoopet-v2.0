"""Autonomous discovery must gather tool evidence before local-model screening."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from picotoopet_core.autonomous.discovery import (
    ContentDiscoveryCoordinator,
    ContentDiscoveryError,
    ContentDiscoveryRequest,
)
from picotoopet_core.autonomous.local_intelligence import (
    LocalAnalysisRequest,
    LocalAnalysisResult,
    LocalAnalysisRole,
)
from picotoopet_core.domain.enums import TaskStatus
from picotoopet_core.domain.models import TaskRecord
from picotoopet_core.research.execution import ResearchGatewayExecutionError
from picotoopet_core.research.models import ResearchSearchResult


class FakeSearch:
    def __init__(self, *, fail_queries: set[str] | None = None) -> None:
        self.fail_queries = fail_queries or set()
        self.calls: list[tuple[str, int, int]] = []

    def search(self, *, query: str, limit: int, timeout_seconds: int) -> ResearchSearchResult:
        self.calls.append((query, limit, timeout_seconds))
        if query in self.fail_queries:
            raise ResearchGatewayExecutionError("simulated search failure")
        return ResearchSearchResult(
            query=query,
            limit=limit,
            output=f'{{"query":"{query}","documents":[{{"title":"hit","url":"https://example.com/{len(self.calls)}"}}]}}',
        )


class FakeLocal:
    def __init__(self) -> None:
        self.requests: list[LocalAnalysisRequest] = []

    def analyze(self, request: LocalAnalysisRequest) -> LocalAnalysisResult:
        self.requests.append(request)
        return LocalAnalysisResult(
            role=request.role,
            summary="发现两个值得继续低成本验证的主题。",
            confidence=0.81,
            findings=["宠物拟人办公内容重复出现", "AI 视频工作流内容讨论增长"],
            recommended_actions=["继续验证宠物拟人办公", "继续验证 AI 视频工作流"],
            evidence_ids=request.evidence_ids,
        )


def _task(payload: dict[str, object]) -> TaskRecord:
    now = datetime.now(UTC)
    return TaskRecord(
        task_id="task-discovery",
        task_type="autonomous.discovery.v1",
        status=TaskStatus.RUNNING,
        priority=600,
        resource_tag="workflow:wf-discovery",
        payload=payload,
        attempt_count=1,
        max_attempts=2,
        timeout_seconds=900,
        created_at=now,
        updated_at=now,
    )


def test_request_is_read_only_and_bounded() -> None:
    request = ContentDiscoveryRequest(
        objective="发现值得继续研究的内容主题",
        read_only=True,
        max_candidates=20,
    )
    assert request.read_only is True

    with pytest.raises(ValidationError):
        ContentDiscoveryRequest(objective="x", read_only=False)
    with pytest.raises(ValidationError):
        ContentDiscoveryRequest(objective="x", max_candidates=51)
    with pytest.raises(ValidationError):
        ContentDiscoveryRequest.model_validate(
            {"objective": "x", "read_only": True, "shell": "echo unsafe"}
        )


def test_coordinator_searches_before_one_local_scout_pass() -> None:
    search = FakeSearch()
    local = FakeLocal()
    coordinator = ContentDiscoveryCoordinator(search=search, local=local)

    result = coordinator.handler(
        _task(
            {
                "objective": "发现近期高增长、可进一步研究的内容主题候选",
                "read_only": True,
                "max_candidates": 20,
            }
        )
    )

    assert len(search.calls) == 4
    assert all(limit == 5 for _query, limit, _timeout in search.calls)
    assert len(local.requests) == 1
    scout = local.requests[0]
    assert scout.role is LocalAnalysisRole.SCOUT
    assert scout.evidence_ids == ["search-01", "search-02", "search-03", "search-04"]
    assert "Search evidence search-01" in scout.text

    assert result.result_type == "autonomous.discovery.v1"
    assert result.schema_version == "1.0"
    assert result.result_document is not None
    assert result.result_document["search_count"] == 4
    assert result.result_document["failed_search_count"] == 0
    assert result.result_document["confidence"] == 0.81
    assert result.result_document["findings"] == [
        "宠物拟人办公内容重复出现",
        "AI 视频工作流内容讨论增长",
    ]


def test_partial_search_failure_is_recorded_but_does_not_invent_missing_evidence() -> None:
    search = FakeSearch()
    local = FakeLocal()
    coordinator = ContentDiscoveryCoordinator(search=search, local=local)
    failed_query = coordinator.seed_queries[1]
    search.fail_queries.add(failed_query)

    result = coordinator.handler(
        _task({"objective": "发现主题", "read_only": True, "max_candidates": 10})
    )

    assert result.result_document is not None
    assert result.result_document["search_count"] == 3
    assert result.result_document["failed_search_count"] == 1
    assert local.requests[0].evidence_ids == ["search-01", "search-03", "search-04"]


def test_all_searches_failed_never_calls_local_model() -> None:
    local = FakeLocal()
    probe = ContentDiscoveryCoordinator(search=FakeSearch(), local=local)
    search = FakeSearch(fail_queries=set(probe.seed_queries))
    coordinator = ContentDiscoveryCoordinator(search=search, local=local)

    with pytest.raises(ContentDiscoveryError, match="all discovery searches failed"):
        coordinator.handler(
            _task({"objective": "发现主题", "read_only": True, "max_candidates": 10})
        )

    assert local.requests == []
