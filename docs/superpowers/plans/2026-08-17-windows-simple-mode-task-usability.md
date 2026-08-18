# Windows Simple Mode Task Usability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix simple-mode task actions, make work-component cards real navigation entries, redesign task detail into a readable split layout, add keyword/category/date filtering to In Progress/Completed/Deleted, and ship a verified Windows UI Preview installer.

**Architecture:** Keep Windows as the Control Center and Mac Core as the task/result source of truth. Reuse existing cancel/hide/restore APIs and existing Shell navigation routes; filtering is a Windows presentation concern over the current Mac Core snapshot and must not introduce a parallel task store. Task detail continues to use the fixed TaskDetail gateway/result contracts only.

**Tech Stack:** .NET/WPF, C#, XAML, Python contract tests, PowerShell Windows release/lifecycle harnesses, GitHub Actions.

**Spec:** User-approved requirements in the 2026-08-17 project conversation and screenshots.

## Global Constraints

- Work only on `feature/windows-ui-interaction-polish-2.3.27.1`; do not modify the Maotai asset branch.
- Preserve product version `2.3.26.1`; this remains a `2.3.27.1` UI delivery increment.
- Windows must not directly execute crawler/research providers; Mac Core remains task/result/audit source of truth.
- Do not weaken Settings token handling or formal Maotai/full-release gates.
- Do not invent permanent deletion: active tasks cancel; completed tasks hide into Deleted; deleted tasks restore unless a real hard-delete contract exists.
- Final user deliverable is a Windows UI Preview installer with `full_release=false`, native Windows CI and lifecycle evidence.

---

### Task 1: Encode the requested behavior as RED contracts

**Files:**
- Create: `tests/contract/test_windows_simple_mode_task_usability.py`

**Interfaces:**
- Consumes: current WPF XAML/ViewModels and existing `ControlCenterSession.CancelTaskAsync`, hide, restore contracts.
- Produces: contract assertions for action semantics, work-card navigation, split detail layout, and unified filtering.

- [ ] **Step 1: Write failing contract tests**

Assert that In Progress uses explicit cancel labels/`CancelTaskAsync`; Completed uses move-to-deleted/hide; Deleted restores. Assert task list XAML binds keyword/category/start/end-date controls and clear-filter behavior. Assert home work cards are actionable and code-behind routes to existing `Projects`, `BusinessAutomation`, `Automation`, and `Results`/review surfaces. Assert TaskDetailWindow has a named two-column detail workspace with separate metadata and result panes.

- [ ] **Step 2: Run Windows CI to verify RED**

Run the repository Windows control-center workflow through a commit and confirm only the new contracts fail for the intended missing behavior.

- [ ] **Step 3: Commit RED evidence**

Commit the contract file before production changes.

---

### Task 2: Correct task lifecycle actions and add unified filters

**Files:**
- Modify: `windows/desktop/src/PicotooPet.Desktop/ViewModels/OperatorProjection.cs`
- Modify: `windows/desktop/src/PicotooPet.Desktop/ViewModels/OperatorTaskListPageViewModel.cs`
- Modify: `windows/desktop/src/PicotooPet.Desktop/Views/Pages/OperatorTaskListPage.xaml`
- Modify: `windows/desktop/src/PicotooPet.Desktop/Views/Pages/OperatorTaskListPage.xaml.cs`

**Interfaces:**
- Consumes: `OperatorSnapshot`, `OperatorTaskCard`, `ControlCenterSession.CancelTaskAsync`, `HideTasksAsync`, `RestoreTasksAsync`.
- Produces: filtered visible `Items`, filter state (`Keyword`, category, start/end date), mode-specific action labels/semantics.

- [ ] **Step 1: Make In Progress cancel instead of hide/delete**

Use `CancelTaskAsync(taskId)` for In Progress single/bulk actions. Use `HideTasksAsync` only for Completed and `RestoreTasksAsync` only for Deleted. Labels are `取消任务/取消所选`, `移到已删除`, and `恢复/恢复所选` respectively.

- [ ] **Step 2: Preserve task metadata needed by filters**

Extend `OperatorTaskCard` with task type/category, created date, and safe searchable goal text derived from approved payload summary fields only.

- [ ] **Step 3: Add filter state and deterministic local filtering**

Keyword matches title, task id, task type/category, and safe goal text case-insensitively. Category exposes All plus categories present in the current bucket. Start/end dates filter by CreatedAt local date inclusively. Clearing filters restores the full current bucket.

- [ ] **Step 4: Add one shared filter bar to all three modes**

Bind keyword TextBox, category ComboBox, start/end DatePickers, Search/Apply and Clear controls to the same ViewModel; keep existing selection actions scoped to the filtered `Items` only.

- [ ] **Step 5: Run contracts/build and commit GREEN**

Verify contract tests and WPF compilation on native Windows CI.

---

### Task 3: Make Work Components real actions

**Files:**
- Modify: `windows/desktop/src/PicotooPet.Desktop/Views/Pages/OperatorHomePage.xaml`
- Modify: `windows/desktop/src/PicotooPet.Desktop/Views/Pages/OperatorHomePage.xaml.cs`

**Interfaces:**
- Consumes: existing `NavigationRoute` values and `ShellWindow.NavigateFromOperator`.
- Produces: four keyboard/click actionable cards without adding a second navigation system.

- [ ] **Step 1: Convert decorative cards to styled Buttons**

Keep the approved card visuals while wiring real click handlers and hand cursor only on actionable controls.

- [ ] **Step 2: Route to existing real pages**

`项目 / 调研` → `Projects`; `业务分析` → `BusinessAutomation`; `自动化` → `Automation`; `结果 / 审核` → `Results` (with existing sidebar review route remaining unchanged).

- [ ] **Step 3: Run interaction contracts/build and commit GREEN**

Confirm no dead-button/hand-cursor regressions.

---

### Task 4: Redesign Task Detail into a split workspace

**Files:**
- Modify: `windows/desktop/src/PicotooPet.Desktop/Views/Pages/TaskDetailWindow.xaml`
- Optionally modify: `windows/desktop/src/PicotooPet.Desktop/ViewModels/TaskDetailViewModel.cs` only for safe display properties already derivable from `TaskRecord`.

**Interfaces:**
- Consumes: existing `TaskDetailViewModel` and fixed research/diagnostic result retrieval contracts.
- Produces: left metadata pane and right result pane with readable scrolling, responsive minimum sizing, and unchanged safe result authority.

- [ ] **Step 1: Build the two-column layout**

Use a named `DetailWorkspace` grid with `MetadataPane` and `ResultPane`; keep title header and close action outside the split area.

- [ ] **Step 2: Improve result readability without new data sources**

Show status/goal/times/attempts on the left and result title/body on the right. Keep arbitrary file browsing forbidden.

- [ ] **Step 3: Run contracts/build and commit GREEN**

Confirm WPF XAML compiles and task detail gateway tests remain intact.

---

### Task 5: Native verification and installable UI Preview

**Files:**
- Reuse: `.github/workflows/windows-ui-preview-release.yml`
- Reuse: `windows/desktop/scripts/Build-Phase2WindowsRelease.ps1`

**Interfaces:**
- Consumes: completed UI branch.
- Produces: verified GitHub Actions artifact and user-friendly installer ZIP + SHA-256.

- [ ] **Step 1: Run full Windows contract/native CI**

Require all applicable Python contracts green, WPF build with zero errors, and `PHASE23_UI_INTERACTION_SMOKE=PASS`.

- [ ] **Step 2: Run Windows UI Preview release**

Require `ValidationScope=UiPreview`, installer build PASS, install/verify/upgrade/recovery/rollback lifecycle PASS, and artifact upload PASS.

- [ ] **Step 3: Download and verify artifact**

Verify GitHub artifact digest, inner installer SHA-256, `unzip -t`, and manifest fields including `validation_scope=windows-ui-preview`, `full_release=false`, `native_ci_verified=true`, and `user_install_allowed=true`.

- [ ] **Step 4: Deliver installer**

Provide the new installer ZIP and SHA file to the user with the existing `INSTALL_PHASE2_WINDOWS.vbs`, `VERIFY_PHASE2_WINDOWS.vbs`, and rollback instructions.
