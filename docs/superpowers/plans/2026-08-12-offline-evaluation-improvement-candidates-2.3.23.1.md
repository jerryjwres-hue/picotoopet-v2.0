# PicotooPet 2.3.23.1 — Offline Evaluation + Improvement Candidates Implementation Plan

Design: `docs/superpowers/specs/2026-08-12-offline-evaluation-improvement-candidates-2.3.23.1-design.md`
Base: frozen 2.3.22.1 feature head `f018aa538253b12a72dca859981c37c8bd7bd685`
Branch: `feature/offline-evaluation-improvement-candidates-2.3.23.1`
Product: `2.3.23.1`
Database schema: `16`

## Execution rules

- Follow RED → GREEN for every contract group.
- Preserve migrations 1–15 and every 2.3.22.1 paid-AI safety invariant.
- Evaluation is deterministic Core-side computation; no local/paid model call is introduced.
- `AcceptedForShadow` is a durable review fact only and must perform zero runtime policy mutation.
- No ordinary test/CI/package failure is a human-approval stop; investigate, fix, and rerun.
- Keep the PR Draft/Open/Unmerged. Do not merge `main`, create tags/releases, enable real paid execution, or perform a real paid request.

## Task 1 — RED: schema 16 and database contract

**Files**
- Add `tests/unit/db/test_quality_evaluation_migration.py`
- Update `tests/unit/db/test_migrations.py`

**RED assertions**
1. `Database.apply_migrations()` records exactly 16 migrations.
2. Schema 16 creates:
   - `quality_evaluation_snapshots`
   - `quality_evaluation_snapshot_members`
   - `quality_evaluation_runs`
   - `quality_evaluation_metrics`
   - `quality_improvement_candidates`
   - `quality_improvement_candidate_reviews`
3. Existing schema 15 tables remain present.
4. Reapplying migrations is idempotent.
5. Foreign-key and uniqueness constraints reject invalid or duplicate durable identities.

**Expected RED**
- Current 2.3.22.1 schema stops at 15 and has none of the new tables.

## Task 2 — RED: evaluation repository/service behavior

**Files**
- Add `tests/deep_ai/test_quality_evaluation.py`

**RED assertions**
1. A snapshot consumes only existing `deep_ai_learning_events` + `deep_ai_learning_details` facts for one project.
2. Snapshot membership is immutable, digest-bound, ordered, capped at 10,000 facts, and idempotent.
3. Snapshot rows contain normalized facts/digests only; no API key, absolute path, raw package/blob, URL, SQL, prompt, or workflow payload is copied.
4. `quality.offline.v1` computes explicit numerator/denominator metrics and preserves unavailable values as `None` / `not_available`.
5. Cohorts below five human-decision samples are `insufficient_sample` and cannot independently create candidates.
6. Candidate trigger thresholds are exact for all five frozen rules:
   - `PROMPT_REVIEW`
   - `LOCAL_REASONING_REVIEW`
   - `EVIDENCE_SELECTION_REVIEW`
   - `PAID_ESCALATION_REVIEW`
   - `COST_POLICY_REVIEW`
7. Candidate generation is idempotent on `(evaluation_run_id, rule_version, candidate_class, cohort_digest)`.
8. Review facts are append-only/idempotent and enforce the closed lifecycle.
9. `AcceptedForShadow` changes no Deep-AI job/provider/model/budget/prompt/config state and creates no attempt/provider request.
10. Terminal 2.3.22.1 escalation history is readable as evaluation input but cannot be reopened or made paid-execution eligible.

**Expected RED**
- `picotoopet_core.deep_ai.evaluation` does not exist.

## Task 3 — GREEN: schema 16 persistence

**Files**
- Add `src/picotoopet_core/db/migration_016.py`
- Update `src/picotoopet_core/db/database.py`

**Implementation**
- Mirror the transaction/rollback style of migration 15.
- Add normalized snapshot/member/run/metric/candidate/review tables and indexes.
- Use immutable identity/digest uniqueness constraints.
- Register migration 16 and set `LATEST_SCHEMA_VERSION = 16`.

**Verification**
- Run migration RED tests and existing migration suite until GREEN.

## Task 4 — GREEN: deterministic evaluation domain

**Files**
- Add `src/picotoopet_core/deep_ai/evaluation.py`

**Implementation**
- Add frozen Pydantic models for scope, snapshot, metric/cohort, evaluation run/report, candidate, and review.
- Add `QualityEvaluationRepository` backed by schema 16.
- Add `QualityEvaluationService` that:
  - selects existing project-scoped learning facts using closed scope fields;
  - canonicalizes selected fact identities/digests;
  - creates immutable snapshots;
  - computes `quality.offline.v1` metrics deterministically;
  - emits the five closed candidate classes at frozen thresholds;
  - records bounded review facts without runtime mutation.
- Query `deep_ai_learning_events` / `deep_ai_learning_details` directly as immutable source facts; do not duplicate raw source payloads.
- Preserve terminal Deep-AI history as read-only evidence only.

**Verification**
- Run `tests/deep_ai/test_quality_evaluation.py` plus existing Deep-AI/learning/terminal-control-plane tests.

## Task 5 — RED/GREEN: authenticated API boundary

**Files**
- Update `src/picotoopet_core/services.py`
- Update `src/picotoopet_core/api/routes/deep_ai.py`
- Update `tests/integration/api/test_deep_ai_api.py`

**Public endpoints**
- `POST /api/v1/deep-ai/evaluation-snapshots`
- `GET /api/v1/deep-ai/evaluation-snapshots`
- `GET /api/v1/deep-ai/evaluation-snapshots/{snapshot_id}`
- `POST /api/v1/deep-ai/evaluations`
- `GET /api/v1/deep-ai/evaluations`
- `GET /api/v1/deep-ai/evaluations/{evaluation_run_id}`
- `POST /api/v1/deep-ai/evaluations/{evaluation_run_id}/reconcile`
- `GET /api/v1/deep-ai/improvement-candidates`
- `GET /api/v1/deep-ai/improvement-candidates/{candidate_id}`
- `POST /api/v1/deep-ai/improvement-candidates/{candidate_id}/review`

**Boundary**
- Create/reconcile contracts accept only the frozen scope/review fields.
- Pydantic `extra="forbid"` rejects prompt/model/provider/endpoint/key/budget/tools/command/shell/path/workflow/sql/formula injections.
- Authentication remains mandatory.
- No worker/provider execution endpoint is added for evaluation.

**Verification**
- First capture API RED, then implement and run integration API tests to GREEN.

## Task 6 — RED/GREEN: Windows contracts, client, session and UI

**Files**
- Update `windows/desktop/src/PicotooPet.Desktop.Core/Contracts/DeepAiContracts.cs`
- Update `windows/desktop/src/PicotooPet.Desktop.Core/Networking/MacCoreClient.DeepAi.cs`
- Update `windows/desktop/src/PicotooPet.Desktop/Services/ControlCenterSession.DeepAi.cs`
- Add `windows/desktop/src/PicotooPet.Desktop/ViewModels/QualityEvaluationPanelViewModel.cs`
- Add `windows/desktop/src/PicotooPet.Desktop/Views/QualityEvaluationPanel.xaml`
- Add `windows/desktop/src/PicotooPet.Desktop/Views/QualityEvaluationPanel.xaml.cs`
- Update `windows/desktop/src/PicotooPet.Desktop/ViewModels/BusinessAutomationPageViewModel.cs`
- Update `windows/desktop/src/PicotooPet.Desktop/Views/Pages/BusinessAutomationPage.xaml`
- Update `windows/desktop/src/PicotooPet.Desktop/Views/Pages/BusinessAutomationPage.xaml.cs`
- Add `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/QualityEvaluationClientSmokeTests.cs`
- Add `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/QualityEvaluationPanelWpfSmokeTests.cs`

**RED assertions**
- Exact REST paths and closed JSON payloads.
- No free-form prompt/model/provider/endpoint/formula controls.
- Candidate display is read-only.
- Every record-only binding is explicit `Mode=OneWay`.
- Real STA WPF construction + `Measure` + `Arrange` + `UpdateLayout` succeeds.

**GREEN implementation**
- Reuse the existing Deep-AI client/session patterns.
- Embed `质量评估` under Business Automation; add no new Shell route.
- Expose only project/scope selection, create/refresh, immutable metrics, candidates, and bounded review actions.

## Task 7 — RED/GREEN: product/schema rollup and cumulative contracts

**Files**
- Update the authoritative product-version/schema files discovered by existing release tests.
- Update `windows/desktop/src/PicotooPet.Desktop/Versioning/ProductVersionInfo.cs` and matching Windows version contracts.
- Update `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/ProductVersionWpfSmokeTests.cs`.
- Update Python release/contract tests that freeze product version and migration count.

**Required values**
- product version `2.3.23.1`
- database schema `16`

**Cumulative requirement**
- Migration 10→16 retained.
- 18.1 Business, 19.1 Creative, 20.1 ComfyUI Production, 21.1 End-to-End, 22.1 Paid-AI + Quality Learning all remain present.
- Real paid execution remains disabled by default.

## Task 8 — Native exact-head CI, focused fixes, and release freeze

1. Open a Draft PR stacked on `feature/paid-ai-quality-learning-2.3.22.1` after RED evidence is committed.
2. Capture expected RED on the native gates where practical.
3. Commit GREEN implementation in focused changes.
4. Run/re-run until all exact-head native gates are SUCCESS:
   - Mac Core Slice B CI
   - Mac Worker Slice D CI
   - Windows Control Center Slice D CI
   - Windows Prebuilt Release
5. Treat ordinary failures with systematic debugging: read exact log, reproduce by contract where possible, make one root-cause fix, rerun.
6. Keep PR Draft/Open/Unmerged and do not modify `main`.

## Task 9 — Formal artifacts and independent verification

Download exact-head artifacts and independently verify:

- Mac Core arm64 prebuilt package + sidecar SHA;
- Mac Worker arm64 prebuilt package + sidecar SHA;
- Windows win-x64 prebuilt package + sidecar SHA;
- source/build tree equality;
- safe single archive root, no traversal/duplicates;
- no unexpected Mac links/special files;
- manifest hashes/sizes;
- Windows PE AMD64;
- install / verify / rollback presence;
- Windows install / upgrade / recovery / rollback lifecycle evidence;
- schema 16 and migration 10→16 presence in the formal Core wheel;
- 23.1 evaluation runtime present;
- zero real paid calls in CI/package verification.

Create:
- unified SHA-256 list;
- delivery manifest;
- independent verification JSON;
- cumulative Chinese real-machine acceptance checklist.

Freeze the exact 23.1 package identities. Any later real-machine defect must become a patch version (for example 2.3.23.2), never a silent replacement of frozen 2.3.23.1 artifacts.

## Task 10 — FULL-EVIDENCE handoff refresh

After package freeze, create a new FULL-EVIDENCE handoff that embeds:

- design + implementation plan;
- Draft PR/source/build identity;
- RED/GREEN evidence;
- exact-head CI evidence;
- formal Mac Core / Mac Worker / Windows packages;
- raw Actions artifacts where useful;
- SHA/manifest/independent verification;
- cumulative acceptance checklist;
- updated architecture/operations/security decisions;
- next-chat continuation prompt.
