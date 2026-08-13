# Operator Simple Mode 2.3.26.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Windows PicotooPet default to a five-entry operator console—首页 / 待我审核 / 进行中 / 已完成 / 高级—with a bounded new-task wizard and real-state projections over the existing 2.3.25.1 control plane.

**Architecture:** Keep Core durable facts, tasks, approvals and results authoritative. Add a Windows-only `OperatorProjection` layer and new WPF operator pages, while preserving all existing engineering routes behind an Advanced Home. No parallel simple-mode persistence is introduced; background snapshots update projections by durable identity.

**Tech Stack:** C# / .NET 10 / WPF / MVVM-style ViewModels / existing `ControlCenterSession`, Core contracts and native Windows smoke-test executable.

## Global Constraints

- Base: `11734a1aa58c1409c7cd2b59579a3cdf5a882930` plus the committed 26.1 design/plan docs.
- Product version target: `2.3.26.1`.
- Database schema remains `18`.
- No new Mac Core/Worker behavior; a shared product-version resource may bump package metadata only.
- No source compilation on the user PC.
- No new Paid-AI execution, provider/endpoint/model/prompt/workflow authority, ComfyUI installation authority, or Promotion runtime mutation.
- No merge to `main`, tag, GitHub Release, or public publication.
- Feature PR stays Draft / Open / Unmerged through real-machine acceptance.
- Existing Business Automation scroll and Task Center stability hotfixes must remain cumulative.

---

## File Structure

### New operator projection and pages

- Create `windows/desktop/src/PicotooPet.Desktop/ViewModels/OperatorProjection.cs` — deterministic projection from `ControlCenterSessionSnapshot` into operator buckets and compact system status.
- Create `windows/desktop/src/PicotooPet.Desktop/ViewModels/OperatorHomePageViewModel.cs` — home summaries and New Task entry.
- Create `windows/desktop/src/PicotooPet.Desktop/ViewModels/OperatorReviewPageViewModel.cs` — unified review-facing cards; initially projects currently available approval/task facts without inventing new durable approval types.
- Create `windows/desktop/src/PicotooPet.Desktop/ViewModels/OperatorTaskListPageViewModel.cs` — reusable in-progress/completed list projection.
- Create `windows/desktop/src/PicotooPet.Desktop/ViewModels/AdvancedHomePageViewModel.cs` — grouped links to existing engineering routes.
- Create `windows/desktop/src/PicotooPet.Desktop/ViewModels/NewTaskWizardViewModel.cs` — bounded supported-task wizard, no arbitrary authority.
- Create `windows/desktop/src/PicotooPet.Desktop/Views/Pages/OperatorHomePage.xaml(.cs)`.
- Create `windows/desktop/src/PicotooPet.Desktop/Views/Pages/OperatorReviewPage.xaml(.cs)`.
- Create `windows/desktop/src/PicotooPet.Desktop/Views/Pages/OperatorTaskListPage.xaml(.cs)`.
- Create `windows/desktop/src/PicotooPet.Desktop/Views/Pages/AdvancedHomePage.xaml(.cs)`.
- Create `windows/desktop/src/PicotooPet.Desktop/Views/Pages/NewTaskWizardWindow.xaml(.cs)`.

### Existing shell/version files

- Modify `windows/desktop/src/PicotooPet.Desktop/Navigation/NavigationRoute.cs` — add operator routes while retaining every existing advanced route.
- Modify `windows/desktop/src/PicotooPet.Desktop/ViewModels/ShellViewModel.cs` — five-entry default navigation, operator-page snapshot updates, hidden advanced-route navigation.
- Modify `windows/desktop/src/PicotooPet.Desktop/Views/ShellWindow.xaml` — operator-oriented visual hierarchy while retaining the existing page fault boundary.
- Modify `windows/desktop/src/PicotooPet.Desktop/App.xaml` — register DataTemplates for new page ViewModels if templates are defined there.
- Modify `src/picotoopet_core/product-version.txt` — bump shared release identity to `2.3.26.1`; schema and Mac behavior remain unchanged.

### Tests

- Create `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/OperatorProjectionSmokeTests.cs`.
- Create `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/OperatorNavigationSmokeTests.cs`.
- Create `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/OperatorSimpleModeWpfSmokeTests.cs`.
- Create `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/NewTaskWizardSmokeTests.cs`.
- Modify `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/Program.cs` — register the new smoke suites using the existing harness pattern.
- Add/modify contract tests under `tests/contract/` to freeze product version, schema 18, five-entry simple navigation, advanced reachability, and absence of forbidden authority fields.

---

### Task 1: Freeze 26.1 version and navigation contract

**Files:**
- Modify: `src/picotoopet_core/product-version.txt`
- Modify: `windows/desktop/src/PicotooPet.Desktop/Navigation/NavigationRoute.cs`
- Test: `tests/contract/test_operator_simple_mode_26_1.py`
- Test: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/OperatorNavigationSmokeTests.cs`

**Interfaces:**
- Produces operator routes `OperatorHome`, `OperatorReview`, `OperatorInProgress`, `OperatorCompleted`, `AdvancedHome` while preserving existing routes.
- Produces shared product version `2.3.26.1`.

- [ ] **Step 1: Write the failing contract test** requiring `product-version.txt == 2.3.26.1`, schema target still 18, and the five new route names while forbidding removal of `TaskCenter`, `Results`, `Approvals`, `BusinessAutomation`, `Health`, `Diagnostics`, and `Settings`.
- [ ] **Step 2: Run** `python -m pytest -q tests/contract/test_operator_simple_mode_26_1.py` and verify RED on version/routes.
- [ ] **Step 3: Write the failing C# smoke** that creates `ShellViewModel.CreateForSmokeTest(...)` and requires exactly five default `NavigationItems` titles in order: `首页`, `待我审核`, `进行中`, `已完成`, `高级`; default route must be `OperatorHome`.
- [ ] **Step 4: Run** the native smoke project on Windows CI and verify RED before production changes.
- [ ] **Step 5: Minimally bump the version resource and extend `NavigationRoute` without changing existing route semantics.**
- [ ] **Step 6: Commit** `test: freeze operator simple navigation for 2.3.26.1` for RED, then `feat: add operator route identities for 2.3.26.1` for GREEN.

### Task 2: Build deterministic OperatorProjection

**Files:**
- Create: `windows/desktop/src/PicotooPet.Desktop/ViewModels/OperatorProjection.cs`
- Test: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/OperatorProjectionSmokeTests.cs`

**Interfaces:**
- Consumes: `ControlCenterSessionSnapshot` and existing `TaskRecord`/Worker/connection states.
- Produces: immutable operator task cards grouped into `PendingReview`, `InProgress`, `Completed`, plus `WindowsStatus`, `CoreStatus`, `WorkerStatus`.

- [ ] **Step 1: Write RED tests** with representative existing task statuses and assert deterministic bucketing, stable `TaskId` identity, descending update order, safe status text, and no percentage property/value.
- [ ] **Step 2: Add a security assertion** that the projection type exposes no `Provider`, `Endpoint`, `ApiKey`, `Model`, `Prompt`, `Workflow`, `Command`, or `Sql` writable property.
- [ ] **Step 3: Run the focused smoke on native Windows** and verify RED because `OperatorProjection` does not exist.
- [ ] **Step 4: Implement `OperatorProjection.FromSnapshot(ControlCenterSessionSnapshot snapshot)` as a pure projection**; use only durable statuses already present in `TaskRecord`/snapshot state and never persist anything.
- [ ] **Step 5: Re-run focused smoke** and verify GREEN.
- [ ] **Step 6: Commit** `feat: project durable facts into operator buckets`.

### Task 3: Make Simple Mode the default Shell and preserve Advanced routes

**Files:**
- Modify: `windows/desktop/src/PicotooPet.Desktop/ViewModels/ShellViewModel.cs`
- Modify: `windows/desktop/src/PicotooPet.Desktop/Views/ShellWindow.xaml`
- Create: `windows/desktop/src/PicotooPet.Desktop/ViewModels/AdvancedHomePageViewModel.cs`
- Create: `windows/desktop/src/PicotooPet.Desktop/Views/Pages/AdvancedHomePage.xaml`
- Create: `windows/desktop/src/PicotooPet.Desktop/Views/Pages/AdvancedHomePage.xaml.cs`
- Test: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/OperatorNavigationSmokeTests.cs`

**Interfaces:**
- `ShellViewModel.Navigate(NavigationRoute)` must support hidden advanced routes without requiring them in `NavigationItems`.
- `AdvancedHomePageViewModel` exposes grouped `AdvancedRouteLink` records and a bounded callback to `ShellViewModel.Navigate`.

- [ ] **Step 1: Extend RED navigation smoke** to require five sidebar items only, navigate `AdvancedHome`, then invoke each advanced link and assert every historical route remains reachable.
- [ ] **Step 2: Implement `BuildNavigation` as five Simple entries only** and default selected/current route to `OperatorHome`.
- [ ] **Step 3: Change `Navigate`** so a hidden advanced route changes `CurrentRoute`/`CurrentPage` while sidebar selection remains `高级` rather than throwing `Single()` lookup failure.
- [ ] **Step 4: Implement Advanced Home grouped links** for business/execution, governance, operations, and development/configuration.
- [ ] **Step 5: Update Shell XAML** to retain `NavigationContentHost` and existing connection/approval safety indicators while using the approved compact five-entry sidebar.
- [ ] **Step 6: Run navigation smoke and warnings-as-errors build**; expect GREEN.
- [ ] **Step 7: Commit** `feat: make operator simple mode the default shell`.

### Task 4: Implement Home, review, in-progress and completed operator pages

**Files:**
- Create: `windows/desktop/src/PicotooPet.Desktop/ViewModels/OperatorHomePageViewModel.cs`
- Create: `windows/desktop/src/PicotooPet.Desktop/ViewModels/OperatorReviewPageViewModel.cs`
- Create: `windows/desktop/src/PicotooPet.Desktop/ViewModels/OperatorTaskListPageViewModel.cs`
- Create: `windows/desktop/src/PicotooPet.Desktop/Views/Pages/OperatorHomePage.xaml(.cs)`
- Create: `windows/desktop/src/PicotooPet.Desktop/Views/Pages/OperatorReviewPage.xaml(.cs)`
- Create: `windows/desktop/src/PicotooPet.Desktop/Views/Pages/OperatorTaskListPage.xaml(.cs)`
- Modify: `windows/desktop/src/PicotooPet.Desktop/ViewModels/ShellViewModel.cs`
- Test: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/OperatorSimpleModeWpfSmokeTests.cs`

**Interfaces:**
- Each page ViewModel accepts a snapshot/projection and exposes `UpdateSnapshot(ControlCenterSessionSnapshot)` to preserve page instance and logical user context.
- `OperatorHomePageViewModel` exposes `OpenNewTaskRequested` or a bounded action callback used by the page code-behind to open the wizard.

- [ ] **Step 1: Write real STA WPF RED** that renders all four operator pages at `1100x800`, calls `Measure`, `Arrange`, `UpdateLayout`, replaces the backing snapshot with same logical task IDs, and asserts visible cards remain stable.
- [ ] **Step 2: Implement page ViewModels** as thin projections; do not copy state into persistence.
- [ ] **Step 3: Implement WPF pages** with OneWay bindings for all read-only properties, real status/stage text only, no fake percentages, and technical detail links rather than raw IDs on primary cards.
- [ ] **Step 4: Update `ShellViewModel.ApplySnapshot`** to call `UpdateSnapshot` on operator pages instead of replacing page instances during heartbeats.
- [ ] **Step 5: Run STA WPF smoke** and verify GREEN with no binding/layout exception.
- [ ] **Step 6: Commit** `feat: add operator home review and result views`.

### Task 5: Add bounded New Task wizard

**Files:**
- Create: `windows/desktop/src/PicotooPet.Desktop/ViewModels/NewTaskWizardViewModel.cs`
- Create: `windows/desktop/src/PicotooPet.Desktop/Views/Pages/NewTaskWizardWindow.xaml`
- Create: `windows/desktop/src/PicotooPet.Desktop/Views/Pages/NewTaskWizardWindow.xaml.cs`
- Modify: `windows/desktop/src/PicotooPet.Desktop/ViewModels/OperatorHomePageViewModel.cs`
- Test: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/NewTaskWizardSmokeTests.cs`
- Test: `tests/contract/test_operator_simple_mode_26_1.py`

**Interfaces:**
- `NewTaskWizardViewModel` exposes a closed `OperatorTaskKind` enum and `OperatorTaskOption` list.
- Submission maps only to already implemented fixed task/work-package operations; unsupported future crawler/search options are disabled with `尚未接入`.

- [ ] **Step 1: Write RED wizard smoke** requiring a finite task option set, explicit disabled unsupported sources, business-goal text, Back/Next/Submit state transitions, and no free-form provider/model/endpoint/workflow fields.
- [ ] **Step 2: Add contract assertions** scanning the new wizard XAML/ViewModel for forbidden authority labels/properties.
- [ ] **Step 3: Implement the smallest useful supported task set** from current capabilities; do not invent crawler/search integration.
- [ ] **Step 4: Wire submission to existing safe task/work-package APIs** only where the mapping is already supported; options without a safe existing operation remain disabled rather than simulated.
- [ ] **Step 5: Run focused smoke and contract tests** and verify GREEN.
- [ ] **Step 6: Commit** `feat: add bounded operator task wizard`.

### Task 6: Native regression, packaging and evidence

**Files:**
- Modify only if required by existing release contracts: `.github/workflows/windows-control-center-ci.yml`, `.github/workflows/phase23-windows-prebuilt.yml`, or release analyzer expectations.
- Evidence docs under `docs/superpowers/red/` and delivery artifacts generated by CI.

**Interfaces:**
- Exact source head becomes the only accepted package provenance for 2.3.26.1.

- [ ] **Step 1: Run full contract/security suite** and confirm schema 18/security boundaries remain unchanged.
- [ ] **Step 2: Run native Windows Control Center CI** requiring operator navigation/projection/wizard STA WPF smoke, warnings-as-errors build and published self-test.
- [ ] **Step 3: Run Mac Core/Worker CI if the shared version file triggers them**; require success and verify no Mac behavior diff beyond release identity.
- [ ] **Step 4: Run formal Windows Prebuilt workflow** and require analyzer/build/publish/self-test, delivery invariants, goal-integrity contract, and PowerShell 5.1 install/upgrade/activation-failure recovery/rollback lifecycle.
- [ ] **Step 5: Download formal artifacts and independently recompute SHA-256, ZIP/tar integrity, manifest source head, target architecture, payload hashes and no-source-build invariants.**
- [ ] **Step 6: Create/update Draft PR** `feat: operator simple mode for 2.3.26.1` targeting `hotfix/task-center-diagnostic-stability-2.3.25.1`; keep Open/Unmerged.
- [ ] **Step 7: Deliver precompiled packages and concise real-machine acceptance instructions.**
