# Native Cloud Development Contract Status Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the generic “云端开发” empty state with a native, read-only WPF page that exposes the already approved Handoff / Return Contract v1 status and boundaries without installing or invoking any external Provider.

**Architecture:** The page is a Windows presentation-only projection of the frozen `1.0.0` contract. A focused immutable ViewModel owns fixed, bounded display data; the Shell creates the page locally and performs no Mac Core or network call. The navigation becomes available because the contract status page itself exists, while the page explicitly reports that Provider execution remains unavailable.

**Tech Stack:** .NET 10, WPF, existing `PageViewModel`/DataTemplate navigation, zero third-party packages, native Windows smoke executable.

## Global Constraints

- Contract source: `docs/superpowers/specs/2026-08-01-handoff-return-contract-v1-design.md`, status `Approved / Frozen`, version `1.0.0`.
- Do not install, invoke, authenticate to, or adapt Grok Build, Codex, Claude Code, or any external Provider.
- Do not upload files, create a Dev Broker, run shell commands, create worktrees, or expose credentials.
- Protected originals must be reported as prohibited from Handoff packages.
- Provider output must be reported as untrusted until local validation and human review.
- No automatic push, merge, tag, release, or Provider switching.
- The page is native WPF; no browser UI, WebView, Electron, localhost UI, helper process, CLI, or script UI.
- User devices receive a prebuilt Windows package and do not compile source.
- Product version for this feature milestone: `2.3.9.1`.
- Mac Core and Mac Worker packages are not rebuilt unless their runtime/API source changes.

---

### Task 1: Freeze the native page contract with RED tests

**Files:**
- Create: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/CloudDevelopmentSmokeTests.cs`
- Create: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/CloudDevelopmentPageWpfLayoutSmokeTests.cs`
- Modify: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/Program.cs`
- Modify: `tests/contract/test_phase23_windows_source.py`

**Interfaces:**
- Consumes: frozen Handoff / Return Contract v1 terminology.
- Produces: required type names `CloudDevelopmentPageViewModel` and `CloudDevelopmentPage`, plus deterministic display properties used by XAML.

- [ ] **Step 1: Write the failing ViewModel contract test**

Create a smoke test that requires:

```csharp
var page = new CloudDevelopmentPageViewModel();
SmokeAssert.Equal("1.0.0", page.ContractVersion, "Handoff 合同版本错误");
SmokeAssert.Equal("Approved / Frozen", page.ContractStatus, "Handoff 合同状态错误");
SmokeAssert.True(!page.ProviderConfigured, "Phase 2.3 不得伪造 Provider 已配置");
SmokeAssert.True(page.TrustChain.Count == 9, "冻结信任链必须完整显示九个阶段");
SmokeAssert.True(page.SecurityBoundaries.Any(value => value.Contains("Protected 原件", StringComparison.Ordinal)), "缺少 Protected 边界");
SmokeAssert.True(page.SecurityBoundaries.Any(value => value.Contains("本地验证", StringComparison.Ordinal)), "缺少本地复验边界");
SmokeAssert.True(page.SecurityBoundaries.Any(value => value.Contains("自动 push", StringComparison.Ordinal)), "缺少自动发布禁止项");
```

- [ ] **Step 2: Write the failing real WPF test**

On an explicit STA thread, instantiate `CloudDevelopmentPage`, bind the ViewModel, call:

```csharp
page.Measure(new Size(960, 680));
page.Arrange(new Rect(0, 0, 960, 680));
page.UpdateLayout();
page.Dispatcher.Invoke(static () => { }, DispatcherPriority.DataBind);
```

Assert valid Measure/Arrange and that no actionable `Button` exists in the visual tree.

- [ ] **Step 3: Add the smoke tests to `Program.Main`**

Insert:

```csharp
CloudDevelopmentSmokeTests.Run();
CloudDevelopmentPageWpfLayoutSmokeTests.Run();
```

before the retry/network smoke tests.

- [ ] **Step 4: Add a static source contract**

Require the Shell route, App DataTemplate, native XAML, exact contract version, and absence of `WebView`, `Process.Start`, Provider SDK names, localhost UI, and external command execution.

- [ ] **Step 5: Run the Windows behavior gate and verify RED**

Expected failure: missing `CloudDevelopmentPageViewModel` / `CloudDevelopmentPage` or the route still returning `EmptyStatePageViewModel`.

- [ ] **Step 6: Commit**

```bash
git add windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests tests/contract/test_phase23_windows_source.py
git commit -m "test: freeze native cloud development contract page"
```

### Task 2: Implement the focused read-only ViewModel and native WPF page

**Files:**
- Create: `windows/desktop/src/PicotooPet.Desktop/ViewModels/CloudDevelopmentPageViewModel.cs`
- Create: `windows/desktop/src/PicotooPet.Desktop/Views/Pages/CloudDevelopmentPage.xaml`
- Create: `windows/desktop/src/PicotooPet.Desktop/Views/Pages/CloudDevelopmentPage.xaml.cs`
- Modify: `windows/desktop/src/PicotooPet.Desktop/App.xaml`
- Modify: `windows/desktop/src/PicotooPet.Desktop/ViewModels/ShellViewModel.cs`

**Interfaces:**
- Produces `CloudDevelopmentPageViewModel()` with immutable properties:
  - `ContractVersion: string`
  - `ContractStatus: string`
  - `ProviderStatus: string`
  - `ProviderConfigured: bool`
  - `TrustChain: IReadOnlyList<string>`
  - `SecurityBoundaries: IReadOnlyList<string>`
  - `PhaseMilestones: IReadOnlyList<CloudDevelopmentMilestone>`
- Produces `CloudDevelopmentMilestone(string Phase, string Status, string Description)`.

- [ ] **Step 1: Implement immutable bounded display data**

Use fixed arrays only. The nine trust-chain values are:

```text
Mac Handoff Manager
Approval Center
Windows Dev Broker
Provider Adapter
Isolated Worktree / Sandbox
Return Package
Local Validation
Human Review
PR / Merge / Release Approval
```

The page must state that Dev Broker and Provider are not installed, and that the current deliverable is contract visibility only.

- [ ] **Step 2: Implement the native XAML**

Use a two-column Grid with:
- contract/status summary cards;
- ordered trust-chain list;
- security boundary list;
- Phase 2.3, Phase 10A, and Phase 10B milestone cards.

Use only read-only WPF controls (`TextBlock`, `ItemsControl`, `Border`, `ScrollViewer`). Do not add buttons, hyperlinks, file pickers, command bindings, terminal output, or provider configuration inputs.

- [ ] **Step 3: Register the DataTemplate**

Add to `App.xaml`:

```xml
<DataTemplate DataType="{x:Type viewModels:CloudDevelopmentPageViewModel}">
    <pages:CloudDevelopmentPage />
</DataTemplate>
```

- [ ] **Step 4: Route the Shell to the native page**

In both runtime and smoke/static route factories, return `new CloudDevelopmentPageViewModel()` for `NavigationRoute.CloudDevelopment`. Mark the navigation item available with message `Handoff / Return Contract v1 已冻结；Provider 尚未配置。` Availability means the status page can open, not that external execution is enabled.

- [ ] **Step 5: Run focused smoke tests**

Run the native smoke executable. Expected: ViewModel contract, no-action surface, Measure/Arrange/UpdateLayout/DataBind, navigation, Results refresh persistence, Approval page, and existing regressions all pass.

- [ ] **Step 6: Commit**

```bash
git add windows/desktop/src/PicotooPet.Desktop
git commit -m "feat: add native cloud development contract status page"
```

### Task 3: Stamp the feature milestone version and verify affected-component delivery

**Files:**
- Modify: `src/picotoopet_core/product-version.txt`
- Modify: version assertions and package fixtures that represent the current formal release.
- Modify only the Windows release label from approval delivery to contract-status delivery where required by formal package tests.

**Interfaces:**
- Produces user-facing product version `2.3.9.1` consistently in WPF title, shortcut, manifest, package name, and verification reports.

- [ ] **Step 1: Change the canonical version to `2.3.9.1`**

Do not change internal Python distribution version `2.3.0.dev2` or runtime schema versions.

- [ ] **Step 2: Update only current-version assertions**

Replace formal `2.3.8.1` expectations with `2.3.9.1`; preserve historical synthetic upgrade/rollback fixture versions.

- [ ] **Step 3: Run affected-component detection**

Expected:
- Windows native behavior and formal Release: run.
- Mac Core: skip native build/package because no Core/API runtime source changed.
- Mac Worker: skip native build/package because no Worker runtime source changed.

- [ ] **Step 4: Run native Windows behavior gate**

Require contract/security tests, legacy binding RED, Results refresh persistence, Cloud Development WPF layout, warnings-as-errors build, and published self-test.

- [ ] **Step 5: Run the single formal Windows Release gate**

Require goal-integrity stamping, independent ZIP verification, PowerShell 5.1 install, upgrade, activation-failure recovery, rollback, and one formal Artifact.

- [ ] **Step 6: Independently verify the downloaded package**

Recompute the ZIP SHA-256, validate safe paths, one top-level root, exact Manifest coverage, payload hashes/sizes, approved executable allowlist, product version `2.3.9.1`, and exact source head.

- [ ] **Step 7: Keep PR #8 Draft/open/unmerged and update evidence**

Record exact run IDs, Artifact ID, package filename, SHA-256, source head, and the fact that Mac packages were intentionally not rebuilt.

- [ ] **Step 8: Commit any evidence-only update without triggering native packages**

Do not merge `main` and do not mark the PR ready for review.
