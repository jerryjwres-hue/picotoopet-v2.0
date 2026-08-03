# Task Center Run Binding Crash Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent the Windows Task Center from crashing when WPF lays out read-only `TaskRowViewModel.Priority` and `TaskRowViewModel.TimeoutSeconds` values.

**Architecture:** Keep the view model read-only to consumers and correct the binding direction at the XAML boundary. Add a source-level regression gate plus a real STA WPF page layout smoke test that constructs `TaskCenterPage`, assigns a populated view model, and executes `Measure`, `Arrange`, and `UpdateLayout` on a native Windows runner.

**Tech Stack:** .NET 10, WPF, C# smoke executable, Python pytest contract tests, GitHub Actions `windows-2025`, PowerShell release packaging.

## Global Constraints

- Base the work on the latest branch containing complete Slice B/C source: `migration/export-slice-c-to-picotoopet-v2-20260802`.
- Add and observe failing regression tests before changing production XAML.
- Run the real WPF page through `Measure`, `Arrange`, and `UpdateLayout`.
- Run native Windows CI and produce a precompiled installer ZIP plus SHA-256.
- Do not compile on the user's PC.
- Do not merge `main`; create a Draft PR.

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

- [ ] **Step 1: Add the source regression test**

```python
def test_task_center_read_only_run_bindings_are_explicitly_one_way() -> None:
    xaml = TASK_CENTER_XAML.read_text(encoding="utf-8")

    assert 'Text="{Binding Priority, Mode=OneWay}"' in xaml
    assert 'Text="{Binding TimeoutSeconds, Mode=OneWay}"' in xaml
```

- [ ] **Step 2: Add the real WPF layout smoke test**

```csharp
var page = new TaskCenterPage
{
    DataContext = viewModel,
};
page.Measure(new Size(960, 680));
page.Arrange(new Rect(0, 0, 960, 680));
page.UpdateLayout();
```

- [ ] **Step 3: Run the branch through the Draft PR Windows workflow**

Expected: the source regression test fails because both `Run.Text` bindings omit `Mode=OneWay`; the WPF smoke path must also execute on `windows-2025`.

### Task 2: Apply the minimal XAML fix

**Files:**
- Modify: `windows/desktop/src/PicotooPet.Desktop/Views/Pages/TaskCenterPage.xaml`

**Interfaces:**
- Consumes: read-only `TaskRowViewModel.Priority` and `TaskRowViewModel.TimeoutSeconds`.
- Produces: explicit one-way `Run.Text` bindings.

- [ ] **Step 1: Change only the two failing bindings**

```xml
<Run Text="{Binding Priority, Mode=OneWay}" />
<Run Text="{Binding TimeoutSeconds, Mode=OneWay}" />
```

- [ ] **Step 2: Re-run all required native Windows checks**

Expected: contract/security tests, smoke executable, WPF solution build, app self-test, package build, package verification, and artifact upload all pass.

### Task 3: Publish evidence without merging

**Files:**
- No production file changes.

**Interfaces:**
- Consumes: successful GitHub Actions run artifacts.
- Produces: Draft PR, precompiled installer ZIP, SHA-256 text file, build report, and self-test report.

- [ ] **Step 1: Download and verify the uploaded artifact**

Run SHA-256 over the downloaded installer ZIP and compare it with the uploaded `.sha256.txt` entry.

- [ ] **Step 2: Keep the PR in Draft state**

The PR base remains `migration/export-slice-c-to-picotoopet-v2-20260802`; do not merge or retarget to `main`.
