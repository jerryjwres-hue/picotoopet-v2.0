"""Discovery progress must expose real work rather than elapsed-time estimates."""

from __future__ import annotations

from datetime import UTC, datetime

from picotoopet_core.autonomous.discovery import ContentDiscoveryCoordinator
from picotoopet_core.autonomous.local_intelligence import (
    LocalAnalysisRequest,
    LocalAnalysisResult,
)
from picotoopet_core.domain.enums import TaskStatus
from picotoopet_core.domain.models import TaskRecord
from picotoopet_core.progress.models import ProgressUpdate
from picotoopet_core.research.models import ResearchSearchResult


class RecordingProgress:
    """In-memory recorder that implements the narrow progress reporter contract."""

    def __init__(self) -> None:
        self.updates: list[ProgressUpdate] = []

    def emit(self, update: ProgressUpdate) -> None:
        self.updates.append(update)


class SuccessfulSearch:
    def search(self, *, query: str, limit: int, timeout_seconds: int) -> ResearchSearchResult:
        return ResearchSearchResult(
            query=query,
            limit=limit,
            output=(
                '{"documents":[{"title":"hit","url":"https://example.com/',
                query,
                '"}]}',
            )[0]
            + query
            + '"}]}'
        )


class LocalScout:
    def analyze(self, request: LocalAnalysisRequest) -> LocalAnalysisResult:
        return LocalAnalysisResult(
            role=request.role,
            summary="progress test",
            confidence=0.8,
            findings=["finding"],
            recommended_actions=["action"],
            evidence_ids=request.evidence_ids,
        )


def _task() -> TaskRecord:
    now = datetime.now(UTC)
    return TaskRecord(
        task_id="task-progress",
        task_type="autonomous.discovery.v1",
        status=TaskStatus.RUNNING,
        priority=600,
        resource_tag="workflow:wf-progress",
        payload={"objective": "研究测试目标", "read_only": True, "max_candidates": 12},
        attempt_count=1,
        max_attempts=2,
        timeout_seconds=900,
        created_at=now,
        updated_at=now,
    )


def test_discovery_emits_truthful_query_progress_and_stage_transitions() -> None:
    """Four real search calls must yield 0/4 through 4/4 and bounded later stages."""

    progress = RecordingProgress()
    coordinator = ContentDiscoveryCoordinator(
        search=SuccessfulSearch(),
        local=LocalScout(),
        seed_queries=("q1", "q2", "q3", "q4"),
        progress=progress,
    )

    coordinator.handler(_task())

    search_events = [event for event in progress.updates if event.stage == "research-search"]
    assert [(event.completed, event.total) for event in search_events] == [
        (0, 4),
        (1, 4),
        (2, 4),
        (3, 4),
        (4, 4),
    ]
    assert all(event.task_id == "task-progress" for event in progress.updates)
    stages = [event.stage for event in progress.updates]
    assert stages[0] == "prepare"
    assert "local-scout" in stages
    assert stages[-1] == "discovery-complete"
    assert progress.updates[-1].completed == 1
    assert progress.updates[-1].total == 1


def test_discovery_progress_counts_failed_searches_without_stalling_sequence() -> None:
    """Every attempted query advances completed/total even when a provider call fails."""

    class PartiallyFailingSearch(SuccessfulSearch):
        def search(self, *, query: str, limit: int, timeout_seconds: int) -> ResearchSearchResult:
            from picotoopet_core.research.execution import ResearchGatewayExecutionError

            if query == "q2":
                raise ResearchGatewayExecutionError("simulated")
            return super().search(query=query, limit=limit, timeout_seconds=timeout_seconds)

    progress = RecordingProgress()
    coordinator = ContentDiscoveryCoordinator(
        search=PartiallyFailingSearch(),
        local=LocalScout(),
        seed_queries=("q1", "q2", "q3"),
        progress=progress,
    )

    coordinator.handler(_task())

    search_events = [event for event in progress.updates if event.stage == "research-search"]
    assert [(event.completed, event.total) for event in search_events] == [
        (0, 3),
        (1, 3),
        (2, 3),
        (3, 3),
    ]
    assert search_events[2].details["failed_sources"] == 1
