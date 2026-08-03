# Task Center Run Binding Crash Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent the Windows Task Center from crashing when WPF lays out read-only `TaskRowViewModel.Priority` and `TaskRowViewModel.TimeoutSeconds` values, then add permanent logging and page-level fault containment.

**Architecture:** Keep the view model read-only to consumers and correct the binding direction at the XAML boundary. Add a source-level regression gate plus a real STA WPF page layout smoke test. Add a `NavigationContentHost` fault boundary that contains recoverable page layout failures and replaces the failed route with a safe explanatory page, while the application-level WPF unhandled-exception handler records any exception that escapes page containment.

**Tech Stack:** .NET 10, WPF, C# smoke executable, Python pytest contract tests, GitHub Actions `windows-2025`, PowerShell release packaging.

## Global Constraints

- Base the work on the latest branch containing complete Slice B/C source: `migration/export-slice-c-to-picotoopet-v2-20260802`.
- Add and observe failing regression tests before changing production code.
- Run the real WPF page through `Measure`, `Arrange`, and `UpdateLayout`.
- Log WPF unhandled exceptions through the existing redacting `SafeFileLogger`.
- Contain recoverable page layout failures without terminating the Control Center or breaking later navigation.
- Run native Windows CI and produce a precompiled installer ZIP plus SHA-256.
- Do not compile on the user's PC.
- Do not merge `main`; keep the pull request in Draft state.

---

### Task 1: Add red regression coverage

**Files:**
- Create: `tests/contract/test_phase23_task_center_run_binding.py`
- Create: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/TaskCenterWpfLayoutSmokeTests.cs`
- Modify: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/Program.cs`
- Modify: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/PicotooPet.Desktop.Core.SmokeTests.csproj`

**Interfaces:**
- Consumes: `TaskCenterPage`, `TaskCenterPageViewModel.CreateForSmokeTest`, `TaskRecord`, `WorkerSnapshot.NotDeployed`.
- Produces: `TaskCenterWpfLayoutSmokeTests.Run()` invoked from the smoke executable on an STA thread.

- [x] **Step 1: Add the source regression test**

```python
def test_task_center_read_only_run_bindings_are_explicitly_one_way() -> None:
    xaml = TASK_CENTER_XAML.read_text(encoding="utf-8")

    assert 'Text="{Binding Priority, Mode=OneWay}"' in xaml
    assert 'Text="{Binding TimeoutSeconds, Mode=OneWay}"' in xaml
```

- [x] **Step 2: Add the real WPF layout smoke test**

```csharp
var page = new TaskCenterPage
{
    DataContext = viewModel,
};
page.Measure(new Size(960, 680));
page.Arrange(new Rect(0, 0, 960, 680));
page.UpdateLayout();
```

- [x] **Step 3: Run the branch through the Draft PR Windows workflow**

Observed RED: Windows Control Center CI run 143 failed on the missing explicit one-way bindings.

### Task 2: Apply the minimal XAML fix

**Files:**
- Modify: `windows/desktop/src/PicotooPet.Desktop/Views/Pages/TaskCenterPage.xaml`

**Interfaces:**
- Consumes: read-only `TaskRowViewModel.Priority` and `TaskRowViewModel.TimeoutSeconds`.
- Produces: explicit one-way `Run.Text` bindings.

- [x] **Step 1: Change only the two failing bindings**

```xml
<Run Text="{Binding Priority, Mode=OneWay}" />
<Run Text="{Binding TimeoutSeconds, Mode=OneWay}" />
```

- [x] **Step 2: Re-run all required native Windows checks**

Observed GREEN: Windows Control Center CI run 146 and Phase 2 Windows Prebuilt Release run 141 passed.

### Task 3: Publish initial evidence without merging

**Files:**
- No production file changes.

**Interfaces:**
- Consumes: successful GitHub Actions run artifacts.
- Produces: Draft PR, precompiled installer ZIP, SHA-256 text file, build report, and self-test report.

- [x] **Step 1: Download and verify the uploaded artifact**

The uploaded checksum entry and an independent SHA-256 calculation matched.

- [x] **Step 2: Keep the PR in Draft state**

The PR remains Draft and targets `migration/export-slice-c-to-picotoopet-v2-20260802`.

### Task 4: Add red tests for WPF logging and page fault containment

**Files:**
- Create: `tests/contract/test_phase23_wpf_fault_boundaries.py`
- Create: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/NavigationFaultBoundarySmokeTests.cs`
- Modify: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/NavigationSmokeTests.cs`
- Modify: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/Program.cs`

**Interfaces:**
- Consumes: desired `NavigationContentHost.NavigationFaulted` event and desired `ShellViewModel.ShowNavigationFailure(NavigationRoute)` recovery method.
- Produces: a native STA test that forces a child element to throw during `Measure` and proves the host can recover with a replacement page.

- [ ] **Step 1: Add source contract gates**

Assert that `App` registers `DispatcherUnhandledException`, logs through `SafeFileLogger`, and `ShellWindow` uses a navigation fault boundary.

- [ ] **Step 2: Add a real WPF faulting-layout smoke test**

Use a `FrameworkElement` whose `MeasureOverride` throws `InvalidOperationException`; verify `NavigationContentHost.Measure`, `Arrange`, and `UpdateLayout` do not terminate the test process, the fault event is raised, and a replacement child can complete layout.

- [ ] **Step 3: Add the Shell fallback-state assertion**

Call `ShowNavigationFailure(NavigationRoute.TaskCenter)` and assert the current page is a safe `EmptyStatePageViewModel` with a user-visible isolation message.

- [ ] **Step 4: Run native Windows CI and capture RED**

Expected: contract tests and/or WPF smoke compilation fail because the logging registration, fault boundary, and fallback API do not exist yet.

### Task 5: Implement the minimal permanent defenses

**Files:**
- Create: `windows/desktop/src/PicotooPet.Desktop/Views/NavigationContentHost.cs`
- Modify: `windows/desktop/src/PicotooPet.Desktop/App.xaml.cs`
- Modify: `windows/desktop/src/PicotooPet.Desktop/Views/ShellWindow.xaml`
- Modify: `windows/desktop/src/PicotooPet.Desktop/Views/ShellWindow.xaml.cs`
- Modify: `windows/desktop/src/PicotooPet.Desktop/ViewModels/ShellViewModel.cs`

**Interfaces:**
- Produces: `NavigationContentHost`, `NavigationFaultEventArgs`, `ShellViewModel.ShowNavigationFailure(NavigationRoute)`.
- Uses: existing `SafeFileLogger.Error(string, Exception)` redaction boundary.

- [ ] **Step 1: Register global WPF unhandled-exception logging**

Store the existing `SafeFileLogger` in `App`, subscribe to `DispatcherUnhandledException`, log the exception, and leave unknown unhandled exceptions unmarked so the application does not silently swallow process-level faults.

- [ ] **Step 2: Add the page layout fault boundary**

Catch only recoverable exceptions escaping `ContentControl.MeasureOverride` or `ArrangeOverride`, suppress repeated layout attempts for the same failed content, and queue a single `NavigationFaulted` callback on the Dispatcher.

- [ ] **Step 3: Replace a failed route with a safe page**

Log the route-specific failure in `ShellWindow`, then call `ShellViewModel.ShowNavigationFailure` so the failed page is replaced while other navigation items remain usable.

- [ ] **Step 4: Run focused and full native Windows checks**

Expected: contract/security tests, WPF smoke executable, warnings-as-errors build, self-tests, PowerShell 5.1 package verification, and release packaging all pass.

### Task 6: Refresh delivery evidence

**Files:**
- Update: Draft PR description and evidence references.

**Interfaces:**
- Consumes: final successful workflow runs and artifact.
- Produces: refreshed precompiled ZIP, SHA-256, build report, self-test report, install/verify/rollback evidence.

- [ ] **Step 1: Verify the final artifact independently**

Download the successful release artifact and compare the calculated SHA-256 with the packaged checksum file.

- [ ] **Step 2: Update Draft PR evidence**

Record RED and GREEN run IDs, final artifact name, SHA-256, base/head SHAs, and confirm that `main` remains untouched.
