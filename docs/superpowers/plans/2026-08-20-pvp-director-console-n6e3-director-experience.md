# PVP Director Console N6E3 Director Experience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a Chinese-first simplified Native director console with self-healing Director Core connectivity and atomic batch delete/restore, packaged as a GitHub-CI-prebuilt Windows installer.

**Architecture:** Keep the frozen Director Core / Canonical / Proposal / Tombstone architecture unchanged. Add atomic batch mutation functions to the existing SQLite control plane, add a Native Core Supervisor around the existing loopback process/client, and simplify WPF presentation while keeping advanced controls available on demand.

**Tech Stack:** Python 3.11 stdlib + SQLite, .NET 10 WPF/C#, GitHub Actions windows-2025, Windows PowerShell 5.1/CMD installer bootstrap.

**Spec:** `docs/superpowers/specs/2026-08-20-pvp-director-console-n6e3-director-experience-design.md`

## Global Constraints
- Canonical source remains read-only.
- No permanent purge; delete is soft delete/tombstone only.
- Delete/restore writes require `HUMAN_DIRECTOR`.
- No media submission, `/prompt`, or `queue_prompt`.
- User PC performs no `dotnet build`, `dotnet publish`, SDK install, pip install, conda install, or model download.
- Build/publish verification occurs on GitHub `windows-2025`.

---

### Task 1: Atomic batch delete/restore API

**Files:**
- Modify: `payload/producer/extensions/director_console_native_v2/src/pvp_director_native_v2/deleted_items.py`
- Modify: `payload/producer/extensions/director_console_native_v2/src/pvp_director_native_v2/server_v2.py`
- Test: `payload/producer/extensions/director_console_native_v2/tests/test_n6e3_batch_deleted_items.py`

**Interfaces:**
- Produces: `preview_batch_delete(store,node_ids,expected_revision)`, `soft_delete_batch(store,node_ids,actor,reason,expected_revision)`, `preview_batch_restore(store,tombstone_ids,expected_revision)`, `restore_deleted_batch(store,tombstone_ids,actor,expected_revision)`.
- HTTP: `POST /api/v2/nodes/batch-delete-preview`, `/api/v2/nodes/batch-delete`, `/api/v2/deleted/batch-restore-preview`, `/api/v2/deleted/batch-restore`.

- [ ] Write tests for successful multi-node delete with exactly one revision increment and two tombstones.
- [ ] Run focused tests and confirm RED due missing batch functions.
- [ ] Implement batch preview/delete in one transaction.
- [ ] Run focused tests GREEN.
- [ ] Add tests for atomic rollback, duplicate IDs, PROJECT:ROOT and actor restriction.
- [ ] Implement batch restore with one revision increment and one transaction.
- [ ] Run focused + full backend regression.

### Task 2: Director Core Supervisor

**Files:**
- Modify: `native/PVP.DirectorConsole/Services/DirectorCoreProcessManager.cs`
- Modify: `native/PVP.DirectorConsole/ViewModels/MainWindowViewModel.cs`
- Test: `native/tests/test_n6e3_director_experience_contract.py`

**Interfaces:**
- `DirectorCoreProcessManager.RunSupervisorAsync(Func<CoreSupervisorStatus,Task>, CancellationToken)` continuously probes/restarts owned Core.
- `CoreSupervisorStatus` exposes `State`, `Attempt`, `MaxAttempts`, `Reason`.

- [ ] Add source-contract assertions for 0.5/1/2/4/8 second backoff, persistent log file, process-exit detection and supervisor loop.
- [ ] Run test and confirm RED.
- [ ] Implement process output redirection/logging and supervisor recovery loop.
- [ ] Update ViewModel initialization/polling so recovery is automatic and last snapshot remains visible.
- [ ] Run Native contract tests GREEN.

### Task 3: Chinese-first simplified WPF shell

**Files:**
- Modify: `native/PVP.DirectorConsole/ViewModels/ShellModels.cs`
- Modify: `native/PVP.DirectorConsole/ViewModels/MainWindowViewModel.cs`
- Modify: `native/PVP.DirectorConsole/MainWindow.xaml`
- Test: `native/tests/test_n6e3_director_experience_contract.py`

**Interfaces:**
- `NodeItem.DisplayLifecycle` maps technical lifecycle to Chinese.
- `MainWindowViewModel.IsInspectorVisible` and `IsTimelineVisible` default false.
- Advanced English/technical execution details remain under System/advanced panels.

- [ ] Add RED assertions for Chinese labels, default collapsed advanced panels, no fixed empty timeline row, no top-level manual reconnect button.
- [ ] Implement Chinese display mappings and simplified labels/navigation.
- [ ] Collapse advanced inspector/timeline by default; make timeline row auto/zero when hidden.
- [ ] Run Native contract tests GREEN.

### Task 4: Native batch delete/restore interaction

**Files:**
- Modify: `native/PVP.DirectorConsole/Models/ApiModels.cs`
- Modify: `native/PVP.DirectorConsole/Services/DirectorCoreClient.cs`
- Modify: `native/PVP.DirectorConsole/ViewModels/ShellModels.cs`
- Modify: `native/PVP.DirectorConsole/ViewModels/MainWindowViewModel.cs`
- Modify: `native/PVP.DirectorConsole/MainWindow.xaml`
- Test: `native/tests/test_n6e3_director_experience_contract.py`

**Interfaces:**
- Client methods: `PreviewBatchDeleteAsync`, `BatchDeleteAsync`, `PreviewBatchRestoreAsync`, `BatchRestoreAsync`.
- Node/Deleted wrapper items expose `IsSelectedForBatch`.
- Actions: `ToggleBatchSelection`, `SelectAllVisible`, `ClearBatchSelection`, `PreviewBatchDelete`, `ConfirmBatchDelete`, `SelectAllDeleted`, `ClearDeletedSelection`, `PreviewBatchRestore`, `ConfirmBatchRestore`.

- [ ] Add RED assertions for batch DTO/client/actions and checkbox bindings.
- [ ] Implement DTO/client calls.
- [ ] Implement selection state and batch preview/confirm ViewModel logic.
- [ ] Add prominent list toolbar and deleted-page batch restore toolbar.
- [ ] Run Native contract tests GREEN.

### Task 5: GitHub Windows prebuilt release and installer

**Files:**
- Update Native source bundle in `pvp/director-console-native-v2-bootstrap/native.part*.b64`
- Update `NATIVE_BUNDLE.sha256`
- Update version/package metadata to `2.0.0-n6e3-director-experience`
- Reuse N6E2.2 deterministic prebuilt installer transaction.

- [ ] Run full backend/native/package verification locally.
- [ ] Rebuild deterministic source ZIP and upload bundle chunks + SHA to isolated feature branch.
- [ ] Wait for GitHub windows-2025 workflow; require VBS/CMD smoke, installer parse/bootstrap, Native contracts, WPF build, publish and EXE self-test all GREEN.
- [ ] Download the exact CI artifact.
- [ ] Build final N6E3 PREBUILT installer ZIP with the exact CI EXE and updated Director Core extension.
- [ ] Verify manifest, hashes, ZIP CRC/paths and forbidden-build/download scans from clean extraction.
- [ ] Deliver only the N6E3 installer ZIP and SHA sidecar for real-machine acceptance.
