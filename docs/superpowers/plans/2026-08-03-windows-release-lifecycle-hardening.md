# Windows Release Lifecycle Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the Task Center fix installer from an internal package preflight into a native-Windows-verified install, verify, activation-recovery, and rollback lifecycle with redirected-desktop coverage and complete evidence.

**Architecture:** Preserve the existing version-directory and atomic `current_version.json` model. Centralize the three Windows shortcut paths in one package helper used by install, verify, and rollback. Add deterministic fixture parameters that default to the current user paths but allow CI to use isolated data roots and normal/OneDrive-style desktops. Exercise the actual packaged scripts in Windows PowerShell 5.1, including two-version rollback and a forced activation failure using a real fast-exiting Windows executable.

**Tech Stack:** Windows PowerShell 5.1, WPF/.NET 10, Python 3.12 + pytest, GitHub Actions `windows-2025`, ZIP/JSON/SHA-256 release artifacts.

## Global Constraints

- Work only in `jerryjwres-hue/picotoopet-v2.0` on `fix/phase23-task-center-run-binding-oneway`.
- Keep pull request #6 open and Draft; do not merge `main`.
- Add and observe failing release-contract tests before production-script changes.
- Keep user installation precompiled; do not require .NET SDK or source compilation on the user's PC.
- Use `[Environment]::GetFolderPath(DesktopDirectory)` by default and cover a redirected OneDrive-style desktop fixture.
- Treat shortcut creation or restoration failure as activation/rollback failure.
- Verify manifest path, SHA-256, and `size_bytes` during install, verify, and rollback.
- Produce install, verification, rollback, and activation-failure-recovery reports from native Windows CI.
- Preserve settings, credentials, databases, logs, results, and historical `analysis` tasks.
- Keep the package `unsigned-ci`; clearly identify it as internal acceptance material rather than a signed public release.

---

### Task 1: Add RED release-contract gates

**Files:**
- Modify: `tests/release/test_windows_prebuilt_delivery.py`
- Modify: `.github/workflows/windows-phase2-release.yml`

**Interfaces:**
- Consumes: current builder, installer, verifier, rollback script, and workflow.
- Produces: explicit assertions for a shared shortcut helper, full lifecycle fixture execution, single-root ZIP, 2.3 Task Center version naming, manifest provenance, and uploaded lifecycle reports.

- [ ] **Step 1: Add failing package-policy assertions**

Assert that install, verify, and rollback dot-source `Phase2Prebuilt.Common.ps1`; verify and rollback check `size_bytes` and shortcut targets; the builder archives one top-level directory and records CI/provenance fields; and the workflow uploads `fixture-evidence/**`.

- [ ] **Step 2: Add native Windows pytest execution to the release workflow**

Install Python 3.12, pytest, and PyYAML, then run:

```powershell
python -m pytest tests/release/test_windows_prebuilt_delivery.py -q
```

- [ ] **Step 3: Run the Draft PR workflow and capture RED**

Expected: the release-contract tests fail because the shared helper, full lifecycle fixture, manifest fields, single-root ZIP, and report upload do not exist yet.

### Task 2: Add a real legacy WPF binding witness

**Files:**
- Create: `windows/desktop/scripts/Test-TaskCenterLegacyBindingRegression.ps1`
- Modify: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/Program.cs`
- Modify: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/TaskCenterWpfLayoutSmokeTests.cs`
- Modify: `.github/workflows/windows-phase2-release.yml`

**Interfaces:**
- Consumes: the real `TaskCenterPage.xaml`, `TaskCenterPage`, and existing STA layout smoke path.
- Produces: `TaskCenterWpfLayoutSmokeTests.RunExpectingLegacyBindingFailure()` and `PHASE23_TASK_CENTER_LEGACY_BINDING_RED=PASS` only after observing the expected WPF `InvalidOperationException` from the mutated legacy bindings.

- [ ] **Step 1: Add an expected-failure smoke mode**

Run the same real page construction, task DataContext, `Measure`, `Arrange`, `UpdateLayout`, and DataBind dispatcher drain. Require an `InvalidOperationException` whose message identifies the read-only binding failure.

- [ ] **Step 2: Add a mutation witness script**

Temporarily replace the two explicit one-way bindings with the historical default bindings, build and run the expected-failure smoke mode, then restore the original XAML in `finally`.

- [ ] **Step 3: Run the witness before the normal release build**

The workflow must fail if the historical bindings do not produce the exact native WPF exception or if the fixed XAML is not restored.

### Task 3: Centralize shortcut behavior and harden reports

**Files:**
- Create: `windows/desktop/release/Phase2Prebuilt.Common.ps1`
- Modify: `windows/desktop/release/Install-Phase2Prebuilt.ps1`
- Modify: `windows/desktop/release/Verify-Phase2Prebuilt.ps1`
- Modify: `windows/desktop/release/Rollback-Phase2Prebuilt.ps1`

**Interfaces:**
- Produces:
  - `Get-PicotooShortcutPaths([string]$DesktopDirectory)`
  - `Set-PicotooShortcuts([string]$Executable, [string]$DesktopDirectory)`
  - `Assert-PicotooShortcuts([string]$Executable, [string]$DesktopDirectory)`
  - `Remove-PicotooShortcuts([string]$DesktopDirectory)`
- Adds optional deterministic fixture parameters while preserving no-argument user behavior.

- [ ] **Step 1: Create the shared shortcut helper**

Resolve the system `DesktopDirectory` when no override is supplied, create desktop/start-menu/startup shortcuts, and return a structured path map after validating every `.lnk` `TargetPath`.

- [ ] **Step 2: Update installation activation and recovery**

Dot-source the helper, accept isolated `DataRoot` and `DesktopDirectory`, support an activation self-test for CI, suppress Notepad only when explicitly requested, and include all shortcut paths/results in the install report. Any shortcut failure must enter the existing activation recovery path.

- [ ] **Step 3: Update VERIFY**

Validate path safety, SHA-256, and file size; validate all shortcut targets; add an offline package-only mode that runs the application and diagnostics self-tests; and write release validation details into the verification report.

- [ ] **Step 4: Update ROLLBACK**

Validate path safety, SHA-256, and file size before switching; recreate and assert all three shortcuts after switching; include pointer, hash, shortcut, and launch results in the rollback report; and restore the pre-rollback pointers and all three shortcuts if any post-switch step fails.

### Task 4: Exercise the full packaged lifecycle

**Files:**
- Modify: `windows/desktop/scripts/Test-Phase2WindowsRelease.ps1`

**Interfaces:**
- Consumes: the built ZIP and all packaged release scripts.
- Produces: isolated normal-desktop and redirected-desktop evidence under `windows/desktop/artifacts/release/fixture-evidence`.

- [ ] **Step 1: Resolve and verify the single package root**

Expand the real ZIP, require exactly one top-level directory, read the manifest with strict UTF-8, check files, and validate PowerShell syntax and VBS encoding.

- [ ] **Step 2: Run two-version install/verify/rollback fixtures**

For each desktop fixture, install version A, install version B, verify B in offline package mode, deliberately corrupt the desktop shortcut, roll back to A, and require all three shortcuts and pointers to target A.

- [ ] **Step 3: Run activation-failure recovery**

Create a fixture package whose main executable is a copied fast-exiting Windows executable with updated manifest hash/size. Require installation failure, a fail report, restoration of the prior current/previous pointers, and restoration of all shortcut targets.

- [ ] **Step 4: Copy evidence out of the temporary fixture**

Copy install A/B, verify B, rollback A, and activation-failure reports for both desktop layouts into the release artifact evidence directory.

### Task 5: Update package structure and provenance

**Files:**
- Modify: `windows/desktop/scripts/Build-Phase2WindowsRelease.ps1`
- Modify: `windows/desktop/release/README_INSTALL_CN.txt`
- Modify: `.github/workflows/windows-phase2-release.yml`

**Interfaces:**
- Produces: `2.3.0-slice-b-taskcenter-fix-<run>-<sha>` packages with a single root directory and manifest fields for target architecture, native CI, install permission, source head/ref, build commit, and unsigned status.

- [ ] **Step 1: Change the default version label**

Use `2.3.0-slice-b-taskcenter-fix-$runNumber-$commit`.

- [ ] **Step 2: Add manifest provenance and release policy**

Record `native_ci_verified`, `user_install_allowed`, `source_head`, `source_ref`, and `build_commit`, while keeping `signature.status=unsigned-ci`.

- [ ] **Step 3: Archive the package directory itself**

Use `Compress-Archive -LiteralPath $packageRoot` so extraction creates one top-level folder.

- [ ] **Step 4: Document architecture and trust status**

README must state `win-x64`, native Windows CI verification, allowed user installation, no user-side build, and possible SmartScreen warning because the package is unsigned.

### Task 6: Verify and publish refreshed Draft evidence

**Files:**
- Update: pull request #6 description.

**Interfaces:**
- Consumes: final successful Windows workflow runs and artifact.
- Produces: refreshed installer ZIP, SHA-256, build report, install/verify/rollback fixture reports, RED/GREEN run IDs, and exact base/head references.

- [ ] **Step 1: Run all native Windows checks**

Require release pytest, legacy WPF mutation witness, normal WPF smoke, warnings-as-errors build, app/diagnostic self-tests, PowerShell 5.1 package lifecycle fixtures, and artifact upload.

- [ ] **Step 2: Download and independently verify the artifact**

Check outer artifact SHA-256, inner package SHA-256, checksum-file equality, ZIP integrity, manifest policy/provenance, and the status of every lifecycle report.

- [ ] **Step 3: Update the Draft PR**

Record failures used as RED evidence, final GREEN runs, artifact ID, hashes, fixture report inventory, source head, synthetic merge commit, and confirmation that `main` remains untouched.
