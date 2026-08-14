# Operator Home Reference UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the confirmed reference screenshot the Windows 2.3.26.1 Simple Mode pixel-level implementation benchmark, including realistic Alaskan assets and correct working/resting/offline state colors.

**Architecture:** Keep the existing Core/Worker facts, `OperatorProjection`, `ShellViewModel`, closed widget catalog, and WPF navigation. Replace only the presentation/resource layer and tighten the assistant state resolver so `Working` depends on Worker `executing`, not the presence of queued tasks. Add packaged image resources and bind all assistant colors/images/text to one state key.

**Tech Stack:** .NET 10 WPF, XAML ResourceDictionary, existing MVVM/session snapshot model, GitHub Actions Windows native WPF gates.

## Global Constraints

- Product version remains `2.3.26.1`.
- Schema remains `18`.
- Paid-AI remains disabled by default.
- Promotion remains governance-only and cannot mutate runtime provider/model/prompt/budget/workflow automatically.
- Windows stores no Provider secrets and exposes no arbitrary Provider/Endpoint/Model/Prompt/Workflow/Command/SQL/Assembly/Script execution surface.
- Search remains `尚未接入` until bounded external acquisition exists.
- Missing telemetry/progress must display an unavailable state, never fabricated percentages.
- Generated code comments remain aligned and concise.
- Do not merge/tag/release automatically.

---

### Task 1: Freeze assistant execution semantics and status colors

**Files:**
- Modify: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/OperatorVisualCompletionSmokeTests.cs`
- Modify: `windows/desktop/src/PicotooPet.Desktop/ViewModels/OperatorExperienceModels.cs`
- Modify: `windows/desktop/src/PicotooPet.Desktop/Views/ShellWindow.xaml`

**Interfaces:**
- Consumes: `ControlCenterSessionSnapshot.State.Worker.State`, `Worker.Available`.
- Produces: `OperatorAssistantStateResolver.FromSnapshot(...)`, `AssistantStateKey`, state-specific WPF brush triggers.

- [ ] **Step 1: Add RED assertions**
  - Assert online + idle + queued task => `Resting`.
  - Assert online + `executing` => `Working`.
  - Assert `Resting` visual indicator uses amber brush, `Working` green, `OfflineSleeping` gray.

- [ ] **Step 2: Run Windows contract/smoke gate**
  - Expected before implementation: FAIL on idle/queued semantics or missing state-specific indicator.

- [ ] **Step 3: Implement resolver and state-specific brushes**
  - `FromSnapshot` must derive `workerExecuting = worker.Available && worker.State == "online" && worker.Reason == "executing"` or equivalent trusted execution signal.
  - `Queued`/projection count must not be used to select `Working`.
  - Bind sidebar dot and assistant status dot to state key via triggers.

- [ ] **Step 4: Re-run focused Windows smoke**
  - Expected: PASS.

---

### Task 2: Package high-quality Alaskan visual assets

**Files:**
- Create: `windows/desktop/src/PicotooPet.Desktop/Assets/Assistant/alaskan-hero.png`
- Create: `windows/desktop/src/PicotooPet.Desktop/Assets/Assistant/alaskan-working.png`
- Create: `windows/desktop/src/PicotooPet.Desktop/Assets/Assistant/alaskan-resting.png`
- Create: `windows/desktop/src/PicotooPet.Desktop/Assets/Assistant/alaskan-sleeping.png`
- Modify: `windows/desktop/src/PicotooPet.Desktop/PicotooPet.Desktop.csproj`
- Modify: `windows/desktop/src/PicotooPet.Desktop/Views/Controls/AlaskanAssistantMascot.xaml`

**Interfaces:**
- Produces stable pack URIs under `/Picotoo Pet AI;component/Assets/Assistant/...`.

- [ ] **Step 1: Extract/crop approved reference artwork into focused resource images**
  - Hero asset preserves the approved realistic Alaskan and blue environment.
  - Working/resting/sleeping assets preserve the approved state language.

- [ ] **Step 2: Add WPF Resource entries**
  - Mark PNG files as `Resource`; do not copy from external/user paths at runtime.

- [ ] **Step 3: Replace vector mascot rendering**
  - `AlaskanAssistantMascot` selects image by `AssistantStateKey`.
  - Keep a simple non-throwing vector/text fallback only if resource loading fails.

- [ ] **Step 4: Add WPF resource-load smoke assertions**
  - Instantiate each state and ensure `Image.Source` resolves without exception.

---

### Task 3: Rebuild Shell/sidebar/header to reference geometry

**Files:**
- Modify: `windows/desktop/src/PicotooPet.Desktop/Views/ShellWindow.xaml`
- Modify: `windows/desktop/src/PicotooPet.Desktop/Themes/PicotooTheme.xaml`

**Interfaces:**
- Consumes existing `ShellViewModel` fields and navigation events.

- [ ] **Step 1: Add structural smoke markers**
  - `ReferenceSidebar`, `ReferenceHeader`, `AssistantStatusPanel`, `ReferenceProfileCard`.

- [ ] **Step 2: Implement reference sidebar**
  - Approximate 260px width at baseline, brand area, nav rows with badge-ready slots, settings entry, assistant panel, user card.
  - Selected row is vivid blue; dark navy background and reference spacing.

- [ ] **Step 3: Implement reference header**
  - Page title/subtitle left; system/worker/windows/approval chips right.
  - Avoid duplicate assistant work state in the header.

- [ ] **Step 4: Verify WPF layout at baseline and minimum window sizes**
  - Measure/Arrange/UpdateLayout in STA smoke.

---

### Task 4: Rebuild Home page to reference 2D layout

**Files:**
- Modify: `windows/desktop/src/PicotooPet.Desktop/Views/Pages/OperatorHomePage.xaml`
- Modify: `windows/desktop/src/PicotooPet.Desktop/ViewModels/OperatorHomePageViewModel.cs`

**Interfaces:**
- Uses existing task projection and closed widget data.
- Adds no durable storage beyond existing widget layout preferences.

- [ ] **Step 1: Add reference layout smoke markers**
  - `ReferenceHero`, `ReferenceSystemCard`, `ReferenceReviewCard`, `ReferenceActiveCard`, `ReferenceCompletedCard`, `ReferenceResourceCard`, `ReferenceRecentTasks`, `ReferenceSystemLog`, `ReferenceWidgetBoard`.

- [ ] **Step 2: Implement top row**
  - Hero left, system-status card right.
  - Hero uses packaged realistic Alaskan asset and reference blue gradient/light treatment.

- [ ] **Step 3: Implement second row**
  - Three compact task summary cards left, resource card right.
  - No fake progress or telemetry.

- [ ] **Step 4: Implement lower row**
  - Recent tasks + system log in left column.
  - Widget board as compact two-column cards in right column.

- [ ] **Step 5: Tune baseline geometry**
  - Match reference proportions/spacing at 1366×853-class window while preserving vertical scroll at smaller DPI-adjusted viewport.

---

### Task 5: Keep non-home pages visually consistent

**Files:**
- Modify as needed: `OperatorReviewPage.xaml`, `OperatorTaskListPage.xaml`, `NewTaskWizardWindow.xaml`, `OperatorWidgetManagerWindow.xaml`, `AdvancedHomePanel` styles/theme resources.

**Interfaces:**
- No navigation or security semantics change.

- [ ] **Step 1: Verify all Simple Mode destinations consume the same card/button/typography resources**
- [ ] **Step 2: Remove remaining default WPF-looking controls in touched pages**
- [ ] **Step 3: Verify no page route loses selection/context on background snapshot refresh**

---

### Task 6: Full verification and installer convergence

**Files:**
- Tests/contracts only if a real regression requires a narrowly scoped fix.

- [ ] **Step 1: Run exact-head Windows Control Center CI**
  - contract/security tests, WPF STA smoke, warnings-as-errors build, published self-test.

- [ ] **Step 2: Run exact-head Windows Prebuilt Release**
  - build/analyze/self-test, invariant stamp, goal integrity, PowerShell 5.1 install/upgrade/recovery/rollback.

- [ ] **Step 3: Confirm Mac Core and Mac Worker regression gates remain green**
  - Windows-only presentation change must not alter their contracts.

- [ ] **Step 4: Download formal Windows artifact and independently verify**
  - ZIP CRC, no traversal/duplicates, manifest hashes, product version, source head, `native_ci_verified`, `user_install_allowed`.

- [ ] **Step 5: Deliver updated Windows installer only**
  - Keep PR Draft/Open/Unmerged unless explicitly authorized otherwise.
