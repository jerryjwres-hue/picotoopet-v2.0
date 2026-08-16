# Task Lifecycle and Windows Readability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add reversible task deletion/recovery, bulk task actions, task/result detail viewing, and whole-app WPF readability improvements while preserving Mac Core authority and existing safety contracts.

**Architecture:** Mac Core gets a dedicated reversible visibility state rather than abusing the frozen execution `Archived` state. Windows simple-mode task lists project visible/deleted tasks from the authoritative Core snapshot, send explicit task IDs for delete/restore, and open a fixed-contract task detail surface. WPF typography moves to centralized application resources with DPI-safe rendering defaults.

**Tech Stack:** Python 3.12, FastAPI, SQLite-backed PicotooPet Core repositories, C#/.NET WPF, xUnit/smoke tests, GitHub Actions Windows release gates.

## Global Constraints

- Main Windows product identity remains the approved 2.3.26.1 identity; Research capability remains 2.3.27.1.
- Mac Core remains authoritative.
- No arbitrary shell execution is added.
- No physical task/result deletion is added.
- Existing diagnostic OpenAPI/result contract remains unchanged.
- Existing Research read-only/write-disabled policy remains unchanged.
- Existing Maotai/pet UI work is preserved.

---

### Task 1: Reversible task visibility contract in Mac Core

**Files:**
- Modify: `src/picotoopet_core/domain/models.py`
- Modify: `src/picotoopet_core/queue/diagnostic_repository.py`
- Modify: `src/picotoopet_core/api/routes/tasks.py`
- Test: `tests/integration/api/test_api.py`
- Test: `tests/contract/test_research_task_contract.py`

**Interfaces:**
- Produces: `TaskRecord.is_hidden: bool` with default `False`.
- Produces: `POST /api/tasks/{task_id}/hide` returning authoritative `TaskRecord`.
- Produces: `POST /api/tasks/{task_id}/restore` returning authoritative `TaskRecord`.
- Produces: `POST /api/tasks/batch-hide` and `POST /api/tasks/batch-restore` with explicit task ID lists and per-task outcomes.

- [ ] **Step 1: Write failing API/repository tests**

Add tests that create a completed task, hide it, verify `is_hidden=true`, restore it, verify the original execution status is unchanged, and verify batch endpoints return one outcome per explicit task ID. Add an active-task test requiring cancel-before-hide semantics.

- [ ] **Step 2: Run targeted tests and verify RED**

Run: `python -m pytest tests/integration/api/test_api.py tests/contract/test_research_task_contract.py -q`
Expected: FAIL because visibility fields/endpoints do not exist.

- [ ] **Step 3: Implement minimal persistent visibility state**

Persist a visibility flag alongside task records using the existing SQLite repository migration/column pattern. Do not transition execution state to `Archived` for user deletion. `hide` must request cancellation for active controlled tasks and only mark hidden once a terminal task is observed; terminal tasks can be hidden immediately. Restore only clears the visibility flag.

- [ ] **Step 4: Implement bounded batch actions**

Add request/response models with a finite maximum task-ID count, reject blank/duplicate IDs deterministically, execute each explicit ID independently, and return success/failure per item without physical deletion.

- [ ] **Step 5: Run targeted tests and verify GREEN**

Run: `python -m pytest tests/integration/api/test_api.py tests/contract/test_research_task_contract.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

Commit message: `feat(tasks): add reversible task visibility`

---

### Task 2: Windows networking/session APIs for hide, restore, and Research result detail

**Files:**
- Modify: `windows/desktop/src/PicotooPet.Desktop.Core/Contracts/ApiContracts.cs`
- Modify: `windows/desktop/src/PicotooPet.Desktop.Core/Networking/MacCoreClient.cs`
- Modify: `windows/desktop/src/PicotooPet.Desktop/Services/ControlCenterSession.Tasks.cs`
- Test: `windows/desktop/tests/PicotooPet.Desktop.Tests/*Task*Tests.cs`

**Interfaces:**
- Produces: `HideTasksAsync(IReadOnlyList<string>, CancellationToken)`.
- Produces: `RestoreTasksAsync(IReadOnlyList<string>, CancellationToken)`.
- Produces: `GetResearchResultAsync(string taskId, CancellationToken)`.

- [ ] **Step 1: Write failing client/session tests**

Cover endpoint paths, explicit task-ID payloads, per-task outcome parsing, snapshot upserts, and Research result retrieval from `/api/tasks/{task_id}/research-result`.

- [ ] **Step 2: Run WPF/Core targeted tests and verify RED**

Run the existing desktop test project with filters for new task-action tests.
Expected: FAIL because methods/contracts do not exist.

- [ ] **Step 3: Implement fixed networking contracts**

Add strongly typed DTOs and fixed endpoint methods only. Do not add arbitrary URL, path, or result-file browsing.

- [ ] **Step 4: Update session snapshot handling**

After hide/restore, upsert every authoritative returned task into the existing task state store and publish a normal snapshot update.

- [ ] **Step 5: Run targeted tests and verify GREEN**

Expected: PASS.

- [ ] **Step 6: Commit**

Commit message: `feat(windows): connect task visibility actions`

---

### Task 3: Simple-mode selection, safe delete, deleted view, and restore

**Files:**
- Modify: `windows/desktop/src/PicotooPet.Desktop/Navigation/NavigationRoute.cs`
- Modify: `windows/desktop/src/PicotooPet.Desktop/ViewModels/ShellViewModel.cs`
- Modify: `windows/desktop/src/PicotooPet.Desktop/ViewModels/OperatorProjection.cs`
- Modify: `windows/desktop/src/PicotooPet.Desktop/ViewModels/OperatorTaskListPageViewModel.cs`
- Modify: `windows/desktop/src/PicotooPet.Desktop/Views/Pages/OperatorTaskListPage.xaml`
- Modify: `windows/desktop/src/PicotooPet.Desktop/Views/Pages/OperatorTaskListPage.xaml.cs`
- Test: relevant simple-mode/navigation tests under `windows/desktop/tests/`

**Interfaces:**
- Produces: `NavigationRoute.OperatorDeleted`.
- Produces: selection state per visible task card.
- Produces: `DeleteSelectedCommand`, `RestoreSelectedCommand`, `SelectAllVisibleCommand`.

- [ ] **Step 1: Write failing projection/navigation tests**

Verify visible in-progress/completed projections exclude `is_hidden=true`; deleted projection contains hidden tasks; simple navigation exposes `已删除`; selection affects only current visible items.

- [ ] **Step 2: Run targeted tests and verify RED**

Expected: FAIL because hidden projection/route/commands do not exist.

- [ ] **Step 3: Implement projection and route**

Keep execution-state classification unchanged; apply visibility as an orthogonal filter. Add `已删除` between `已完成` and `高级`.

- [ ] **Step 4: Implement selection and bulk actions**

Use checkboxes, page-level `全选当前页`, and explicit buttons. Keep selection if Mac Core is unreachable. Show per-task partial failures and refresh successful outcomes from the session snapshot.

- [ ] **Step 5: Add single-task delete/restore controls**

Every task card gets a direct delete or restore action in addition to bulk selection.

- [ ] **Step 6: Run targeted tests and verify GREEN**

Expected: PASS.

- [ ] **Step 7: Commit**

Commit message: `feat(windows): add deleted task recovery view`

---

### Task 4: Clickable task detail with fixed result renderers

**Files:**
- Create: `windows/desktop/src/PicotooPet.Desktop/ViewModels/TaskDetailPageViewModel.cs`
- Create: `windows/desktop/src/PicotooPet.Desktop/Views/Pages/TaskDetailPage.xaml`
- Create: `windows/desktop/src/PicotooPet.Desktop/Views/Pages/TaskDetailPage.xaml.cs`
- Modify: `windows/desktop/src/PicotooPet.Desktop/ViewModels/OperatorTaskListPageViewModel.cs`
- Modify: `windows/desktop/src/PicotooPet.Desktop/ViewModels/ShellViewModel.cs`
- Test: `windows/desktop/tests/PicotooPet.Desktop.Tests/*TaskDetail*Tests.cs`

**Interfaces:**
- Consumes: diagnostic result contract and `GetResearchResultAsync`.
- Produces: fixed task detail model with metadata, safe payload summary, error summary, and typed result sections.

- [ ] **Step 1: Write failing detail/result tests**

Verify all task cards can open details; diagnostic results use existing safe model; Research results render query, summary/content, and sources; unknown result types are metadata-only.

- [ ] **Step 2: Run targeted tests and verify RED**

Expected: FAIL because detail surface does not exist.

- [ ] **Step 3: Implement task detail ViewModel**

Do not expose arbitrary result object paths, raw manifests, tokens, or filesystem locations.

- [ ] **Step 4: Implement WPF detail page and card navigation**

Make the card title/body clickable while keeping checkbox/delete controls independently clickable.

- [ ] **Step 5: Run targeted tests and verify GREEN**

Expected: PASS.

- [ ] **Step 6: Commit**

Commit message: `feat(windows): show task and research results`

---

### Task 5: Whole-app typography and DPI readability

**Files:**
- Modify: `windows/desktop/src/PicotooPet.Desktop/App.xaml`
- Modify: `windows/desktop/src/PicotooPet.Desktop/app.manifest`
- Modify: text-heavy XAML under `windows/desktop/src/PicotooPet.Desktop/Views/`
- Test: existing WPF smoke/visual-contract tests
- Test: add/update source contract test under `tests/contract/` for minimum operator font scale and DPI manifest

**Interfaces:**
- Produces shared resources: caption 12, secondary 13, body 14, emphasized 15, section 18, page 26 DIP.

- [ ] **Step 1: Write failing source/readability contracts**

Assert shared typography resources exist, the application manifest opts into per-monitor DPI awareness, and normal operator pages no longer contain hard-coded 8–10 DIP text sizes.

- [ ] **Step 2: Run contracts and verify RED**

Expected: FAIL on current tiny-font XAML.

- [ ] **Step 3: Add shared typography and rendering defaults**

Set application-level text formatting defaults for opaque surfaces. Preserve transparent floating-pet rendering behavior.

- [ ] **Step 4: Migrate text-heavy pages to shared sizes**

Prioritize shell/sidebar, operator home, task lists, new task wizard, results/task detail, approvals, settings, health/diagnostics, and advanced pages. Increase button/card vertical spacing where needed.

- [ ] **Step 5: Run WPF tests and source contracts**

Expected: PASS with no clipping regressions in smoke tests.

- [ ] **Step 6: Commit**

Commit message: `fix(windows): improve typography and DPI readability`

---

### Task 6: Full verification and Windows installer

**Files:**
- Modify only if required by a concrete failing release gate.

**Interfaces:**
- Produces a new Windows Research release artifact containing the task lifecycle/result/readability changes.

- [ ] **Step 1: Run Research/Core contracts**

Run the repository Research task contract suite and full Python regression.
Expected: PASS.

- [ ] **Step 2: Run native Windows WPF build/tests**

Run the existing GitHub Actions Research Windows final release workflow.
Expected: WPF compile/tests PASS.

- [ ] **Step 3: Run target-integrity and lifecycle gates**

Expected: target stamp/verification PASS; install → upgrade → restore → rollback lifecycle PASS.

- [ ] **Step 4: Download and inspect the uploaded artifact**

Verify installer entrypoints and compute SHA-256 before presenting it.

- [ ] **Step 5: Completion gate**

Do not claim completion until the fresh workflow run is `success` and the new artifact exists.
