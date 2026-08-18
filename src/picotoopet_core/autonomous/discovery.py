"""Tool-first autonomous discovery: Research Gateway evidence, then one local Scout pass."""

from __future__ import annotations

import json
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from picotoopet_core.domain.models import TaskRecord
from picotoopet_core.research.execution import ResearchGatewayExecutionError
from picotoopet_core.research.models import ResearchSearchResult
from picotoopet_core.worker.handlers import HandlerResult

from .content_radar import (
    RadarCandidate,
    RadarCandidateInput,
    RadarScoreSignals,
    cluster_candidates,
    normalize_candidates,
    score_candidate,
)
from .local_intelligence import (
    LocalAnalysisRequest,
    LocalAnalysisResult,
    LocalAnalysisRole,
    LocalIntelligenceAdapter,
)
from .research_stop import ResearchRound, evaluate_research_stop


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
_MAX_RADAR_EXCERPT_CHARS = 4_000


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
        """Execute fixed searches, deterministic Radar cleanup, then one Scout analysis."""

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
        radar_inputs: list[RadarCandidateInput] = []
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
            radar_inputs.extend(
                _extract_typed_radar_inputs(
                    evidence_id=evidence_id,
                    output=result.output,
                )
            )

        if not successful:
            raise ContentDiscoveryError("all discovery searches failed")

        radar_candidates = normalize_candidates(radar_inputs)[: request.max_candidates]
        radar_clusters = cluster_candidates(radar_candidates)
        # Current crawler envelopes provide content/provenance but no trustworthy
        # velocity, resonance, business or actionability metrics. Therefore every
        # missing scoring dimension remains None/zero instead of being inferred
        # from prose or from the Scout's free-form findings.
        radar_scores = [
            {
                "candidate_id": candidate.candidate_id,
                "score": score_candidate(RadarScoreSignals()).model_dump(mode="json"),
            }
            for candidate in radar_candidates
        ]
        evidence_ids = [item["evidence_id"] for item in successful]
        initial_round = ResearchRound(
            round_number=0,
            evidence_ids=evidence_ids,
            cluster_ids=[cluster.cluster_id for cluster in radar_clusters],
            # Initial collection is measured against an empty evidence set; all
            # accepted evidence is new at round zero. Later rounds must measure
            # marginal gain and are constrained by research_stop.py.
            information_gain_ratio=1.0,
        )
        stop_decision = evaluate_research_stop([initial_round])

        scout_text = (
            _render_radar_scout_input(
                objective=request.objective,
                candidates=radar_candidates,
            )
            if radar_candidates
            else _render_scout_input(
                objective=request.objective,
                search_evidence=successful,
            )
        )
        try:
            raw_analysis = self.local.analyze(
                LocalAnalysisRequest(
                    role=LocalAnalysisRole.SCOUT,
                    text=scout_text,
                    evidence_ids=evidence_ids,
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
            "content_radar": {
                "candidate_count": len(radar_candidates),
                "cluster_count": len(radar_clusters),
                "candidates": [
                    candidate.model_dump(mode="json") for candidate in radar_candidates
                ],
                "clusters": [cluster.model_dump(mode="json") for cluster in radar_clusters],
                "scores": radar_scores,
                "research_rounds": [initial_round.model_dump(mode="json")],
                "research_stop": stop_decision.model_dump(mode="json"),
            },
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
                "candidate_count": len(radar_candidates),
                "cluster_count": len(radar_clusters),
                "confidence": analysis.confidence,
            },
            result_document=document,
            result_type=self.TASK_TYPE,
            schema_version="1.0",
        )


def _extract_typed_radar_inputs(*, evidence_id: str, output: str) -> list[RadarCandidateInput]:
    """Read only known typed document envelopes; legacy/plain output yields no fake candidate."""

    try:
        payload = json.loads(output)
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(payload, dict):
        return []
    documents = payload.get("documents")
    if not isinstance(documents, list):
        return []

    accepted: list[RadarCandidateInput] = []
    for document in documents[:50]:
        if not isinstance(document, dict):
            continue
        url = document.get("url")
        if not isinstance(url, str) or not url.strip():
            continue
        title_value = document.get("title")
        source_value = document.get("source")
        title = (
            title_value.strip()
            if isinstance(title_value, str) and title_value.strip()
            else source_value.strip()
            if isinstance(source_value, str) and source_value.strip()
            else "Untitled evidence"
        )
        markdown = document.get("markdown")
        excerpt = (
            _truncate_text(markdown.strip(), _MAX_RADAR_EXCERPT_CHARS)
            if isinstance(markdown, str) and markdown.strip()
            else title
        )
        provider = document.get("provider")
        platform = provider.strip() if isinstance(provider, str) and provider.strip() else None
        try:
            candidate = RadarCandidateInput(
                evidence_id=evidence_id,
                url=url,
                title=_truncate_text(title, 500),
                excerpt=excerpt,
                platform=platform,
            )
            # Validate the public URL through the canonical Radar path per item,
            # so one malformed/private document cannot poison the whole batch.
            normalize_candidates([candidate])
        except (ValidationError, ValueError):
            continue
        accepted.append(candidate)
    return accepted


def _render_radar_scout_input(*, objective: str, candidates: list[RadarCandidate]) -> str:
    lines = [
        "Goal objective:",
        objective,
        "",
        "The following candidates were normalized and exactly deduplicated by deterministic code.",
        "Classify themes only from these candidates. Do not invent engagement metrics or scores.",
    ]
    for candidate in candidates:
        lines.extend(
            [
                "",
                f"Search evidence {', '.join(candidate.evidence_ids)}",
                f"URL: {candidate.canonical_url}",
                f"Title: {candidate.title}",
                f"Excerpt: {candidate.excerpt}",
            ]
        )
    return _truncate_text("\n".join(lines), 23_000)


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
