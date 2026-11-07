# Issue #231-B Owner Structured Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver an authenticated Proposal → Preview → Atomic Commit API that creates source-bound `state_facts.v1` in the canonical evidence ledger.

**Architecture:** A dedicated Core review service resolves Goal/source/evidence snapshots and performs all digest and authority checks. A separate owner-authenticated router exposes the service, while the existing ledger gains transaction-aware batch ingestion for atomic commit and idempotence.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLite, pytest, Ruff.

**Spec:** `docs/superpowers/specs/2026-11-06-issue-231-owner-structured-review-design.md`

## Global Constraints

- Exact base: `496016e2fcb5ef6a77350c36dd305db969dd0035`.
- Do not modify `security/owner_principal.py`, `security/owner_auth.py`, `config/owner_registry.py`, `creative/state_spine.py`, Windows, Story Gate, Worker or GPU code.
- No database migration, deployment, Goal/model/GPU execution or real owner data.
- Existing Owner Evidence APIs and historical records remain unchanged.
- All production behavior is implemented test-first.

## Review Focus

- A valid actor attempting another Goal subject must receive 403 without evidence disclosure (Task 3).
- A source change between Preview and Commit must return 409 before any write (Task 2).
- Existing free text must never become a typed identity value (Task 1).
- Same idempotency key with mutated body must return 409, while exact replay is byte-equivalent (Task 2).
- A late batch conflict must roll back earlier inserts in the same transaction (Task 2).

---

### Task 1: Proposal and side-effect-free Preview

**Files:**
- Create: `src/picotoopet_core/autonomous/owner_structured_review.py`
- Create: `tests/unit/autonomous/test_owner_structured_review.py`

**Interfaces:**
- Consumes: `OwnerPrincipal`, `StateFactsV1`, `CanonicalEvidenceLedger`, Goal/source tables.
- Produces: strict request/response contracts and `OwnerStructuredReviewService.proposal()` / `.preview()`.

- [ ] Write failing tests for deterministic Proposal, free-text UNKNOWN behavior, strict field decisions, authority assignment, `NEEDS_HUMAN`, actor mismatch and preview zero writes.
- [ ] Run `uv run pytest -q tests/unit/autonomous/test_owner_structured_review.py` and verify missing-module/API failures.
- [ ] Implement the minimal contracts, snapshot resolver, digest builder and preview assembler without persistence.
- [ ] Run the same test command and verify PASS.
- [ ] Commit with `feat(core): add owner structured review proposal and preview`.

### Task 2: Canonical atomic Commit and replay safety

**Files:**
- Modify: `src/picotoopet_core/autonomous/evidence_ledger.py`
- Modify: `src/picotoopet_core/autonomous/owner_structured_review.py`
- Modify: `tests/unit/autonomous/test_owner_structured_review.py`
- Modify: `tests/unit/autonomous/test_evidence_ledger.py`

**Interfaces:**
- Consumes: Task 1 preview contracts and digests.
- Produces: `CanonicalEvidenceLedger.ingest_batch[_in_transaction]()` and `OwnerStructuredReviewService.commit()`.

- [ ] Write failing tests for atomic batch rollback, exact replay, replay mutation, stale evidence/source, evidence binding verification and unchanged pre-existing rows.
- [ ] Run the focused unit tests and verify failures are caused by missing commit/batch behavior.
- [ ] Implement transaction-aware ledger ingestion and commit-time digest/source/actor recomputation.
- [ ] Run the focused unit tests and verify PASS.
- [ ] Commit with `feat(core): atomically commit reviewed state facts`.

### Task 3: Authenticated API and frozen OpenAPI

**Files:**
- Create: `src/picotoopet_core/api/routes/owner_structured_reviews.py`
- Modify: `src/picotoopet_core/api/app.py`
- Create: `tests/integration/api/test_owner_structured_review_api.py`
- Modify: `tests/contract/test_exported_contracts.py`
- Modify: `contracts/openapi/mac_core_v1.openapi.json`
- Create: `docs/p0_video_quality/OWNER_STRUCTURED_REVIEW_V1.md`

**Interfaces:**
- Consumes: Task 1/2 service and PR #234 owner auth dependency.
- Produces: three `/api/v1/owner-structured-reviews/...` routes and frozen request/response examples.

- [ ] Write failing loopback API tests covering 401/403/404/409/422, successful flow, no-write Preview and OpenAPI examples.
- [ ] Run the API/contract tests and verify missing-route/contract failures.
- [ ] Implement the router, app registration, error mapping and documentation examples.
- [ ] Export `contracts/openapi/mac_core_v1.openapi.json` with the existing exporter.
- [ ] Run API, contract, owner-auth, ledger and StateFacts tests plus Ruff and verify PASS.
- [ ] Commit with `docs(api): freeze owner structured review contract`.

### Task 4: Whole-branch verification and delivery

**Files:**
- Verify all changed files; no new production scope.

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces: final exact SHA, remote branch, Draft PR and native Core/Worker CI run IDs.

- [ ] Run the full local pytest suite and changed-file Ruff; classify any environment-only failure without changing unrelated production code.
- [ ] Verify auth/config/State Spine protected files are byte-identical to base and review the complete diff.
- [ ] Push the branch without force, create a Draft PR referencing #231, and trigger/observe native Mac Core and Worker workflows for the exact SHA.
- [ ] Record final SHA, CI run IDs, OpenAPI digest and no-deployment status.
