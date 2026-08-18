# PicotooPet AI Content Radar Slice B Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the existing evidence-grounded `content.discovery` task into a deterministic Content Radar that normalizes and deduplicates tool evidence, computes bounded research-priority scores, clusters related topics, and stops deepening when information gain is exhausted.

**Architecture:** Keep `ResearchGatewayExecutor`, Crawl4AI/Scrapling routing, `ContentDiscoveryCoordinator`, the existing Mac Worker, Queue, WorkflowService and ResultStore. Add focused deterministic Content Radar modules in `picotoopet_core.autonomous`; the local `gpt-oss:20b` remains a bounded semantic labeler/judge and never receives network, filesystem, shell or arbitrary task authority.

**Tech Stack:** Python 3.12, Pydantic, existing Research Gateway/Crawl4AI adapters, existing Ollama structured adapter, pytest, native macOS arm64 package/lifecycle verification.

**Spec:** `docs/superpowers/specs/2026-08-17-autonomous-intelligence-and-storage-design.md`

## Global Constraints

- Mac Core SQLite remains the only durable fact source.
- Existing Queue/WorkflowScheduler remain the only durable scheduler family.
- Windows never executes crawler, model, shell or Content Radar work.
- Crawl4AI stays behind Research Gateway and remains read-only.
- `gpt-oss:20b` performs bounded semantic jobs only; deterministic code owns normalization, metrics, scoring and stop decisions.
- No invented engagement metrics: missing numeric evidence remains missing and contributes no fabricated score.
- Research Priority Score weights remain exactly: velocity 20, audience resonance 20, novelty 15, business relevance 15, evidence quality 10, cross-platform 10, actionability 10.
- Default thresholds remain: 85-100 deep-research eligible, 70-84 shallow validation, 0-69 retain signal only.
- Deepening stops when information gain is below 5% for two consecutive rounds or after 3 deepening rounds following initial collection.
- No account writes, login/CAPTCHA bypass, posting, messaging, purchasing, merge or release automation.

---

### Task 1: Deterministic candidate normalization and exact deduplication

**Files:**
- Create: `src/picotoopet_core/autonomous/content_radar.py`
- Test: `tests/unit/autonomous/test_content_radar_normalization.py`

**Interfaces:**
- `RadarCandidateInput`: source/evidence identifiers, canonical URL, title/text excerpt, optional platform/metrics.
- `RadarCandidate`: normalized immutable candidate with deterministic `candidate_id`, normalized URL/domain/text key and evidence IDs.
- `normalize_candidates(inputs: list[RadarCandidateInput]) -> list[RadarCandidate]`.

- [ ] Write failing tests proving URL tracking parameters/fragments are normalized, exact duplicate URLs/text collapse without losing evidence IDs, malformed/private/file URLs are rejected, and output order is deterministic.
- [ ] Run focused pytest and confirm RED because `content_radar` does not exist.
- [ ] Implement URL/text normalization and exact dedupe only; do not add fuzzy model-based dedupe.
- [ ] Run focused tests and existing autonomous discovery tests; expect GREEN.

### Task 2: Research Priority Score with missing-evidence honesty

**Files:**
- Modify: `src/picotoopet_core/autonomous/content_radar.py`
- Test: `tests/unit/autonomous/test_content_radar_scoring.py`

**Interfaces:**
- `RadarScoreSignals` contains normalized 0-1 signals or `None` for the seven score dimensions.
- `RadarScore` contains component points, `total`, `coverage`, and `decision` (`deep_research`, `shallow_validation`, `retain_signal`).
- `score_candidate(signals: RadarScoreSignals) -> RadarScore`.

- [ ] Write RED tests for exact weight mapping and threshold boundaries 85/70.
- [ ] Prove missing signals contribute zero points and reduce `coverage`; they are never silently imputed to neutral/high values.
- [ ] Implement deterministic clamping/rounding and decision thresholds.
- [ ] Run focused tests; expect GREEN.

### Task 3: Lightweight deterministic topic clustering

**Files:**
- Modify: `src/picotoopet_core/autonomous/content_radar.py`
- Test: `tests/unit/autonomous/test_content_radar_clustering.py`

**Interfaces:**
- `RadarCluster`: stable `cluster_id`, member candidate IDs, representative text, aggregated evidence IDs.
- `cluster_candidates(candidates: list[RadarCandidate], *, similarity_threshold: float = 0.45) -> list[RadarCluster]`.

- [ ] Write RED tests proving obvious token-overlap topics cluster, unrelated topics stay separate, repeated candidates cannot inflate cluster size, and ordering/IDs are stable across input order.
- [ ] Implement normalized token/Jaccard clustering with a bounded candidate count; no embeddings or network/model calls.
- [ ] Run clustering and normalization regression tests.

### Task 4: Information-gain stop policy

**Files:**
- Create: `src/picotoopet_core/autonomous/research_stop.py`
- Test: `tests/unit/autonomous/test_research_stop_policy.py`

**Interfaces:**
- `ResearchRound`: round number, evidence IDs, cluster IDs and information-gain ratio.
- `ResearchStopDecision`: `stop`, `reason`, `next_round`.
- `evaluate_research_stop(rounds: list[ResearchRound]) -> ResearchStopDecision`.

- [ ] Write RED tests for <5% twice consecutively, reset after a >=5% round, and hard stop after 3 deepening rounds beyond initial collection.
- [ ] Reject invalid negative/>1 gains and non-monotonic round numbers.
- [ ] Implement deterministic stop policy without model judgment.
- [ ] Run focused tests.

### Task 5: Integrate Radar into existing `content.discovery`

**Files:**
- Modify: `src/picotoopet_core/autonomous/discovery.py`
- Test: `tests/unit/autonomous/test_content_discovery.py`
- Create: `tests/unit/autonomous/test_content_discovery_radar_integration.py`

**Interfaces:**
- Existing task type stays `autonomous.discovery.v1`; existing capability stays `content.discovery`.
- Research Gateway results are parsed only when they contain a known enriched/search JSON envelope; legacy plain text remains bounded evidence and does not receive fabricated metrics.
- Result document adds normalized candidates, deterministic clusters, score breakdowns and stop-policy metadata while retaining raw bounded `search_evidence` traceability.

- [ ] Write RED integration tests using Crawl4AI-enriched search envelopes and legacy raw output.
- [ ] Normalize/dedupe before local Scout input so duplicate pages do not consume model context.
- [ ] Compute deterministic score components only from explicit evidence/metrics; semantic-only dimensions may be supplied by the bounded Scout result only through a closed mapping, never by free-form invented numbers.
- [ ] Run existing discovery/background/manager tests plus full Python regression.

### Task 6: Native package and lifecycle acceptance

**Files:**
- Modify only package/fixture allowlists if a newly explicit task type requires it; never broaden to wildcard task acceptance.
- Test: existing Mac Core and Mac Worker native Actions workflows.

- [ ] Run full Python/security regression on macOS arm64.
- [ ] Run ruff and shell syntax checks.
- [ ] Build and hash Mac Core/Worker offline packages.
- [ ] Exercise install, restart/recovery and rollback lifecycle fixtures.
- [ ] Confirm Windows WPF regression remains green because no Windows UI behavior changed.
- [ ] Keep formal Windows release blocked if the independent Maotai production-asset gate is still unsatisfied.
