"""Tool-first autonomous discovery: canonical evidence + Research Gateway + local Scout."""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from picotoopet_core.domain.models import TaskRecord
from picotoopet_core.progress.models import ProgressUpdate
from picotoopet_core.progress.reporter import ProgressReporter
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
from .legacy_acquisition import build_discovery_queries
from .local_intelligence import (
    LocalAnalysisRequest,
    LocalAnalysisResult,
    LocalAnalysisRole,
    LocalIntelligenceAdapter,
    LocalIntelligenceError,
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
    connected_product_keys: tuple[str, ...] = Field(default=(), max_length=8)

    @model_validator(mode="after")
    def _require_safe_scope(self) -> ContentDiscoveryRequest:
        if self.read_only is not True:
            raise ValueError("autonomous discovery must remain read-only")
        if len(set(self.connected_product_keys)) != len(self.connected_product_keys):
            raise ValueError("connected_product_keys must be unique")
        for key in self.connected_product_keys:
            if not key or key != key.strip() or len(key) > 200:
                raise ValueError("connected_product_keys must contain bounded canonical keys")
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


class _ConnectedProduct(Protocol):
    product_key: str
    title: str


class _ConnectedEvidence(Protocol):
    evidence_id: str
    product_key: str
    evidence_type: str
    source: str
    platform: str
    source_url: str
    text_value: str
    numeric_value: float | None
    trust_level: str
    confidence: float
    captured_at: str
    origin: str


class _ConnectedEvidenceReader(Protocol):
    """Read-only view over Mac Core canonical evidence; never exposes database writes to the model."""

    def list_products(self, *, limit: int = 200) -> list[_ConnectedProduct]: ...

    def list_evidence(
        self,
        *,
        product_key: str | None = None,
        limit: int = 500,
    ) -> list[_ConnectedEvidence]: ...


_MAX_TOOL_EXCERPT_CHARS = 5_000
_MAX_RADAR_EXCERPT_CHARS = 4_000
_MAX_CONNECTED_PRODUCTS = 1_000
_MAX_CONNECTED_EVIDENCE = 16
_MAX_CONNECTED_TEXT_CHARS = 600
_MAX_SCOUT_STAGE_ATTEMPTS = 2
_SUBJECT_WHITESPACE = re.compile(r"\s+")


class ContentDiscoveryCoordinator:
    """Gather existing canonical evidence and objective-specific tool evidence before Scout."""

    TASK_TYPE = "autonomous.discovery.v1"
    CAPABILITY = "content.discovery"

    def __init__(
        self,
        *,
        search: _SearchExecutor,
        local: LocalIntelligenceAdapter,
        seed_queries: tuple[str, ...] | None = None,
        connected_evidence: _ConnectedEvidenceReader | None = None,
        progress: ProgressReporter | None = None,
    ) -> None:
        normalized: tuple[str, ...] | None = None
        if seed_queries is not None:
            if not seed_queries or len(seed_queries) > 8:
                raise ValueError("seed_queries must contain 1-8 bounded queries")
            normalized = tuple(query.strip() for query in seed_queries)
            if any(not query or len(query) > 240 for query in normalized):
                raise ValueError("each discovery query must be 1-240 characters")
            if len(set(normalized)) != len(normalized):
                raise ValueError("seed_queries must be unique")
        self.search              = search
        self.local               = local
        self.connected_evidence  = connected_evidence
        self.progress            = progress
        # ── Explicit seeds remain only a deterministic fixture/manual override. ──
        self.seed_queries        = normalized

    def handler(self, task: TaskRecord) -> HandlerResult:
        """Use scoped Core evidence, bounded searches, Radar cleanup, then one Scout pass."""

        if task.task_type != self.TASK_TYPE:
            raise ContentDiscoveryError("unsupported autonomous discovery task type")
        try:
            request = ContentDiscoveryRequest.model_validate(task.payload)
        except ValidationError as error:
            raise ContentDiscoveryError("invalid autonomous discovery request") from error

        self._emit_progress(
            task=task,
            stage="prepare",
            message="正在准备研究目标和已有证据。",
            component="worker",
        )
        if request.connected_product_keys:
            connected = self._connected_evidence_for_keys(request.connected_product_keys)
        else:
            connected = self._connected_evidence_for_objective(request.objective)
        connected_ids = [item["evidence_id"] for item in connected]
        self._emit_progress(
            task=task,
            stage="connected-evidence",
            message=f"已读取 {len(connected)} 条现有可信证据。",
            component="core",
            details={"connected_evidence_count": len(connected)},
        )

        queries = self._queries_for_objective(request.objective)
        per_query_limit = max(
            1,
            min(5, (request.max_candidates + len(queries) - 1) // len(queries)),
        )
        per_query_timeout = min(max(int(task.timeout_seconds / len(queries)), 30), 120)

        successful: list[dict[str, str]] = []
        radar_inputs: list[RadarCandidateInput] = []
        failed_count = 0
        self._emit_progress(
            task=task,
            stage="research-search",
            completed=0,
            total=len(queries),
            message=f"准备执行 {len(queries)} 个只读研究查询。",
            component="research",
            details={"successful_sources": 0, "failed_sources": 0},
        )
        for index, query in enumerate(queries, start=1):
            evidence_id = f"search-{index:02d}"
            try:
                result = self.search.search(
                    query=query,
                    limit=per_query_limit,
                    timeout_seconds=per_query_timeout,
                )
            except ResearchGatewayExecutionError:
                failed_count += 1
                self._emit_progress(
                    task=task,
                    stage="research-search",
                    completed=index,
                    total=len(queries),
                    message=f"研究查询 {index}/{len(queries)} 完成；本次来源失败。",
                    component="research",
                    details={
                        "successful_sources": len(successful),
                        "failed_sources": failed_count,
                    },
                )
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
            self._emit_progress(
                task=task,
                stage="research-search",
                completed=index,
                total=len(queries),
                message=f"研究查询 {index}/{len(queries)} 完成。",
                component="research",
                details={
                    "successful_sources": len(successful),
                    "failed_sources": failed_count,
                },
            )

        # ── Canonical evidence remains usable when Research Gateway is temporarily offline. ──
        if not successful and not connected:
            raise ContentDiscoveryError("all discovery searches failed")

        self._emit_progress(
            task=task,
            stage="radar-normalize",
            message="正在去重并整理研究候选。",
            component="worker",
            details={
                "successful_sources": len(successful),
                "failed_sources": failed_count,
            },
        )
        radar_candidates = normalize_candidates(radar_inputs)[: request.max_candidates]
        radar_clusters   = cluster_candidates(radar_candidates)
        # ── Missing trustworthy velocity/business metrics stay unscored rather than inferred. ──
        radar_scores = [
            {
                "candidate_id": candidate.candidate_id,
                "score": score_candidate(RadarScoreSignals()).model_dump(mode="json"),
            }
            for candidate in radar_candidates
        ]
        search_ids   = [item["evidence_id"] for item in successful]
        evidence_ids = connected_ids + search_ids
        initial_round = ResearchRound(
            round_number=0,
            evidence_ids=evidence_ids,
            cluster_ids=[cluster.cluster_id for cluster in radar_clusters],
            information_gain_ratio=1.0,
        )
        stop_decision = evaluate_research_stop([initial_round])

        if radar_candidates:
            search_text = _render_radar_scout_input(
                objective=request.objective,
                candidates=radar_candidates,
            )
        else:
            search_text = _render_scout_input(
                objective=request.objective,
                search_evidence=successful,
            )
        scout_text = _render_combined_scout_input(
            objective=request.objective,
            connected_evidence=connected,
            search_text=search_text,
        )
        self._emit_progress(
            task=task,
            stage="local-scout",
            message="研究证据已准备完成，正在进行本地 Scout 分析。",
            component="ollama",
            details={
                "evidence_count": len(evidence_ids),
                "candidate_count": len(radar_candidates),
                "attempt": 1,
            },
        )
        analysis_request = LocalAnalysisRequest(
            role=LocalAnalysisRole.SCOUT,
            text=scout_text,
            evidence_ids=evidence_ids,
        )
        analysis: LocalAnalysisResult | None = None
        for scout_attempt in range(1, _MAX_SCOUT_STAGE_ATTEMPTS + 1):
            try:
                raw_analysis = self.local.analyze(analysis_request)
                analysis = LocalAnalysisResult.model_validate(raw_analysis)
                break
            except (ValidationError, TypeError, ValueError) as error:
                raise ContentDiscoveryError(
                    "local scout returned invalid structured output"
                ) from error
            except LocalIntelligenceError as error:
                is_timeout = str(error).strip() == "MODEL_RUNNER_TIMEOUT"
                if not is_timeout or scout_attempt >= _MAX_SCOUT_STAGE_ATTEMPTS:
                    raise ContentDiscoveryError("local scout failed") from error
                # ── Research evidence is already complete in memory; resume only Scout. ──
                self._emit_progress(
                    task=task,
                    stage="local-scout",
                    message="本地模型超时；保留已完成研究证据并重试 Scout。",
                    component="ollama",
                    details={
                        "evidence_count": len(evidence_ids),
                        "candidate_count": len(radar_candidates),
                        "attempt": scout_attempt + 1,
                        "checkpoint": "research-complete",
                    },
                )
            except Exception as error:
                raise ContentDiscoveryError("local scout failed") from error
        if analysis is None:
            raise ContentDiscoveryError("local scout failed")

        document = {
            "schema_version": "1.0",
            "objective": request.objective,
            "connected_evidence_count": len(connected),
            "connected_evidence": connected,
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
        self._emit_progress(
            task=task,
            stage="discovery-complete",
            completed=1,
            total=1,
            message="资料搜集和首轮本地筛选已完成。",
            component="worker",
            details={
                "evidence_count": len(evidence_ids),
                "candidate_count": len(radar_candidates),
                "failed_sources": failed_count,
            },
        )
        return HandlerResult(
            summary={
                "task_type": self.TASK_TYPE,
                "capability": self.CAPABILITY,
                "connected_evidence_count": len(connected),
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

    def _emit_progress(
        self,
        *,
        task: TaskRecord,
        stage: str,
        message: str,
        component: str,
        completed: int | None = None,
        total: int | None = None,
        details: dict[str, object] | None = None,
    ) -> None:
        """Emit only a bounded fact; a missing reporter preserves deterministic unit fixtures."""

        if self.progress is None:
            return
        self.progress.emit(
            ProgressUpdate(
                task_id=task.task_id,
                stage=stage,
                completed=completed,
                total=total,
                message=message,
                component=component,
                details=details or {},
            )
        )

    def _queries_for_objective(self, objective: str) -> tuple[str, ...]:
        """Choose explicit fixture seeds or the deterministic legacy-derived objective plan."""

        if self.seed_queries is not None:
            return self.seed_queries
        return build_discovery_queries(objective)

    def _connected_evidence_for_keys(
        self,
        product_keys: tuple[str, ...],
    ) -> list[dict[str, object]]:
        """Read only exact Core-selected products; never fuzzy-expand an automatic intake scope."""

        if self.connected_evidence is None:
            return []
        selected: list[dict[str, object]] = []
        seen_ids: set[str] = set()
        for product_key in product_keys:
            for record in self.connected_evidence.list_evidence(
                product_key=product_key,
                limit=_MAX_CONNECTED_EVIDENCE,
            ):
                item = _connected_evidence_item(record, seen_ids)
                if item is None:
                    continue
                selected.append(item)
                if len(selected) >= _MAX_CONNECTED_EVIDENCE:
                    return selected
        return selected

    def _connected_evidence_for_objective(self, objective: str) -> list[dict[str, object]]:
        """Use existing evidence only when deterministic text matching identifies one product."""

        if self.connected_evidence is None:
            return []
        normalized_objective = _normalize_subject(objective)
        matches: dict[str, _ConnectedProduct] = {}
        for product in self.connected_evidence.list_products(limit=_MAX_CONNECTED_PRODUCTS):
            normalized_key   = _normalize_subject(product.product_key)
            normalized_title = _normalize_subject(product.title)
            key_match = bool(normalized_key and normalized_key in normalized_objective)
            title_match = bool(
                len(normalized_title) >= 4 and normalized_title in normalized_objective
            )
            if key_match or title_match:
                matches[product.product_key] = product
        if len(matches) != 1:
            # ── Ambiguity is never resolved by fuzzy/model guessing across products. ──
            return []

        product_key = next(iter(matches))
        selected: list[dict[str, object]] = []
        seen_ids: set[str] = set()
        for record in self.connected_evidence.list_evidence(
            product_key=product_key,
            limit=_MAX_CONNECTED_EVIDENCE,
        ):
            item = _connected_evidence_item(record, seen_ids)
            if item is not None:
                selected.append(item)
        return selected


def _connected_evidence_item(
    record: _ConnectedEvidence,
    seen_ids: set[str],
) -> dict[str, object] | None:
    if record.evidence_id in seen_ids:
        return None
    text_excerpt = _truncate_text(record.text_value.strip(), _MAX_CONNECTED_TEXT_CHARS)
    if not text_excerpt and record.numeric_value is None:
        return None
    seen_ids.add(record.evidence_id)
    return {
        "evidence_id": record.evidence_id,
        "product_key": record.product_key,
        "evidence_type": record.evidence_type,
        "source": record.source,
        "platform": record.platform,
        "source_url": record.source_url,
        "text_excerpt": text_excerpt,
        "numeric_value": record.numeric_value,
        "trust_level": record.trust_level,
        "confidence": record.confidence,
        "captured_at": record.captured_at,
        "origin": record.origin,
    }


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
        title_value  = document.get("title")
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
            # ── One malformed/private document cannot poison the whole typed batch. ──
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
    return _truncate_text("\n".join(lines), 12_000)


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
    return _truncate_text("\n".join(lines), 12_000)


def _render_combined_scout_input(
    *,
    objective: str,
    connected_evidence: list[dict[str, object]],
    search_text: str,
) -> str:
    lines = [
        "Goal objective:",
        objective,
        "",
        "Use only the evidence below. Connected evidence is an existing Mac Core fact, not model output.",
        "Do not invent values, sources, metrics, or facts that are not explicitly present.",
    ]
    if connected_evidence:
        lines.extend(["", "Connected canonical evidence (read-only; already in Mac Core):"])
        for item in connected_evidence:
            lines.extend(
                [
                    "",
                    f"Evidence ID: {item['evidence_id']}",
                    f"Product: {item['product_key']}",
                    f"Source: {item['source']} / {item['platform']}",
                    f"Trust: {item['trust_level']}",
                    f"Confidence: {item['confidence']}",
                    f"Captured: {item['captured_at']}",
                    f"Text: {item['text_excerpt']}",
                    f"Numeric: {item['numeric_value']}",
                ]
            )
    if search_text.strip():
        lines.extend(["", "Read-only Research Gateway evidence:", search_text])
    # ── LocalAnalysisRequest caps input at 24k; leave deterministic instruction headroom. ──
    return _truncate_text("\n".join(lines), 23_000)


def _normalize_subject(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    return _SUBJECT_WHITESPACE.sub(" ", normalized)


def _truncate_text(value: str, maximum_chars: int) -> str:
    if len(value) <= maximum_chars:
        return value
    suffix = "\n...[truncated]"
    return value[: max(0, maximum_chars - len(suffix))] + suffix
