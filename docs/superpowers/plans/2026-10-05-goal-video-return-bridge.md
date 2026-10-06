# Goal Video Return Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Accept one strictly bound manual Web GPT video return and continue it through canonical Creative adoption into the existing ComfyUI Production Job path.

**Architecture:** Verify the exact completed Goal handoff and validate a strict return against its evidence allowlist. Extend Creative Intelligence with an external-adoption seam that uses the existing quality gate, stage persistence, shared package finalizer, immutable store, and repository, then call the unchanged Production service. Reuse Result Store plus artifact provenance for durable linkage; add no lifecycle table.

**Tech Stack:** Python 3.12+, Pydantic v2, FastAPI, SQLite, pytest.

**Spec:** `docs/superpowers/specs/2026-10-05-goal-video-return-bridge-design.md`

## Global Constraints

- Base is exactly `652dc9850593a5f0756ed65fcd85faa3cd916585` on `feature/autonomous-intelligence-e2e-goal-center-2.3.27.1`.
- Manual Web GPT upload/return remains manual; no browser or paid-AI execution.
- Mac Core is the source of truth; Windows executes GPU work.
- No arbitrary provider/model/renderer/workflow/endpoint/path/command authority.
- Verified fact IDs are a subset of original handoff evidence; creative/inference content is separate.
- Creative adoption uses existing schemas, quality gate, stage persistence, package store, and repository.
- Production plans are generated only by the existing closed Production compiler.
- Identical replay is idempotent; conflicting replay fails closed; adopted artifacts are immutable.
- No Maotai or release-gate bypass.

## Review Focus

- A syntactically valid return with one unknown evidence ID must not create a Creative or Production record.
- A return bound to another Goal, package digest, or prompt version must fail before artifact adoption.
- Provider/renderer/workflow/endpoint/path/command fields or unsafe values must be rejected, including nested stage content.
- A crash before the final artifact link must still make a conflicting replay fail via the Creative idempotency/source digest.
- Restarted services must reconstruct exact Goal → Creative → Production identities without re-adopting artifacts.

---

### Task 1: Strict return and verified handoff context

**Files:**
- Create: `src/picotoopet_core/autonomous/video_return.py`
- Modify: `src/picotoopet_core/autonomous/goal_handoff_access.py`
- Modify: `src/picotoopet_core/creative/quality.py`
- Test: `tests/unit/autonomous/test_goal_video_return.py`

**Interfaces:**
- Produces: `GoalVideoReturnV1`, `GoalVideoReturnError`, `GoalHandoffContext`, `GoalHandoffAccess.context(goal_id)`, and deterministic validation/source-set helpers.
- Consumes: existing Creative stage models and forbidden-output policy.

- [ ] Write failing tests for strict extra-field rejection, completed handoff context, evidence subset validation, digest/version binding, and forbidden authority.
- [ ] Run the tests and confirm failures are caused by the missing contract/context.
- [ ] Implement the bounded models, manifest read, canonical digest, evidence validation, and synthetic source-set projection.
- [ ] Run the task tests and relevant handoff/Creative-quality tests to green.
- [ ] Commit the task.

### Task 2: Canonical Creative external adoption

**Files:**
- Create: `src/picotoopet_core/creative/package.py`
- Modify: `src/picotoopet_core/creative/service.py`
- Modify: `src/picotoopet_core/creative/execution.py`
- Modify: `src/picotoopet_core/creative/repository.py`
- Test: `tests/creative/test_creative_external_adoption.py`
- Test: `tests/integration/worker/test_creative_intelligence_worker.py`

**Interfaces:**
- Consumes: `NormalizedCreativeSourceSet`, ordered existing stage result dictionaries, fixed provenance, return digest, and generated timestamp.
- Produces: `CreativeIntelligenceService.adopt_external(...) -> CreativePackageRecord` using `CreativePackageFinalizer`; the Worker coordinator uses the same finalizer.

- [ ] Write failing tests proving external results traverse every existing quality gate, persist PASS stages, create one canonical package, reject unknown provenance, and replay immutably.
- [ ] Run the tests and confirm the adoption API/finalizer is missing.
- [ ] Extract the existing package finalization into `CreativePackageFinalizer` and make the Worker use it without changing local-package behavior.
- [ ] Implement the service adoption seam with immutable stage replay checks and no queue/model execution.
- [ ] Run Creative unit/integration tests to green and commit.

### Task 3: Goal-to-production continuation and authenticated API

**Files:**
- Modify: `src/picotoopet_core/automation/models.py`
- Modify: `src/picotoopet_core/automation/repository.py`
- Modify: `src/picotoopet_core/autonomous/video_return.py`
- Modify: `src/picotoopet_core/services.py`
- Modify: `src/picotoopet_core/api/routes/autonomous_goals.py`
- Test: `tests/integration/api/test_goal_video_return_api.py`

**Interfaces:**
- Consumes: verified handoff context, canonical return object, Creative adoption, `ProductionService.create_job()`, Result Store, and artifact provenance.
- Produces: `GoalVideoReturnService.accept/get` and `GoalVideoReturnReceipt` with exact Creative/Production linkage and current statuses.

- [ ] Write failing API tests for authentication, valid return-to-production, wrong/stale binding, extra authority, identical replay, conflict, and restart reconstruction.
- [ ] Run the tests and confirm the endpoint/service is missing.
- [ ] Add typed artifact provenance reads, compose the service, add GET/POST routes, and map bounded errors.
- [ ] Run integration tests to green and commit.

### Task 4: Regression, security, and architecture drift gate

**Files:**
- Modify only files required by failures attributable to C001.

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces: verified branch evidence and a scope-reviewed diff.

- [ ] Run the complete new C001 tests plus autonomous Goal/handoff, Creative, Production, security, and release-goal regression suites.
- [ ] Run Ruff on changed Python files.
- [ ] Inspect `git diff 652dc985..HEAD` for duplicate lifecycle/package/compiler paths, arbitrary authority, migration drift, and unrelated changes.
- [ ] Run the full Python suite and record all failures exactly; do not hide the two known baseline Storage Worker failures.
- [ ] Commit any test-backed C001 fixes, then perform the final verification pass.
