# PicotooPet 2.3.24.1 Controlled Shadow Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic, offline, restart-safe `quality.shadow.v1` validation for 2.3.23.1 `AcceptedForShadow` Improvement Candidates and ship cumulative 2.3.24.1 prebuilt Mac Core, Mac Worker, and Windows packages.

**Architecture:** Mac Core adds schema 17 plus a dedicated shadow repository/service that reuses immutable evaluation snapshot members, performs a source-controlled split, recomputes frozen candidate trigger metrics per arm, and persists a fact-only verdict/review trail. Mac Worker receives no new execution authority. Windows extends the existing Quality Evaluation panel with bounded create/refresh/review controls and no free-form execution policy fields.

**Tech Stack:** Python 3.13, FastAPI, Pydantic v2, SQLite, pytest, ruff, C#/.NET 8 WPF, GitHub Actions native macOS/Windows packaging.

## Global Constraints

- Product version: `2.3.24.1`.
- Database schema: `17`.
- Base head: `4a19528868b835a8b214f0aff11e7215b31f97d3`.
- Shadow profile: `quality.shadow.v1`.
- Split version: `quality.shadow.split.v1`.
- Eligible candidate state: exactly `AcceptedForShadow`.
- Shadow validation uses immutable schema-16 snapshot members only.
- Zero local-AI, paid-AI, ComfyUI, shell/browser/Git/GitHub/publication execution.
- Zero prompt/model/provider/endpoint/budget/workflow mutation.
- No automatic promotion; `AcceptedForPromotionReview` is a review fact only.
- No source compilation on user Mac/Windows machines.
- Final PR remains Draft/Open/Unmerged; no main merge, tag, or GitHub Release.

---

### Task 1: RED contract and migration tests

**Files:**
- Create: `tests/unit/db/test_quality_shadow_migration.py`
- Create: `tests/deep_ai/test_quality_shadow_validation.py`
- Create: `tests/integration/api/test_quality_shadow_api.py`
- Create: `docs/superpowers/red/2026-08-12-controlled-shadow-validation-2.3.24.1-red.md`

**Interfaces:**
- Consumes: schema-16 `quality_improvement_candidates`, `quality_evaluation_runs`, `quality_evaluation_snapshots`, snapshot members and learning facts.
- Produces: executable requirements for schema 17 and the `QualityShadowService` public contract.

- [ ] Add migration RED asserting schema version 17 and tables `quality_shadow_runs`, `quality_shadow_arm_metrics`, `quality_shadow_reviews`.
- [ ] Add service RED for exact `AcceptedForShadow` eligibility, idempotent run identity, deterministic split/reconcile, three verdicts, zero paid attempts and no candidate-state mutation.
- [ ] Add review RED for bounded actions and fact-only `AcceptedForPromotionReview`.
- [ ] Add API RED for create/get/list/reconcile/metrics/review and forbidden extra fields.
- [ ] Run focused native/Python CI-capable tests and capture expected RED evidence before production files exist.

### Task 2: Schema 17 and deterministic shadow domain

**Files:**
- Create: `src/picotoopet_core/db/migration_017.py`
- Modify: `src/picotoopet_core/db/database.py`
- Create: `src/picotoopet_core/deep_ai/shadow.py`

**Interfaces:**
- `QualityShadowRepository(database: Database)`.
- `QualityShadowService(repository: QualityShadowRepository, evaluation_repository: QualityEvaluationRepository)`.
- `create(candidate_id: str) -> QualityShadowRun`.
- `reconcile(shadow_run_id: str) -> QualityShadowRun`.
- `get_run`, `list_runs`, `list_metrics`, `review`.

- [ ] Add normalized schema-17 tables with immutable candidate/source digests, one run per candidate, arm metric uniqueness and idempotent review facts.
- [ ] Add frozen Pydantic models with `extra="forbid"` and digest validation.
- [ ] Add exact candidate/source eligibility checks.
- [ ] Derive logical samples from the immutable snapshot using the existing 2.3.23.1 grouping semantics.
- [ ] Split samples by SHA-256 of `split_version + candidate_digest + sample_key` into `baseline`/`shadow`.
- [ ] Recompute only the frozen trigger metrics for the candidate class with explicit numerators/denominators and missing-data semantics.
- [ ] Derive `Supported`, `NeedsMoreData`, or `NotReproduced` deterministically.
- [ ] Persist/reconcile derived facts under the same run identity; never reserve paid attempts or mutate candidate/Deep-AI execution state.
- [ ] Implement append-only/idempotent bounded shadow reviews.
- [ ] Run focused tests until GREEN.

### Task 3: Service container and authenticated API

**Files:**
- Modify: `src/picotoopet_core/services.py`
- Modify: `src/picotoopet_core/api/routes/deep_ai.py`

**Interfaces:**
- `POST /deep-ai/shadow-runs` body `{candidate_id}`.
- `GET /deep-ai/shadow-runs` with optional candidate filter and bounded limit.
- `GET /deep-ai/shadow-runs/{shadow_run_id}`.
- `POST /deep-ai/shadow-runs/{shadow_run_id}/reconcile` empty body.
- `GET /deep-ai/shadow-runs/{shadow_run_id}/metrics`.
- `POST /deep-ai/shadow-runs/{shadow_run_id}/review` with closed action and idempotency key.

- [ ] Wire repository/service into `Services` and `build_services`.
- [ ] Add strict request models and bounded route handlers using existing Deep-AI error translation.
- [ ] Reject arbitrary prompt/model/endpoint/key/budget/tool/command/path/workflow/sql/formula/threshold/split/seed fields through `extra="forbid"`.
- [ ] Run focused integration tests until GREEN.

### Task 4: Windows bounded Shadow Validation UX

**Files:**
- Modify: `windows/desktop/src/PicotooPet.Desktop.Core/Contracts/DeepAiContracts.cs`
- Modify: `windows/desktop/src/PicotooPet.Desktop.Core/Networking/MacCoreClient.DeepAi.cs`
- Modify: `windows/desktop/src/PicotooPet.Desktop/Services/ControlCenterSession.DeepAi.cs`
- Modify: `windows/desktop/src/PicotooPet.Desktop/ViewModels/QualityEvaluationPanelViewModel.cs`
- Modify: `windows/desktop/src/PicotooPet.Desktop/Views/QualityEvaluationPanel.xaml`
- Modify/create Windows smoke tests for client contracts and WPF layout.

**Interfaces:**
- Closed DTOs mirror Core shadow-run/metric/review models only.
- Create accepts selected candidate ID only.
- Review exposes `Reviewed`, `AcceptedForPromotionReview`, `Rejected`, `Cancelled` only.

- [ ] Add DTOs/client/session methods without free-form policy fields.
- [ ] Add ViewModel state/commands that enable create only for selected `AcceptedForShadow` candidate.
- [ ] Add `影子验证` section inside existing Quality Evaluation surface; record-only bindings use `Mode=OneWay`.
- [ ] Add real STA `Measure/Arrange/UpdateLayout` smoke and source-contract assertions.
- [ ] Run Windows analyzer/warnings-as-errors/WPF smoke until GREEN.

### Task 5: Version and cumulative release contracts

**Files:**
- Modify: `src/picotoopet_core/product-version.txt`
- Modify: `contracts/release/project-goal-invariants.json`
- Modify: cumulative product/version tests that intentionally pin the newest target.
- Update Windows product version surfaces as required by existing release contract.

- [ ] Roll cumulative product identity to `2.3.24.1` and schema to `17` without deleting 18–23 functionality.
- [ ] Update only tests/contracts whose purpose is the newest cumulative release identity; preserve historical-version tests where they intentionally validate older slices.
- [ ] Run Python full regression + ruff and Windows native build/smoke.

### Task 6: Draft PR and exact-head native CI

**Files:**
- Create/update: Draft PR body and release evidence only.

- [ ] Open a Draft PR stacked directly on `feature/offline-evaluation-improvement-candidates-2.3.23.1`.
- [ ] Verify exact feature head and source tree.
- [ ] Run/observe Mac Core Slice B, Mac Worker Slice D, Windows Control Center, and Windows Prebuilt workflows.
- [ ] On ordinary failures, inspect logs, patch the feature branch, and rerun until all four exact-head gates are GREEN.
- [ ] Keep PR Draft/Open/Unmerged.

### Task 7: Prebuilt package extraction and independent verification

**Files:**
- User-visible artifacts under `/mnt/data` only; do not commit binaries to source.

- [ ] Download the final exact-head Mac Core, Mac Worker, and Windows Actions artifacts.
- [ ] Extract the three formal installer packages and sidecar SHA-256 files.
- [ ] Recalculate wrapper and formal package SHA-256 independently.
- [ ] Verify safe single-root archives, no traversal/duplicates, no unsafe Mac link/special payload, correct arm64/AMD64 target, version `2.3.24.1`, migration 17, INSTALL/VERIFY/ROLLBACK, and source/build tree identity evidence available from CI.
- [ ] Produce a final installer bundle and manifest in `/mnt/data`.
- [ ] Report package filenames, SHA-256 values, CI run identities, Draft PR state, and real-machine acceptance status.