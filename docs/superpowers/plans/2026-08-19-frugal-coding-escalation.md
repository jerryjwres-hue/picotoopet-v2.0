# Frugal Coding Escalation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Core-owned frugal escalation arbiter that keeps coding work local when confidence is sufficient, otherwise selects at most one bounded Codex or Claude Code session initially, with a hard two-session maximum and no automatic retry.

**Architecture:** Preserve Mac Core as source of truth and reuse the existing Codex provider/worktree/return pipeline. Add a deterministic score/confidence/history module in Core plus a symmetric, more restrictive Claude Code Worker adapter. Provider choice and budget remain trusted policy facts; Windows only reads the decision projection.

**Tech Stack:** Python 3.12, Pydantic, SQLite/Core repositories, existing Worker bounded process runner, pytest, Ruff, Bash/macOS packaging, WPF/.NET Windows regression contracts.

**Spec:** `docs/superpowers/specs/2026-08-19-frugal-coding-escalation-design.md`

## Global Constraints

- Mac Core remains the only source of truth.
- Windows cannot choose provider/model/budget/argv or execute shell/crawlers.
- Coding agents are not eligible for ordinary research/content/video goals.
- Default external coding sessions per Goal: 1; absolute max: 2.
- Automatic provider retries: 0; external concurrency: 1.
- Codex existing worktree/return safety path is reused, not replaced.
- Claude Code must never use `--dangerously-skip-permissions`; Bash, WebFetch/WebSearch, MCP and agent spawning remain disallowed.
- No auto-login, credential capture, plan purchase, budget enlargement or Natural Motion V2 gate bypass.

---

### Task 1: Frugal scoring, confidence band and Wilson history

**Files:**
- Create: `src/picotoopet_core/deep_ai/frugal.py`
- Modify: `src/picotoopet_core/deep_ai/models.py`
- Test: `tests/unit/deep_ai/test_frugal.py`

**Interfaces:**
- Produces: `wilson95(successes: int, trials: int) -> tuple[float, float]`
- Produces: `FrugalEscalationInput`, `ProviderHistorySnapshot`, `ProviderCandidate`, `ProviderEscalationDecision`
- Produces: `FrugalEscalationArbiter.decide(input: FrugalEscalationInput) -> ProviderEscalationDecision`

- [ ] **Step 1: Write failing tests** for zero/small/large Wilson samples, high-confidence local-only, non-coding ineligibility, conservative sparse history, deterministic Codex/Claude choice, and hard two-session cap.
- [ ] **Step 2: Run focused tests and verify RED** with missing `deep_ai.frugal` / missing decision models.
- [ ] **Step 3: Implement minimal deterministic models and arbiter.** Normalize score to `0..100`; clamp all confidence fields to `0..1`; use lower confidence bound for policy; encode reason codes; use cold-start Codex tie-break only when utilities are equal/insufficient-history.
- [ ] **Step 4: Run focused tests and verify GREEN.**
- [ ] **Step 5: Commit** `feat: add frugal coding escalation arbiter`.

### Task 2: Persist and expose immutable Core decisions

**Files:**
- Create: `src/picotoopet_core/deep_ai/frugal_repository.py`
- Modify: Core migration/schema files selected by existing project pattern
- Modify: `src/picotoopet_core/deep_ai/learning.py` only as needed to aggregate provider terminal outcomes
- Modify: existing Deep-AI API route or add a narrowly scoped read-only decision route following current route structure
- Test: `tests/integration/api/test_frugal_escalation_api.py`
- Test: repository/migration tests under existing `tests/unit/db` or `tests/unit/deep_ai`

**Interfaces:**
- Consumes: `ProviderEscalationDecision`
- Produces: replay-safe durable decision keyed by `decision_digest`
- Produces: read-only API projection; no client provider/budget override fields

- [ ] **Step 1: Write failing repository/API tests** proving decision durability, digest stability, idempotent replay, and rejection/absence of provider/model/budget override inputs.
- [ ] **Step 2: Run focused tests and verify RED.**
- [ ] **Step 3: Implement migration/repository/API with Core-owned fields only.**
- [ ] **Step 4: Run focused tests and verify GREEN.**
- [ ] **Step 5: Commit** `feat: persist frugal escalation decisions`.

### Task 3: Add bounded Claude Code adapter and readiness contract

**Files:**
- Create: `src/picotoopet_core/worker/claude_code_adapter.py`
- Create or modify: provider readiness helper following existing Codex readiness pattern
- Modify: provider model literals to support `codex` and `claude_code` without weakening existing budgets
- Test: `tests/unit/worker/test_claude_code_adapter.py`
- Test: existing Codex tests/contracts as regression

**Interfaces:**
- Produces task type: `provider.claude-code.handoff-v1`
- Produces: `ClaudeCodeAdapter.build_argv() -> list[str]`
- Produces bounded result metadata without raw prompt/transcript/secrets

- [ ] **Step 1: Write failing adapter tests** asserting fixed executable/argv, non-interactive JSON output, fixed turn/timeout cap, isolated cwd, no automatic retry, and explicit absence of `--dangerously-skip-permissions`.
- [ ] **Step 2: Add security tests** asserting Bash, WebFetch, WebSearch, MCP/agent-spawn capabilities cannot be enabled through payload or argv.
- [ ] **Step 3: Run tests and verify RED.**
- [ ] **Step 4: Implement adapter using existing `BoundedProcessRunner`.** Keep stdin/prompt bounded; parse only safe machine-readable result metadata; never retain raw stderr/transcript in official result.
- [ ] **Step 5: Add readiness probe** that reports `ready`, `not_authenticated`, `unavailable` or `policy_blocked` without reading credential files.
- [ ] **Step 6: Run Claude + Codex focused tests and verify GREEN.**
- [ ] **Step 7: Commit** `feat: add bounded claude code provider adapter`.

### Task 4: Wire provider execution to the frugal decision without creating a new execution plane

**Files:**
- Modify: existing provider session/execution service files under `src/picotoopet_core/providers/`
- Modify: existing Worker registration path under `src/picotoopet_core/worker/`
- Modify: relevant Deep-AI continuation/promotion path only where a coding-class escalation is created
- Test: `tests/integration/providers/test_frugal_provider_routing.py`
- Test: existing provider session/return validation suites

**Interfaces:**
- Consumes: persisted `ProviderEscalationDecision`
- Produces: zero provider tasks for `LOCAL_ONLY`/ineligible decisions; exactly one initial fixed provider task for an allowed choice
- Produces: optional second-provider decision only after first terminal local validation failure/uncertainty and remaining cap

- [ ] **Step 1: Write failing routing tests** proving research/content/video goals never queue coding providers, high-confidence local results queue none, selected provider queues exactly one task, provider PASS stops spending, and second-provider path requires failed/uncertain local validation plus remaining budget.
- [ ] **Step 2: Run focused tests and verify RED.**
- [ ] **Step 3: Generalize provider literals/dispatch minimally** so existing Codex sessions continue to work and Claude Code uses the same isolated worktree/return validation lifecycle.
- [ ] **Step 4: Register `provider.claude-code.handoff-v1` only when readiness/policy is healthy.**
- [ ] **Step 5: Run provider + Worker integration tests and verify GREEN.**
- [ ] **Step 6: Commit** `feat: route coding escalation through frugal provider policy`.

### Task 5: Operator projection, install verification and native delivery

**Files:**
- Modify: Windows Deep-AI/Goal Center read-only status projection and XAML only as needed to display local score/confidence/provider decision
- Modify: `deploy/macos/phase23-worker/README_INSTALL_CN.txt`
- Modify: `deploy/macos/phase23-worker/VERIFY_GOAL_CENTER_E2E.command` or add a narrowly named strict provider verifier while preserving existing Goal Center verifier semantics
- Modify: Mac Core/Worker build content contracts so `frugal.py` and `claude_code_adapter.py` must be present in packaged wheel
- Test: Windows contracts + Mac package content contracts

**Interfaces:**
- Windows displays decision explanation but has no provider/budget override control.
- Real-machine verifier reports Codex and Claude Code readiness separately and clearly marks login/authentication as user action.

- [ ] **Step 1: Write failing package/UI contracts** requiring arbiter, both provider adapters, decision fields, and absence of provider-choice/budget-edit UI.
- [ ] **Step 2: Run contracts and verify RED.**
- [ ] **Step 3: Implement minimal read-only UI copy and strict package/live verification.**
- [ ] **Step 4: Run focused Python/WPF/package contracts and verify GREEN.**
- [ ] **Step 5: Run full Mac Core native CI, Mac Worker native CI and Windows Control Center CI.**
- [ ] **Step 6: Confirm formal Windows release still fails only on the existing Natural Motion V2 real-asset gate if assets remain absent.**
- [ ] **Step 7: Download and independently verify new Core/Worker artifacts, then rebuild the combined delivery ZIP with updated manifest/SHA/install order.**
- [ ] **Step 8: Add final evidence to Draft PR #41 and commit** `docs: record frugal escalation delivery evidence`.

## Self-review

- Spec coverage: all frozen boundaries, confidence semantics, Wilson history, provider selection, second-provider cap, adapters, readiness, Windows projection and real-machine acceptance map to Tasks 1-5.
- Placeholder scan: no deferred implementation requirements.
- Type consistency: `ProviderEscalationDecision` is defined in Task 1, persisted in Task 2, consumed in Task 4 and projected in Task 5; provider names are exactly `codex` and `claude_code`.
