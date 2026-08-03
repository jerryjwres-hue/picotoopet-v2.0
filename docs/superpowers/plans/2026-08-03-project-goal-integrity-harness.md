# Project Goal Integrity Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent any future agent, build script, or release process from substituting a different product form for the approved PicotooPet architecture, and continue Slice D only as an upgrade to the existing native WPF desktop application.

**Architecture:** A repository-level instruction file defines judgment rules, a machine-readable release contract freezes the approved surface, and a Python validator enforces those rules against actual installer ZIPs. Contract tests include a mutation witness that rejects the already-observed browser Helper pattern. The Windows native release builder writes the required manifest fields and the release workflow runs the validator before Artifact upload.

**Tech Stack:** Markdown project instructions, JSON release contracts, Python 3.12, pytest, PowerShell 7/Windows PowerShell 5.1, C#/.NET 10 WPF, GitHub Draft PR.

## Global Constraints

- The formal Windows UI is the existing `Picotoo Pet AI.exe` native WPF application.
- Slice D must be integrated into the existing Task Center.
- Browser, localhost HTTP UI, WebView, Electron, CLI, script UI, or a separate Helper cannot substitute for the WPF deliverable.
- A platform or tooling blocker may change status to `BLOCKED`, `UNVERIFIED`, or `DIAGNOSTIC`; it may not change the goal.
- `user_install_allowed=true` requires `native_ci_verified=true`.
- No source build, SDK installation, CI Runner duty, or iterative debugging on the user's daily Mac or Windows computers.
- Mac Core + SQLite Queue/Outbox remains the fact source.
- Historical `analysis` tasks remain unsupported and untouched.
- Keep PR #8 Draft and do not merge `main`.

---

### Task 1: Record the governance incident and project instruction

**Files:**
- Create: `AGENTS.md`
- Create: `docs/operations/2026-08-03-goal-degradation-incident.md`

**Interfaces:**
- Consumes: approved design `docs/superpowers/specs/2026-08-03-project-goal-integrity-harness-design.md`.
- Produces: project instructions read by future coding agents and an auditable incident record.

- [ ] **Step 1: Add the non-negotiable rule to `AGENTS.md`**

The file must state that blockers cannot authorize changes to product form, technology, integration point, architecture boundary, user workflow, or acceptance criteria. Any such change requires explicit user approval before implementation.

- [ ] **Step 2: Record GOV-GOAL-001**

Document the old target, the browser Helper substitution, why it violated the target, why r4 is disqualified as Windows Slice D, and the permanent gates added by this plan.

- [ ] **Step 3: Review for loopholes**

Search both files for language that could permit “temporary,” “equivalent,” “fallback,” or “prototype” substitutes to be called a formal deliverable. Remove those loopholes.

- [ ] **Step 4: Commit**

```bash
git add AGENTS.md docs/operations/2026-08-03-goal-degradation-incident.md
git commit -m "docs: forbid project goal degradation"
```

---

### Task 2: Add RED package-goal contract tests

**Files:**
- Create: `tests/contract/test_project_goal_integrity.py`
- Create: `contracts/release/project-goal-invariants.json`

**Interfaces:**
- Produces: the frozen contract document and tests that call `verify_windows_package(package: Path) -> dict[str, object]`.

- [ ] **Step 1: Write a compliant WPF fixture**

Create an in-memory ZIP with one root directory, `payload/Picotoo Pet AI.exe`, the existing Phase 2 INSTALL/VERIFY/ROLLBACK VBS launchers, and a manifest containing:

```json
{
  "release_type": "prebuilt",
  "target": "win-x64",
  "source_build_on_user_pc": false,
  "delivery_surface": "existing-native-wpf-desktop",
  "ui_framework": "WPF",
  "entry_executable": "Picotoo Pet AI.exe",
  "integration_target": "TaskCenter",
  "browser_ui": false,
  "local_http_ui": false,
  "native_ci_verified": true,
  "user_install_allowed": true
}
```

- [ ] **Step 2: Write the Helper mutation witness**

Change the fixture to `release_type=prebuilt-helper`, `delivery_surface=browser-localhost-helper`, `ui_framework=web`, `entry_executable=PicotooPet Slice D.exe`, `browser_ui=true`, and `local_http_ui=true`. Assert `GoalIntegrityError`.

- [ ] **Step 3: Write the native-verification gate**

Set `user_install_allowed=true` and `native_ci_verified=false`. Assert `GoalIntegrityError` mentioning `native_ci_verified`.

- [ ] **Step 4: Write the separate-executable gate**

Set `entry_executable=SliceD.exe`. Assert `GoalIntegrityError` mentioning `Picotoo Pet AI.exe`.

- [ ] **Step 5: Run RED**

```bash
python -m pytest tests/contract/test_project_goal_integrity.py -q
```

Expected: collection failure because `scripts.verify_project_goal_integrity` does not exist.

- [ ] **Step 6: Commit only the tests and contract**

```bash
git add tests/contract/test_project_goal_integrity.py contracts/release/project-goal-invariants.json
git commit -m "test: reject delivery goal degradation"
```

---

### Task 3: Implement the package-goal validator

**Files:**
- Create: `scripts/verify_project_goal_integrity.py`
- Test: `tests/contract/test_project_goal_integrity.py`

**Interfaces:**
- Produces:
  - `class GoalIntegrityError(ValueError)`
  - `verify_windows_package(package: Path | str) -> dict[str, object]`
  - CLI: `python scripts/verify_project_goal_integrity.py <zip> --report <json>`

- [ ] **Step 1: Validate archive structure**

Require a real non-empty ZIP with exactly one top-level directory and `release-manifest.json`.

- [ ] **Step 2: Validate frozen fields**

Read `contracts/release/project-goal-invariants.json` and compare all required manifest values exactly.

- [ ] **Step 3: Validate payload and launchers**

Require:

```text
payload/Picotoo Pet AI.exe
INSTALL_PHASE2_WINDOWS.vbs
VERIFY_PHASE2_WINDOWS.vbs
ROLLBACK_PHASE2_WINDOWS.vbs
```

Reject names containing `SliceDHelper`, `Windows-Helper`, `PicotooPet Slice D.exe`, and files ending in `.html`, `.htm`, `.js`, or `.css`.

- [ ] **Step 4: Enforce install permission**

If `user_install_allowed` is true and `native_ci_verified` is not true, raise `GoalIntegrityError`.

- [ ] **Step 5: Run GREEN**

```bash
python -m pytest tests/contract/test_project_goal_integrity.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Verify the observed r4 package fails**

```bash
python scripts/verify_project_goal_integrity.py PicotooPet-SliceD-Windows-Helper-*-r4.zip
```

Expected: exit 1 and `GOAL_INTEGRITY_VIOLATION` describing `prebuilt-helper` or browser Helper.

- [ ] **Step 7: Commit**

```bash
git add scripts/verify_project_goal_integrity.py
git commit -m "feat: enforce installer goal integrity"
```

---

### Task 4: Add goal fields to the native WPF release

**Files:**
- Modify: `windows/desktop/scripts/Build-Phase2WindowsRelease.ps1`
- Modify: `tests/release/test_windows_prebuilt_delivery.py`

**Interfaces:**
- Consumes: `verify_project_goal_integrity.py` manifest contract.
- Produces: WPF installer manifests that can pass the validator.

- [ ] **Step 1: Add failing release-contract assertions**

Require the build script's manifest to emit:

```text
source_build_on_user_pc=false
delivery_surface=existing-native-wpf-desktop
ui_framework=WPF
entry_executable=Picotoo Pet AI.exe
integration_target=TaskCenter
browser_ui=false
local_http_ui=false
```

- [ ] **Step 2: Run RED**

```bash
python -m pytest tests/release/test_windows_prebuilt_delivery.py -q
```

Expected: failure for missing goal-integrity manifest fields.

- [ ] **Step 3: Update the PowerShell manifest and build report**

Add the exact fields above. Do not add compatibility aliases that permit helper or web surfaces.

- [ ] **Step 4: Run release contracts**

```bash
python -m pytest tests/release/test_windows_prebuilt_delivery.py tests/contract/test_project_goal_integrity.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add windows/desktop/scripts/Build-Phase2WindowsRelease.ps1 tests/release/test_windows_prebuilt_delivery.py
git commit -m "build: declare native WPF delivery invariants"
```

---

### Task 5: Gate Artifact upload

**Files:**
- Modify: `.github/workflows/windows-phase2-release.yml`

**Interfaces:**
- Consumes: built installer ZIP and `scripts/verify_project_goal_integrity.py`.
- Produces: a SUCCESS Artifact only after goal-integrity validation.

- [ ] **Step 1: Add harness paths to workflow triggers**

Include `AGENTS.md`, `contracts/release/project-goal-invariants.json`, `scripts/verify_project_goal_integrity.py`, and `tests/contract/test_project_goal_integrity.py`.

- [ ] **Step 2: Run contract tests before .NET setup**

```powershell
python -m pytest tests/contract/test_project_goal_integrity.py tests/release/test_windows_prebuilt_delivery.py -q
```

- [ ] **Step 3: Validate the actual built ZIP before lifecycle and upload**

```powershell
$package = Get-ChildItem windows/desktop/artifacts/release/PicotooPet-Phase2-Windows-Prebuilt-*.zip -File
python scripts/verify_project_goal_integrity.py $package.FullName --report windows/desktop/artifacts/release/goal-integrity-report.json
if ($LASTEXITCODE -ne 0) { throw "GOAL_INTEGRITY_VIOLATION" }
```

- [ ] **Step 4: Upload the report with the SUCCESS Artifact**

Add `goal-integrity-report.json` to the Artifact paths.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/windows-phase2-release.yml
git commit -m "ci: block non-WPF substitute releases"
```

---

### Task 6: Continue the native Slice D WPF package

**Files:**
- Existing Slice D WPF source under `windows/desktop/src/**`
- Existing WPF smoke tests under `windows/desktop/tests/**`
- Existing release and lifecycle scripts under `windows/desktop/scripts/**` and `windows/desktop/release/**`

**Interfaces:**
- Produces: a self-contained `win-x64` upgrade package for the existing `Picotoo Pet AI.exe`.

- [ ] **Step 1: Confirm the branch still contains the native Task Center Slice D source**

Verify the fixed diagnostic endpoints, `DiagnosticResultViewModel`, `TaskCenterPageViewModel`, and `TaskCenterPage.xaml` changes remain on PR #8.

- [ ] **Step 2: Run zero-cost source and contract gates**

Run Python contracts, XML/XAML source checks, PowerShell parser checks, Manifest checks, and package-goal tests before using any native build minutes.

- [ ] **Step 3: Produce one immutable release-candidate SHA**

Do not trigger native builds on intermediate commits. Freeze one head only after all non-native gates pass.

- [ ] **Step 4: Build on a real Windows environment without involving the user**

Use .NET SDK 10.0.302, build the real WPF solution, run warnings-as-errors, STA `Measure/Arrange/UpdateLayout`, application self-test, and actual package lifecycle.

- [ ] **Step 5: Run goal-integrity validation on the actual ZIP**

The package must pass Task 3's validator before it can be marked installable.

- [ ] **Step 6: Independently verify**

Recompute outer and inner SHA-256, verify every Manifest path/size/hash, single top-level directory, PowerShell 5.1 encoding, lifecycle evidence, and `task_center_rendering=pass`.

- [ ] **Step 7: Deliver only the final native package**

Do not deliver another Helper, browser, local HTTP UI, diagnostic substitute, or unverified installer.

---

## Plan self-review

- Every design requirement maps to a task.
- The previously observed r4 Helper is an explicit mutation witness.
- The contract distinguishes progress blockers from architecture changes.
- `user_install_allowed` cannot be true without native verification.
- The final Windows deliverable is constrained to the existing WPF executable and Task Center.
- No user account creation, billing change, SDK installation, local compilation, or CI Runner duty is required.
- No placeholders or alternate product forms remain.