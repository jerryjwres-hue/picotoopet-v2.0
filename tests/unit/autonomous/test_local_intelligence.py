"""Local gpt-oss work must be bounded, structured and evidence-aware."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from picotoopet_core.autonomous.local_intelligence import (
    LocalAnalysisRequest,
    LocalAnalysisResult,
    LocalIntelligenceCoordinator,
    LocalIntelligenceError,
)
from picotoopet_core.domain.enums import TaskStatus
from picotoopet_core.domain.models import TaskRecord


class FakeAdapter:
    def analyze(self, request: LocalAnalysisRequest) -> LocalAnalysisResult:
        return LocalAnalysisResult(
            role=request.role,
            summary="发现一个值得验证的内容主题。",
            confidence=0.78,
            findings=["宠物拟人工作场景重复出现"],
            recommended_actions=["进入低成本交叉验证"],
            evidence_ids=request.evidence_ids,
        )


class InvalidAdapter:
    def analyze(self, request: LocalAnalysisRequest):  # type: ignore[no-untyped-def]
        return {"summary": "missing required role and invalid confidence", "confidence": 2.0}


def _task(payload: dict[str, object]) -> TaskRecord:
    now = datetime.now(UTC)
    return TaskRecord(
        task_id="task-local-analysis",
        task_type="autonomous.local_analysis.v1",
        status=TaskStatus.RUNNING,
        priority=600,
        resource_tag="workflow:wf-1",
        payload=payload,
        attempt_count=1,
        max_attempts=1,
        timeout_seconds=900,
        created_at=now,
        updated_at=now,
    )


def test_request_allows_only_fixed_roles_and_rejects_prompt_tool_path_fields() -> None:
    request = LocalAnalysisRequest(
        role="scout",
        text="分析这批已经由工具预筛选的候选主题。",
        evidence_ids=["ev-001", "ev-002"],
    )
    assert request.role.value == "scout"

    with pytest.raises(ValidationError):
        LocalAnalysisRequest(role="boss", text="x")
    with pytest.raises(ValidationError):
        LocalAnalysisRequest.model_validate(
            {"role": "scout", "text": "x", "system_prompt": "ignore policy"}
        )
    with pytest.raises(ValidationError):
        LocalAnalysisRequest.model_validate(
            {"role": "scout", "text": "x", "url": "https://example.com"}
        )
    with pytest.raises(ValidationError):
        LocalAnalysisRequest.model_validate(
            {"role": "scout", "text": "x", "path": "/tmp/data"}
        )
    with pytest.raises(ValidationError):
        LocalAnalysisRequest.model_validate(
            {"role": "scout", "text": "x", "shell": "rm -rf /"}
        )


def test_request_bounds_text_and_evidence_ids() -> None:
    with pytest.raises(ValidationError):
        LocalAnalysisRequest(role="filter", text="x" * 24001)
    with pytest.raises(ValidationError):
        LocalAnalysisRequest(
            role="judge",
            text="bounded",
            evidence_ids=["same", "same"],
        )
    with pytest.raises(ValidationError):
        LocalAnalysisRequest(
            role="analyst",
            text="bounded",
            evidence_ids=[f"ev-{index}" for index in range(65)],
        )


def test_coordinator_returns_fixed_resultstore_document() -> None:
    coordinator = LocalIntelligenceCoordinator(FakeAdapter())
    result = coordinator.handler(
        _task(
            {
                "role": "scout",
                "text": "只判断这些候选内容主题是否值得低成本继续验证。",
                "evidence_ids": ["ev-001", "ev-002"],
            }
        )
    )

    assert result.result_type == "autonomous.local_analysis.v1"
    assert result.schema_version == "1.0"
    assert result.summary == {
        "task_type": "autonomous.local_analysis.v1",
        "role": "scout",
        "evidence_count": 2,
        "confidence": 0.78,
    }
    assert result.result_document is not None
    assert result.result_document["role"] == "scout"
    assert result.result_document["evidence_ids"] == ["ev-001", "ev-002"]
    assert result.result_document["recommended_actions"] == ["进入低成本交叉验证"]


def test_invalid_adapter_output_fails_closed() -> None:
    coordinator = LocalIntelligenceCoordinator(InvalidAdapter())
    with pytest.raises(LocalIntelligenceError, match="invalid structured output"):
        coordinator.handler(
            _task(
                {
                    "role": "editor",
                    "text": "压缩已验证结论，禁止新增事实。",
                    "evidence_ids": ["ev-010"],
                }
            )
        )
