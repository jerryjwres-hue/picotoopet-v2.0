"""Bounded local-intelligence task for the always-on Mac worker.

The local model is intentionally treated as a narrow structured worker. Queue
payloads cannot supply system prompts, tools, URLs, file paths or shell
commands; callers provide only a fixed role, bounded text and evidence IDs.
"""

from __future__ import annotations

import asyncio
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from picotoopet_core.agents.runtime import AgentRuntime
from picotoopet_core.domain.models import TaskRecord
from picotoopet_core.ollama.model_runner import (
    IsolatedModelRunner,
    ModelRunnerError,
    ModelRunnerPolicy,
)
from picotoopet_core.worker.handlers import HandlerResult


class LocalIntelligenceError(RuntimeError):
    """Local analysis request or structured result failed its closed contract."""


class LocalAnalysisRole(StrEnum):
    """Small fixed jobs that a local 20B model can perform reliably."""

    SCOUT = "scout"
    FILTER = "filter"
    ANALYST = "analyst"
    JUDGE = "judge"
    EDITOR = "editor"


class LocalAnalysisRequest(BaseModel):
    """Worker payload; extra fields are rejected so it cannot become a general agent."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default="1.0", pattern=r"^1\.0$")
    role: LocalAnalysisRole
    text: str = Field(min_length=1, max_length=24_000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=64)

    @field_validator("evidence_ids")
    @classmethod
    def _validate_evidence_ids(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("evidence_ids must be unique")
        for value in values:
            if not value or len(value) > 128:
                raise ValueError("evidence_id must be 1-128 characters")
        return values


class LocalAnalysisResult(BaseModel):
    """Persistable result returned by the local language worker."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default="1.0", pattern=r"^1\.0$")
    role: LocalAnalysisRole
    summary: str = Field(min_length=1, max_length=4_000)
    confidence: float = Field(ge=0.0, le=1.0)
    findings: list[str] = Field(default_factory=list, max_length=32)
    recommended_actions: list[str] = Field(default_factory=list, max_length=16)
    evidence_ids: list[str] = Field(default_factory=list, max_length=64)

    @field_validator("findings", "recommended_actions")
    @classmethod
    def _validate_bounded_lines(cls, values: list[str]) -> list[str]:
        for value in values:
            if not value or len(value) > 2_000:
                raise ValueError("structured text item must be 1-2000 characters")
        return values

    @field_validator("evidence_ids")
    @classmethod
    def _validate_result_evidence_ids(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("evidence_ids must be unique")
        for value in values:
            if not value or len(value) > 128:
                raise ValueError("evidence_id must be 1-128 characters")
        return values


class LocalIntelligenceAdapter(Protocol):
    """Synchronous interface consumed by the Worker coordinator."""

    def analyze(self, request: LocalAnalysisRequest) -> LocalAnalysisResult:
        """Return one bounded structured result."""


_ROLE_INSTRUCTIONS: dict[LocalAnalysisRole, str] = {
    LocalAnalysisRole.SCOUT: (
        "判断候选内容是否值得继续低成本验证。关注相关性、新颖度和潜在价值；"
        "不要扩展成开放式研究计划。"
    ),
    LocalAnalysisRole.FILTER: (
        "筛掉噪声、广告拼接、重复语义和与目标无关的内容，只保留有证据价值的项目。"
    ),
    LocalAnalysisRole.ANALYST: (
        "只解释给定材料中的模式、痛点、正向驱动和受众信号；不要补写不存在的事实。"
    ),
    LocalAnalysisRole.JUDGE: (
        "判断当前证据是否足以支持结论，并指出矛盾或仍需验证的最小缺口。"
    ),
    LocalAnalysisRole.EDITOR: (
        "压缩已经验证的结论，保持事实、推断和建议分离；禁止新增事实。"
    ),
}


def _build_prompt(request: LocalAnalysisRequest) -> str:
    evidence = ", ".join(request.evidence_ids) if request.evidence_ids else "无"
    return (
        "你正在执行 PicotooPet AI 的固定本地分析工位。\n"
        f"角色：{request.role.value}\n"
        f"固定职责：{_ROLE_INSTRUCTIONS[request.role]}\n"
        "规则：只使用下面给出的文本；不要调用工具、不要访问网络、不要读取文件、"
        "不要假设未提供的数据。输出必须符合既定结构化结果。\n"
        f"Evidence IDs：{evidence}\n"
        "输入文本：\n"
        f"{request.text}"
    )


class AgentRuntimeLocalIntelligenceAdapter:
    """Legacy in-process adapter retained only for explicitly injected tests and callers."""

    def __init__(self, runtime: AgentRuntime) -> None:
        self.runtime = runtime

    def analyze(self, request: LocalAnalysisRequest) -> LocalAnalysisResult:
        prompt = _build_prompt(request)
        try:
            result = asyncio.run(self.runtime.analyze(prompt))
        except RuntimeError as error:
            # ── Production assembly no longer uses this in-process path. ──
            raise LocalIntelligenceError("local model runtime unavailable") from error
        return _to_local_result(request, result)

    @staticmethod
    def _build_prompt(request: LocalAnalysisRequest) -> str:
        """Compatibility helper used by existing focused tests/callers."""

        return _build_prompt(request)


class IsolatedRunnerLocalIntelligenceAdapter:
    """Production adapter: long model execution lives only in a killable child process."""

    def __init__(self, runner: IsolatedModelRunner) -> None:
        self.runner = runner

    def analyze(self, request: LocalAnalysisRequest) -> LocalAnalysisResult:
        try:
            result = self.runner.analyze(_build_prompt(request))
        except ModelRunnerError as error:
            # ── Stable runner codes are preserved without exposing prompt or child output. ──
            raise LocalIntelligenceError(str(error)) from error
        return _to_local_result(request, result)


def _to_local_result(request: LocalAnalysisRequest, result: object) -> LocalAnalysisResult:
    """Map the validated AgentResult shape into the local-analysis result contract."""

    summary = getattr(result, "summary")
    confidence = getattr(result, "confidence")
    findings = getattr(result, "findings")
    recommended_actions = getattr(result, "recommended_actions")
    return LocalAnalysisResult(
        role=request.role,
        summary=summary,
        confidence=confidence,
        findings=findings,
        recommended_actions=recommended_actions,
        evidence_ids=request.evidence_ids,
    )


def build_ollama_local_intelligence_adapter(
    *,
    work_root: Path | str,
    model_name: str = "gpt-oss:20b",
    base_url: str = "http://127.0.0.1:11434/v1",
    timeout_seconds: float = 900.0,
) -> IsolatedRunnerLocalIntelligenceAdapter:
    """Build the production local-analysis adapter with a hard subprocess boundary."""

    policy = ModelRunnerPolicy(
        hard_timeout_seconds=min(float(timeout_seconds), 1800.0),
        max_attempts=2,
        circuit_failure_threshold=2,
        circuit_cooldown_seconds=60.0,
    )
    return IsolatedRunnerLocalIntelligenceAdapter(
        IsolatedModelRunner(
            work_root=work_root,
            model_name=model_name,
            base_url=base_url,
            policy=policy,
        )
    )


class LocalIntelligenceCoordinator:
    """Translate one fixed queue task into one structured local-model result."""

    TASK_TYPE = "autonomous.local_analysis.v1"
    CAPABILITY = "local.text.analysis"

    def __init__(self, adapter: LocalIntelligenceAdapter) -> None:
        self.adapter = adapter

    def handler(self, task: TaskRecord) -> HandlerResult:
        if task.task_type != self.TASK_TYPE:
            raise LocalIntelligenceError("unsupported local intelligence task type")
        try:
            request = LocalAnalysisRequest.model_validate(task.payload)
        except ValidationError as error:
            raise LocalIntelligenceError("invalid local analysis request") from error

        try:
            raw_result = self.adapter.analyze(request)
            result = LocalAnalysisResult.model_validate(raw_result)
        except (ValidationError, TypeError, ValueError) as error:
            raise LocalIntelligenceError("invalid structured output") from error
        except LocalIntelligenceError:
            raise
        except Exception as error:
            raise LocalIntelligenceError("local model analysis failed") from error

        return HandlerResult(
            summary={
                "task_type": self.TASK_TYPE,
                "role": result.role.value,
                "evidence_count": len(result.evidence_ids),
                "confidence": result.confidence,
            },
            result_document=result.model_dump(mode="json"),
            result_type=self.TASK_TYPE,
            schema_version=result.schema_version,
        )
