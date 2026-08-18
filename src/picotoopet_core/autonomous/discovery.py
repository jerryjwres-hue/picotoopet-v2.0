"""Tool-first autonomous discovery: Research Gateway evidence, then one local Scout pass."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from picotoopet_core.domain.models import TaskRecord
from picotoopet_core.research.execution import ResearchGatewayExecutionError
from picotoopet_core.research.models import ResearchSearchResult
from picotoopet_core.worker.handlers import HandlerResult

from .local_intelligence import (
    LocalAnalysisRequest,
    LocalAnalysisResult,
    LocalAnalysisRole,
    LocalIntelligenceAdapter,
)


class ContentDiscoveryError(RuntimeError):
    """The bounded discovery workflow could not produce trustworthy tool evidence."""


class ContentDiscoveryRequest(BaseModel):
    """Closed discovery request; provider/query selection remains server-owned."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default="1.0", pattern=r"^1\.0$")
    objective: str = Field(min_length=1, max_length=2_000)
    read_only: bool = True
    max_candidates: int = Field(default=20, ge=1, le=50)

    @model_validator(mode="after")
    def _require_read_only(self) -> ContentDiscoveryRequest:
        if self.read_only is not True:
            raise ValueError("autonomous discovery must remain read-only")
        return self


class _SearchExecutor(Protocol):
    def search(
        self,
        *,
        query: str,
        limit: int,
        timeout_seconds: int,
    ) -> ResearchSearchResult:
        """Run one existing bounded Research Gateway search."""


_DEFAULT_SEED_QUERIES = (
    "pet content trends high engagement short video recent",
    "pet product consumer pain points trending reviews recent",
    "AI video creative formats trending short form recent",
    "ecommerce creator content trends audience engagement recent",
)
_MAX_TOOL_EXCERPT_CHARS = 5_000


class ContentDiscoveryCoordinator:
    """Gather a small tool evidence batch before asking the local model to classify it."""

    TASK_TYPE = "autonomous.discovery.v1"
    CAPABILITY = "content.discovery"

    def __init__(
        self,
        *,
        search: _SearchExecutor,
        local: LocalIntelligenceAdapter,
        seed_queries: tuple[str, ...] = _DEFAULT_SEED_QUERIES,
    ) -> None:
        if not seed_queries or len(seed_queries) > 8:
            raise ValueError("seed_queries must contain 1-8 bounded queries")
        normalized = tuple(query.strip() for query in seed_queries)
        if any(not query or len(query) > 240 for query in normalized):
            raise ValueError("each discovery query must be 1-240 characters")
        if len(set(normalized)) != len(normalized):
            raise ValueError("seed_queries must be unique")
        self.search = search
        self.local = local
        self.seed_queries = normalized

    def handler(self, task: TaskRecord) -> HandlerResult:
        """Execute fixed searches, then one Scout analysis over only those search results."""

        if task.task_type != self.TASK_TYPE:
            raise ContentDiscoveryError("unsupported autonomous discovery task type")
        try:
            request = ContentDiscoveryRequest.model_validate(task.payload)
        except ValidationError as error:
            raise ContentDiscoveryError("invalid autonomous discovery request") from error

        per_query_limit = max(
            1,
            min(5, (request.max_candidates + len(self.seed_queries) - 1) // len(self.seed_queries)),
        )
        per_query_timeout = min(max(int(task.timeout_seconds / len(self.seed_queries)), 30), 120)

        successful: list[dict[str, str]] = []
        failed_count = 0
        for index, query in enumerate(self.seed_queries, start=1):
            evidence_id = f"search-{index:02d}"
            try:
                result = self.search.search(
                    query=query,
                    limit=per_query_limit,
                    timeout_seconds=per_query_timeout,
                )
            except ResearchGatewayExecutionError:
                failed_count += 1
                continue
            successful.append(
                {
                    "evidence_id": evidence_id,
                    "query": query,
                    "output_excerpt": _truncate_text(result.output, _MAX_TOOL_EXCERPT_CHARS),
                }
            )

        if not successful:
            raise ContentDiscoveryError("all discovery searches failed")

        scout_text = _render_scout_input(
            objective=request.objective,
            search_evidence=successful,
        )
        try:
            raw_analysis = self.local.analyze(
                LocalAnalysisRequest(
                    role=LocalAnalysisRole.SCOUT,
                    text=scout_text,
                    evidence_ids=[item["evidence_id"] for item in successful],
                )
            )
            analysis = LocalAnalysisResult.model_validate(raw_analysis)
        except (ValidationError, TypeError, ValueError) as error:
            raise ContentDiscoveryError("local scout returned invalid structured output") from error
        except Exception as error:
            raise ContentDiscoveryError("local scout failed") from error

        document = {
            "schema_version": "1.0",
            "objective": request.objective,
            "search_count": len(successful),
            "failed_search_count": failed_count,
            "search_evidence": successful,
            "summary": analysis.summary,
            "confidence": analysis.confidence,
            "findings": analysis.findings,
            "recommended_actions": analysis.recommended_actions,
            "evidence_ids": analysis.evidence_ids,
        }
        return HandlerResult(
            summary={
                "task_type": self.TASK_TYPE,
                "capability": self.CAPABILITY,
                "search_count": len(successful),
                "failed_search_count": failed_count,
                "confidence": analysis.confidence,
            },
            result_document=document,
            result_type=self.TASK_TYPE,
            schema_version="1.0",
        )


def _render_scout_input(*, objective: str, search_evidence: list[dict[str, str]]) -> str:
    lines = [
        "Goal objective:",
        objective,
        "",
        "The following items are tool-collected search evidence. Classify themes only from these items.",
    ]
    for item in search_evidence:
        lines.extend(
            [
                "",
                f"Search evidence {item['evidence_id']}",
                f"Query: {item['query']}",
                item["output_excerpt"],
            ]
        )
    rendered = "\n".join(lines)
    # LocalAnalysisRequest enforces 24k chars. Keep deterministic headroom for role instructions.
    return _truncate_text(rendered, 23_000)


def _truncate_text(value: str, maximum_chars: int) -> str:
    if len(value) <= maximum_chars:
        return value
    suffix = "\n...[truncated]"
    return value[: max(0, maximum_chars - len(suffix))] + suffix
