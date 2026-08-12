# Controlled Promotion / Rollback 2.3.25.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a deterministic, exact-approval, versioned Promotion governance registry with reversible rollback on top of 2.3.24.1 Shadow evidence, while making zero runtime policy changes.

**Architecture:** Mac Core adds schema 18 plus a dedicated promotion repository/service that consumes only immutable 24.1 Shadow facts and persists versioned Promotion, approval and rollback evidence. Mac Worker gains no execution authority. Windows extends the existing Business Automation quality surface with bounded Promotion/rollback controls and no free-form policy inputs.

**Tech Stack:** Python 3.12/3.13, FastAPI, Pydantic v2, SQLite, pytest, ruff, C#/.NET WPF, GitHub Actions native macOS/Windows packaging.

## Global Constraints

- Product version: `2.3.25.1`.
- Database schema: `18`.
- Base head: `a3d77a9bdfc6d413565972971ed10dcb4c34045d`.
- Promotion profile: `quality.promotion.v1`.
- Eligible Shadow state: `Completed` + verdict `Supported` + terminal review `AcceptedForPromotionReview`.
- Version numbers are Mac Core assigned, monotonically increasing per `(project_key, candidate_class)` slot.
- Activation and rollback require exact request digests and bounded human decisions.
- 25.1 runtime does not consume Active Promotion records to mutate execution.
- Zero local-AI, paid-AI, ComfyUI, shell/browser/Git/GitHub/publication execution caused by Promotion.
- Zero prompt/model/provider/endpoint/budget/workflow mutation.
- No source compilation on user Mac/Windows machines.
- Final PR remains Draft/Open/Unmerged; no main merge, tag, or GitHub Release.

---

### Task 1: RED migration/domain/API contracts

**Files:**
- Create: `tests/unit/db/test_quality_promotion_migration.py`
- Create: `tests/deep_ai/test_quality_promotion.py`
- Create: `tests/integration/api/test_quality_promotion_api.py`
- Create: `docs/superpowers/red/2026-08-12-controlled-promotion-rollback-2.3.25.1-red.md`

**Interfaces:**
- Consumes: schema-17 `quality_shadow_runs`, `quality_shadow_reviews`, schema-16 candidate/evaluation identities.
- Produces: executable schema/service/API requirements for Promotion.

- [ ] Write migration RED asserting schema version 18 and tables `quality_promotions`, `quality_promotion_approval_requests`, `quality_promotion_decisions`, `quality_promotion_rollbacks`.
- [ ] Write service RED proving only `Supported + AcceptedForPromotionReview` Shadow results are eligible.
- [ ] Write service RED for proposal idempotency, monotonic slot versions, exact activation approval, one Active per slot, supersede semantics and exact rollback restore semantics.
- [ ] Write service RED proving stale request digests, conflicting decisions, invalid rollback reason codes and history-only eligibility fail closed.
- [ ] Write zero-authority RED proving Promotion never creates paid attempts or mutates prompt/model/provider/endpoint/budget/workflow/runtime state.
- [ ] Write API RED for strict `extra="forbid"` create/reconcile/activation/rollback request models.
- [ ] Run native/Python RED and capture exact failing evidence before production implementation exists.

### Task 2: Schema 18 and promotion repository/service

**Files:**
- Create: `src/picotoopet_core/db/migration_018.py`
- Modify: `src/picotoopet_core/db/database.py`
- Create: `src/picotoopet_core/deep_ai/promotion.py`

**Interfaces:**
- `QualityPromotionRepository(database: Database)`.
- `QualityPromotionService(repository: QualityPromotionRepository, shadow_repository: QualityShadowRepository, evaluation_repository: QualityEvaluationRepository)`.
- `create(shadow_run_id: str) -> QualityPromotion`.
- `reconcile(promotion_id: str) -> QualityPromotion`.
- `get_promotion`, `list_promotions`, `get_active`.
- `decide_activation(promotion_id, decision, request_digest, idempotency_key)`.
- `request_rollback(promotion_id, rollback_reason_code)`.
- `decide_rollback(promotion_id, decision, request_digest, idempotency_key)`.

- [ ] Add schema-18 tables and indexes, including unique Shadow identity, unique `(slot_key, version_no)` and partial unique Active-per-slot index.
- [ ] Add frozen Pydantic models with `extra="forbid"` and digest patterns.
- [ ] Re-check Shadow run/candidate/evaluation/snapshot immutable digests before proposal creation and activation.
- [ ] Allocate slot/version transactionally; clients never submit either value.
- [ ] Generate fixed-expiry activation request and immutable `request_digest` from exact proposal facts.
- [ ] Implement activation decisions `Approved|Rejected|Cancelled`; approval transactionally supersedes prior Active and activates new version.
- [ ] Implement rollback request with closed reason codes `RegressionObserved|UnexpectedImpact|OperatorDecision`.
- [ ] Implement exact rollback approval that marks current `RolledBack` and restores immediate superseded predecessor, otherwise leaves the slot empty.
- [ ] Keep append-only decision/rollback facts and idempotent retry semantics.
- [ ] Implement reconcile without new version allocation or external execution.
- [ ] Run focused tests until GREEN.

### Task 3: Service container and authenticated Promotion API

**Files:**
- Modify: `src/picotoopet_core/services.py`
- Modify: `src/picotoopet_core/api/routes/deep_ai.py`

**Interfaces:**
- `POST /api/v1/deep-ai/promotions` body `{shadow_run_id}`.
- `GET /api/v1/deep-ai/promotions` with bounded optional project/candidate-class filters.
- `GET /api/v1/deep-ai/promotions/{promotion_id}`.
- `POST /api/v1/deep-ai/promotions/{promotion_id}/reconcile` empty body.
- `GET /api/v1/deep-ai/promotions/{promotion_id}/activation-request`.
- `POST /api/v1/deep-ai/promotions/{promotion_id}/activation-decision` bounded decision triple.
- `POST /api/v1/deep-ai/promotions/{promotion_id}/rollback-request` closed reason code only.
- `GET /api/v1/deep-ai/promotions/{promotion_id}/rollback-request`.
- `POST /api/v1/deep-ai/promotions/{promotion_id}/rollback-decision` bounded decision triple.
- `GET /api/v1/deep-ai/promotions/{promotion_id}/history`.

- [ ] Wire repository/service into `Services` and `build_services`.
- [ ] Add strict request models with `extra="forbid"`.
- [ ] Reject prompt/model/provider/endpoint/key/budget/tool/command/path/workflow/sql/formula/threshold/version/slot/executable-patch fields.
- [ ] Translate closed Promotion domain errors consistently.
- [ ] Run focused integration tests until GREEN.

### Task 4: Windows bounded Promotion / rollback UX

**Files:**
- Create: `windows/desktop/src/PicotooPet.Desktop.Core/Contracts/QualityPromotionContracts.cs`
- Create: `windows/desktop/src/PicotooPet.Desktop.Core/Networking/MacCoreQualityPromotionClient.cs`
- Modify: `windows/desktop/src/PicotooPet.Desktop/Services/ControlCenterSession.DeepAi.cs`
- Create: `windows/desktop/src/PicotooPet.Desktop/ViewModels/QualityPromotionPanelViewModel.cs`
- Create: `windows/desktop/src/PicotooPet.Desktop/Views/QualityPromotionPanel.xaml`
- Create: `windows/desktop/src/PicotooPet.Desktop/Views/QualityPromotionPanel.xaml.cs`
- Modify: `windows/desktop/src/PicotooPet.Desktop/Views/Pages/BusinessAutomationPage.xaml`
- Modify: `windows/desktop/src/PicotooPet.Desktop/ViewModels/BusinessAutomationPageViewModel.cs`
- Create: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/QualityPromotionClientSmokeTests.cs`
- Create: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/QualityPromotionPanelWpfSmokeTests.cs`
- Modify: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/Program.cs`

**Interfaces:**
- Closed DTOs mirror Promotion records/approval requests/history only.
- Create accepts selected `shadow_run_id` only.
- Activation decision exposes `Approved|Rejected|Cancelled` only.
- Rollback request exposes the three fixed reason codes only.
- Rollback decision exposes `Approved|Rejected|Cancelled` only.

- [ ] Add DTO/client/session methods without free-form execution-policy fields.
- [ ] Add ViewModel state that only loads Shadow runs with `Supported + AcceptedForPromotionReview` eligibility.
- [ ] Add exact approval-digest display and bounded activation buttons.
- [ ] Add closed rollback reason selector and exact rollback decision buttons.
- [ ] Add read-only Promotion version/history grid with explicit `Mode=OneWay` bindings.
- [ ] Embed panel in existing Business Automation quality area; add no top-level route.
- [ ] Add real STA `Measure/Arrange/UpdateLayout` smoke and REST-client smoke.
- [ ] Run Windows analyzer/warnings-as-errors/WPF smoke until GREEN.

### Task 5: Version/schema cumulative release contracts

**Files:**
- Modify: `src/picotoopet_core/product-version.txt`
- Modify: `contracts/release/project-goal-invariants.json`
- Modify: cumulative contract tests whose purpose is the newest product/schema identity.
- Modify: Windows product version/User-Agent/goal surfaces required by existing release contract.

- [ ] Roll current identity to `2.3.25.1` and schema 18 while preserving historical 18–24 schema definitions unchanged.
- [ ] Add `controlled_promotion_rollback_v1` architecture contract with schema 18 and all zero-authority invariants.
- [ ] Update only newest-rollup assertions from 24.1/schema17 to 25.1/schema18.
- [ ] Run full Python regression + ruff and Windows native build/smoke.

### Task 6: Draft PR and exact-head native CI

**Files:**
- Draft PR metadata/evidence only.

- [ ] Open Draft PR stacked directly on `feature/controlled-shadow-validation-2.3.24.1`.
- [ ] Verify exact feature head and source tree.
- [ ] Observe Mac Core, Mac Worker, Windows Control Center and Windows Prebuilt exact-head workflows.
- [ ] On ordinary failures, inspect logs, patch and rerun without pausing for confirmation.
- [ ] Keep PR Draft/Open/Unmerged and do not create tag/release.

### Task 7: Prebuilt package extraction and independent verification

**Files:**
- User-visible artifacts under `/mnt/data` only; do not commit binaries.

- [ ] Download exact-head Mac Core, Mac Worker and Windows Actions artifacts.
- [ ] Extract the three formal installer packages and CI sidecar SHA files.
- [ ] Independently recalculate wrapper and formal package SHA-256.
- [ ] Verify package paths, archive safety, arm64/AMD64 target, product `2.3.25.1`, migration 18, Promotion source/API presence, INSTALL/VERIFY/ROLLBACK and source/build tree identity.
- [ ] Produce `PicotooPet-2.3.25.1-Installers.zip`, stable FROZEN package names, SHA list, delivery manifest, independent-verification JSON, final status and cumulative manual acceptance instructions.
- [ ] Produce a new FULL-EVIDENCE operations handoff including 25.1 source/CI/package evidence and the retained 24.1 baseline.
