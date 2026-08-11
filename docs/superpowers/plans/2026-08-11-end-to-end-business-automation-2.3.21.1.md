# PicotooPet 2.3.21.1 End-to-End Business Automation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a restart-safe daily business pipeline from a validated Work Package through local intelligence, Creative Intelligence, ComfyUI Production, and an immutable Return Package v1.

**Architecture:** Mac Core owns one durable `BusinessPipelineRun` and reconciles child stages by immutable IDs. Existing 18.1/19.1/20.1 services remain authoritative for their own work; the pipeline only creates each child once, observes its durable state, and propagates terminal quality outcomes. Windows extends the existing Business Automation page with closed Amazon/Inspiration adapters and one End-to-End panel; no new top-level route or arbitrary renderer/model authority is added.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLite migrations, existing queue/worker runtime, C#/.NET WPF, PowerShell 5.1 release lifecycle, GitHub Actions native macOS arm64 and Windows runners.

## Global Constraints

- Base source head: `32f504344a343a6dd39d42609b2eb4ecc30574c1`.
- Product version: `2.3.21.1`.
- Database schema: `14`.
- Fixed Creative profile: `creative.content_plan.v1`.
- Fixed Production profile: `production.comfyui.v1`.
- ComfyUI remains loopback-only at `http://127.0.0.1:8188`.
- Business producers may not select model, endpoint, prompt/system prompt, workflow JSON, commands, tools, Git/GitHub actions, or arbitrary Core filesystem paths.
- Existing stage retry budgets remain authoritative; no unbounded retry loop is added.
- PR stays Draft/Open/Unmerged; no main merge/tag/GitHub Release.

---

### Task 1: Durable pipeline schema, contracts, and repository

**Files:**
- Create: `src/picotoopet_core/db/migration_014.py`
- Create: `src/picotoopet_core/business_pipeline/__init__.py`
- Create: `src/picotoopet_core/business_pipeline/models.py`
- Create: `src/picotoopet_core/business_pipeline/repository.py`
- Modify: `src/picotoopet_core/db/database.py`
- Test: `tests/business_pipeline/test_pipeline_repository.py`
- Test: `tests/unit/db/test_migrations.py`

**Interfaces:**
- Produces `BusinessPipelineStatus`, `BusinessAdapterProfile`, `BusinessPipelineRunRecord`, `BusinessReturnPackageRecord`.
- Produces `BusinessPipelineRepository.create_run()`, `get_run()`, `list_runs()`, `bind_child_once()`, `transition()`, `save_return_package()`.

- [ ] Write repository/migration tests first. The tests must assert schema 14, idempotent create by `idempotency_key`, one pipeline per `work_package_id`, and write-once child identities.
- [ ] Run focused tests and verify RED because Migration 14/module does not exist.
- [ ] Implement Migration 14 with `business_pipeline_runs` and `business_return_packages`, unique constraints on idempotency/work package/return package, child identity columns, status/project/time indexes.
- [ ] Implement strict Pydantic models with `extra="forbid"`; no request model contains model/workflow/endpoint/path/command/provider fields.
- [ ] Implement repository transitions and compare-and-bind semantics that reject replacing a non-null child ID with a different ID.
- [ ] Run focused tests and verify GREEN.

### Task 2: Core reconciler and quality propagation

**Files:**
- Create: `src/picotoopet_core/business_pipeline/service.py`
- Create: `src/picotoopet_core/business_pipeline/scheduler.py`
- Modify: `src/picotoopet_core/services.py`
- Modify: `src/picotoopet_core/api/app.py`
- Test: `tests/business_pipeline/test_pipeline_service.py`
- Test: `tests/business_pipeline/test_pipeline_scheduler.py`

**Interfaces:**
- Consumes `BusinessAutomationService`, `CreativeIntelligenceService`, `ProductionService` and their repositories.
- Produces `BusinessPipelineService.create_run(work_package_id, adapter_profile, idempotency_key)`, `reconcile(run_id)`, `cancel(run_id)`, `list_runs()`, `get_run()`.
- Produces `BusinessPipelineScheduler.reconcile_all()`.

- [ ] Write RED tests for `Completed Work Package + PASS Result → exactly one Creative job`, `creative_ready → exactly one Production job`, restart/reconcile idempotency, and terminal propagation for NeedsDeepAI/NeedsHuman/Rejected/Failed/Cancelled.
- [ ] Run RED and confirm failures are missing pipeline service behavior rather than fixture errors.
- [ ] Implement `reconcile()` as an ordered state machine that observes durable child records and binds IDs once. It must never call a later stage unless the predecessor package is immutable and PASS.
- [ ] Implement production waiting semantics: created Production job transitions parent to `AwaitingGpu`; active leased/rendering Production keeps parent at `Rendering`; production terminal states converge parent deterministically.
- [ ] Add scheduler loop to FastAPI lifespan beside the existing workflow scheduler with exception isolation and the existing reconcile cadence.
- [ ] Run focused and full Python regression until GREEN.

### Task 3: Immutable Return Package v1

**Files:**
- Create: `src/picotoopet_core/business_pipeline/package_builder.py`
- Create: `src/picotoopet_core/business_pipeline/store.py`
- Modify: `src/picotoopet_core/business_pipeline/service.py`
- Test: `tests/business_pipeline/test_return_package.py`

**Interfaces:**
- Produces `build_return_package(run, work_package, result_package, creative_package, production_package) -> dict[str, object]`.
- Return package is written once and referenced by `BusinessReturnPackageRecord`.

- [ ] Write RED provenance test through real repositories. Require Work/Result/Creative/Production IDs and digests, final output SHA/bytes/media metadata, inherited evidence provenance, producer/adapter identity, warnings/failures, and PASS quality outcome.
- [ ] Verify RED fails on missing return-package fields.
- [ ] Implement a pure builder that reads trusted Core records only. Reject mismatched project/package identity.
- [ ] Implement managed artifact storage under a Core-owned return-package directory; no producer-supplied path enters storage resolution.
- [ ] Final reconciliation writes package once, saves digest/relative path, then transitions parent to `Completed`.
- [ ] Run focused/full Python regression and ruff until GREEN.

### Task 4: Strict Business Pipeline API

**Files:**
- Create: `src/picotoopet_core/api/routes/business_pipeline.py`
- Modify: `src/picotoopet_core/api/app.py`
- Test: `tests/integration/api/test_business_pipeline_api.py`
- Test: `tests/contract/test_business_pipeline_23211_contract.py`

**Interfaces:**
- `POST /api/v1/business-pipeline/runs`
- `GET /api/v1/business-pipeline/runs`
- `GET /api/v1/business-pipeline/runs/{pipeline_run_id}`
- `POST /api/v1/business-pipeline/runs/{pipeline_run_id}/reconcile`
- `POST /api/v1/business-pipeline/runs/{pipeline_run_id}/cancel`
- `GET /api/v1/business-pipeline/runs/{pipeline_run_id}/return-package`
- `GET /api/v1/business-pipeline/runs/{pipeline_run_id}/return-package/archive`

- [ ] Write RED API tests for lifecycle and for rejection of extra fields including `model_id`, `endpoint`, `workflow`, `path`, `command`, `provider`.
- [ ] Implement strict request/response contracts and routes using `request.app.state.services.business_pipeline` only.
- [ ] Export authoritative OpenAPI and ensure new endpoints are present without widening old contracts.
- [ ] Run API/contract/full regression until GREEN.

### Task 5: Windows first-party Amazon and Inspiration adapters

**Files:**
- Create: `windows/desktop/src/PicotooPet.Desktop.Core/BusinessPipeline/BusinessAdapterContracts.cs`
- Create: `windows/desktop/src/PicotooPet.Desktop.Core/BusinessPipeline/BusinessWorkPackageAdapter.cs`
- Create: `windows/desktop/src/PicotooPet.Desktop.Core/BusinessPipeline/AmazonReviewsAdapter.cs`
- Create: `windows/desktop/src/PicotooPet.Desktop.Core/BusinessPipeline/InspirationIdeasAdapter.cs`
- Test: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/BusinessPipelineAdapterSmokeTests.cs`
- Modify: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/Program.cs`

**Interfaces:**
- Adapter profiles: `amazon.reviews_export.v1`, `inspiration.ideas_export.v1`.
- Each adapter produces a Work Package v1 ZIP/manifest compatible with the existing BusinessBridge upload path.

- [ ] Write RED adapter smoke tests for accepted CSV/JSON/JSONL/text, SHA-256/size manifest correctness, deterministic project/objective mapping, unsupported extension rejection, path traversal rejection, symlink/reparse-point rejection, and configured maximum size.
- [ ] Implement a shared safe packaging helper that copies only selected regular files into `inputs/`, normalizes filenames, computes SHA-256 from bytes, and writes `manifest.json` last.
- [ ] Implement Amazon adapter mapping only to `reviews.voice_of_customer.v1`.
- [ ] Implement Inspiration adapter mapping only to `ideas.pattern_analysis.v1`.
- [ ] Ensure no public adapter API accepts model/workflow/endpoint/command fields.
- [ ] Run .NET smoke/analyzer tests until GREEN.

### Task 6: Windows pipeline client, bridge, and End-to-End panel

**Files:**
- Create: `windows/desktop/src/PicotooPet.Desktop.Core/Contracts/BusinessPipelineContracts.cs`
- Create: `windows/desktop/src/PicotooPet.Desktop.Core/Networking/MacCoreClient.BusinessPipeline.cs`
- Create: `windows/desktop/src/PicotooPet.Desktop/Services/ControlCenterSession.BusinessPipeline.cs`
- Create: `windows/desktop/src/PicotooPet.Desktop/ViewModels/BusinessPipelinePanelViewModel.cs`
- Create: `windows/desktop/src/PicotooPet.Desktop/Views/Panels/BusinessPipelinePanel.xaml`
- Create: `windows/desktop/src/PicotooPet.Desktop/Views/Panels/BusinessPipelinePanel.xaml.cs`
- Modify: `windows/desktop/src/PicotooPet.Desktop/Services/BusinessBridgeService.cs`
- Modify: `windows/desktop/src/PicotooPet.Desktop/ViewModels/BusinessAutomationPageViewModel.cs`
- Modify: `windows/desktop/src/PicotooPet.Desktop/Views/Pages/BusinessAutomationPage.xaml`
- Test: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/BusinessPipelineWpfSmokeTests.cs`
- Modify: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/Program.cs`

**Interfaces:**
- Uses the API from Task 4.
- Reuses `%LOCALAPPDATA%\PicotooPet\BusinessBridge\Inbox`, `Outbox`, and adds managed `Runs` metadata.

- [ ] Write RED contract and WPF smoke tests before production UI code. The WPF test must instantiate the real panel and call `Measure/Arrange/UpdateLayout`.
- [ ] Implement client/session create/list/get/reconcile/cancel/return-package operations with the existing MacCoreClient auth/base URL.
- [ ] Extend BusinessBridgeService with adapter-to-Inbox submission and Return Package-to-Outbox materialization. Do not execute external programs.
- [ ] Implement panel ViewModel with bounded actions: select adapter/source, submit, refresh, cancel, open managed Outbox.
- [ ] Integrate panel inside existing Business Automation page; do not add a top-level Shell route.
- [ ] Run WPF smoke, warnings-as-errors build, and published EXE self-test until GREEN.

### Task 7: Version 2.3.21.1, release contracts, and exact-head delivery

**Files:**
- Modify: `src/picotoopet_core/product-version.txt`
- Modify: version/schema baseline tests and Windows product-version surfaces identified by existing contract suite
- Modify: `contracts/release/project-goal-invariants.json` only as required to freeze 2.3.21.1 capabilities
- Test: full native CI suites

**Interfaces:**
- Final release-freeze exact source head is the only accepted artifact source.

- [ ] Add RED product/schema/adapter/pipeline release contracts for `2.3.21.1` and schema 14 before updating production version surfaces.
- [ ] Update product version and active baseline fixtures without deleting historical migration/package assertions.
- [ ] Run exact-head Mac Core, Mac Worker impact/native gate, Windows Control Center WPF gate, and Windows Prebuilt release gate.
- [ ] If a gate fails, inspect exact logs, write/retain a regression reproducing the root cause, and fix only that cause before rerunning the latest head.
- [ ] Require Windows formal gate to pass build/self-test, installer goal-integrity, install/upgrade/recovery/rollback lifecycle.
- [ ] Download all affected artifacts and independently recompute outer artifact and inner formal package SHA-256 values.
- [ ] Deliver every required installer in one response with a unified SHA manifest and a manual end-to-end acceptance checklist. Keep PR Draft/Open/Unmerged.
