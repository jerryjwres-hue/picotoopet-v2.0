# PicotooPet AI Autonomous Slice A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the first restart-safe autonomous Mac work loop to the existing PicotooPet program without replacing the WPF shell, Mac Core database, queue, workflow scheduler, Worker, Result Store, Research Gateway, Maotai component boundary, or release lifecycle.

**Architecture:** Reuse the existing `WorkflowService`, `WorkflowScheduler`, queue leases, capability registrations, Ollama agent runtime, and managed runtime paths. Add only durable Goal metadata that existing workflow facts do not represent, a thin `AutonomousOperationsManager` that creates P3/P4 work only when existing explicit work is absent, bounded local-model task handling, an allowlisted storage lifecycle manager, and a deterministic Web GPT handoff builder. Windows changes in this slice are product identity only.

**Tech Stack:** Python 3.12, SQLite/WAL, Pydantic, existing PydanticAI/Ollama runtime, pytest, native WPF/.NET.

**Spec:** `docs/superpowers/specs/2026-08-17-autonomous-intelligence-and-storage-design.md`, `docs/superpowers/specs/2026-08-17-autonomous-storage-safety-invariants.md`, `docs/superpowers/specs/2026-08-17-incremental-integration-and-ui-preservation.md`

## Global Constraints

- Product UI name: `PicotooPet AI`; secondary Windows line: `superpower v1.0`.
- Mac Core SQLite remains the only durable fact source.
- Existing queue and existing automation scheduler remain the only durable queue/scheduler family.
- Windows never executes crawler, LLM, shell, storage cleanup, or autonomous background work.
- Mac Worker executes explicitly registered task types only.
- Autonomous P3/P4 creation yields whenever existing explicit active work exists.
- `gpt-oss:20b` is a bounded structured worker, never an unrestricted agent loop.
- Storage cleanup operates only inside new PicotooPet-managed autonomous runtime roots.
- Protected originals are never written, moved, deleted, overwritten, or compressed in place.
- Models may recommend cleanup but have no deletion authority.
- Maotai UI component remains separate and is not modified by Slice A.
- No account writes, login bypass, CAPTCHA bypass, posting, comments, DMs, likes, follows, profile changes, purchases, push/merge/release automation.

---

### Task 1: Durable autonomous Goal facts

**Files:**
- Create: `src/picotoopet_core/db/migration_019.py`
- Modify: `src/picotoopet_core/db/database.py`
- Create: `src/picotoopet_core/autonomous/models.py`
- Create: `src/picotoopet_core/autonomous/repository.py`
- Create: `src/picotoopet_core/autonomous/__init__.py`
- Test: `tests/unit/autonomous/test_goal_repository.py`

**Interfaces:**
- `PriorityClass`: P0/P1/P2/P3/P4 with stable queue priorities `0/100/300/600/900`.
- `GoalCreate`: origin, intent_type, priority_class, objective, constraints, budget_class, parent_goal_id, pinned, idempotency_key.
- `GoalRecord`: adds goal_id, workflow_id, status, score, timestamps.
- `AutonomousGoalRepository.create/get/list/bind_workflow/update_status`.

- [ ] Write failing tests proving idempotent Goal creation, restart replay, priority mapping, and schema 19.
- [ ] Run focused pytest and confirm RED because migration/models/repository do not exist.
- [ ] Add migration 19 with one `autonomous_goals` table and indexes only; do not duplicate workflow steps/tasks/results.
- [ ] Implement typed repository using existing `Database.transaction()`.
- [ ] Run focused tests and existing automation foundation tests; expect GREEN.

### Task 2: Thin Autonomous Operations Manager over existing WorkflowService

**Files:**
- Create: `src/picotoopet_core/autonomous/manager.py`
- Modify: `src/picotoopet_core/services.py`
- Test: `tests/unit/autonomous/test_manager.py`

**Interfaces:**
- `AutonomousOperationsManager.tick() -> AutonomousTickResult`.
- Manager observes existing active queue tasks before creating autonomous work.
- Manager never executes a task inline; it creates/reconciles an ordinary `WorkflowCreate`.
- One initial default P4 maintenance Goal is allowed when no explicit work exists; P3 discovery is created only when a registered discovery capability is fresh/healthy.

- [ ] Write RED tests proving explicit queue work suppresses P3/P4 creation, restart does not duplicate a Goal/workflow, and created workflows use existing queue priorities/max concurrency.
- [ ] Implement minimum manager by composing `AutonomousGoalRepository`, `WorkflowService`, `WorkflowScheduler`, and `CapabilityRouter`.
- [ ] Keep autonomous workflows at `max_concurrency=1` in Slice A.
- [ ] Run focused and automation regression tests.

### Task 3: Bounded local `gpt-oss:20b` Worker task

**Files:**
- Create: `src/picotoopet_core/autonomous/local_intelligence.py`
- Modify: `src/picotoopet_core/worker/handlers.py`
- Test: `tests/unit/autonomous/test_local_intelligence.py`
- Test: `tests/worker/test_autonomous_worker_registration.py`

**Interfaces:**
- Fixed task type: `autonomous.local_analysis.v1`.
- Fixed capability: `local.text.analysis`.
- Roles: `scout`, `filter`, `analyst`, `judge`, `editor` only.
- Payload is bounded text/evidence IDs/role; no arbitrary system prompt, tool command, path, URL fetch, or shell field.
- Handler returns a bounded ResultStore document with summary/confidence/findings/recommended_actions/evidence_ids/role/schema_version.

- [ ] Write RED contract tests for role allowlist, payload size, evidence IDs, and fixed task registration.
- [ ] Implement using the existing Ollama/PydanticAI runtime through an injectable adapter; synchronous Worker bridge uses one bounded call.
- [ ] Fail closed on invalid structured output; never convert invalid model output into a fact.
- [ ] Run agent, worker, and autonomous tests.

### Task 4: Safe autonomous storage lifecycle

**Files:**
- Modify: `src/picotoopet_core/config/paths.py`
- Create: `src/picotoopet_core/autonomous/storage.py`
- Test: `tests/unit/autonomous/test_storage_lifecycle.py`
- Security test: `tests/security/test_autonomous_storage_boundaries.py`

**Interfaces:**
- Managed roots under `RuntimePaths.autonomous_root`: `staging`, `archive`, `handoffs`, `state`.
- `StorageLifecycleManager.compact_completed(...)` writes verified gzip archive + manifest before removing its managed source.
- `StorageLifecycleManager.cleanup(...)` only deletes allowlisted disposable files whose grace period passed.
- Every run returns counts and bytes reclaimed/compressed for audit/status.

- [ ] Write RED tests proving outside-root paths are rejected, protected roots cannot be passed, source is not removed before archive hash verification, cleanup is idempotent, and useful completed data is compressed.
- [ ] Implement allowlist/path containment checks before every mutation.
- [ ] Do not touch existing ResultStore objects in Slice A.
- [ ] Run storage/security tests.

### Task 5: Fixed Web GPT production handoff

**Files:**
- Create: `src/picotoopet_core/autonomous/handoff.py`
- Create: `src/picotoopet_core/autonomous/prompts/web_gpt_master_v1.txt`
- Test: `tests/unit/autonomous/test_web_gpt_handoff.py`

**Interfaces:**
- `WebGptHandoffBuilder.build(goal, analysis, evidence, sources, creative_brief) -> Path`.
- Deterministic ZIP includes the versioned files specified by the design and `WEB_GPT_MASTER_PROMPT.txt`.
- Manifest includes prompt version, source/evidence IDs, per-file SHA-256, creation time, and no raw protected source paths.

- [ ] Write RED tests for exact required files, fixed prompt version, SHA manifest, evidence traceability, and rejection of unsafe source paths/secrets.
- [ ] Implement deterministic package staging in `autonomous_handoffs_dir` and final ZIP.
- [ ] Verify package contents and ZIP integrity in tests.

### Task 6: Product identity without UI redesign

**Files:**
- Modify: `windows/desktop/src/PicotooPet.Desktop/Versioning/ProductVersionInfo.cs`
- Modify: `windows/desktop/src/PicotooPet.Desktop/Views/ShellWindow.xaml`
- Test: `tests/contract/test_picotoopet_ai_product_identity.py`

**Interfaces:**
- Window title contains `PicotooPet AI` and existing four-part product version.
- Left rail primary name becomes `PicotooPet AI`.
- Existing `ControlCenterSubtitle` remains version-aware; a separate small visible line displays `superpower v1.0`.
- No navigation/page/layout replacement and no Maotai asset/component changes.

- [ ] Write RED source contract for exact product identity while asserting Maotai `AssistantPetPanel` host is preserved.
- [ ] Apply only text/small-label changes to the existing shell.
- [ ] Run Python UI contracts and native WPF build/smoke.

### Task 7: Background bootstrap and fresh verification

**Files:**
- Modify only the existing Mac service/bootstrap composition point determined during implementation; do not add a Mac GUI.
- Test: integration test under `tests/integration/` for restart/reconcile.

**Interfaces:**
- Background loop periodically calls existing workflow reconciliation plus `AutonomousOperationsManager.tick()`.
- Exceptions in one autonomous tick are isolated/logged and do not terminate Mac Core/Worker.
- Shutdown is cooperative; restart replays durable Goal/workflow facts.

- [ ] Write RED restart/exception-isolation integration test.
- [ ] Wire the thin manager into existing Mac background service loop.
- [ ] Run full Python suite/security contracts.
- [ ] Run native Windows WPF build/smoke because shared contracts/UI identity changed.
- [ ] Do not generate a formal release package until all existing release gates, including the independent Maotai production-asset gate, are satisfied; a UI/feature acceptance package may remain explicitly non-final if those gates are still blocked.
