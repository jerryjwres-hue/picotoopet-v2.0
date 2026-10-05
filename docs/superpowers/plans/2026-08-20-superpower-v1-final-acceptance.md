# PicotooPet AI — Superpower v1.0 Final Acceptance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish Task 8/9 and produce a natively verified Windows Preview + Mac arm64 acceptance set without weakening the existing Maotai V2 full-release art gate.

**Architecture:** Reuse Mac Core as the unique source of truth. Reuse the existing durable `/api/v1/tasks/{task_id}/progress` contract and wire it into the Windows task detail experience; do not add a second progress database or client-owned estimation. Keep REST authoritative and WebSocket advisory, then validate recovery/fault paths before packaging.

**Tech Stack:** Python/FastAPI/SQLite on Mac Core, native arm64 Mac Worker, .NET 10 WPF Windows Control Center, GitHub Actions, VBS/PowerShell packaging wrappers.

**Spec:** Existing project architecture and PR #41 autonomous-intelligence E2E contract.

## Global Constraints

- Windows remains control plane only; it does not execute crawlers or external providers directly.
- Mac Core remains the source of truth for goals, tasks/workflows, evidence, results and audit.
- WebSocket loss must degrade realtime notifications only while REST remains healthy.
- Progress must use durable Core-owned facts; no elapsed-time fake percentages.
- Formal Windows Full Release remains blocked by the genuine Maotai V2 art gate; Preview packaging must not bypass it.
- Codex/Claude provider execution remains governed by Frugal Coding approvals and manual quota confirmation; these acceptance tasks do not trigger paid/external provider sessions.

---

### Task 8: Durable task-progress projection in Windows task detail

**Files:**
- Modify: `windows/desktop/src/PicotooPet.Desktop.Core/Contracts/ApiContracts.cs`
- Modify: `windows/desktop/src/PicotooPet.Desktop.Core/Networking/MacCoreClient.cs`
- Modify: `windows/desktop/src/PicotooPet.Desktop/Services/ControlCenterSession.cs`
- Modify: `windows/desktop/src/PicotooPet.Desktop/ViewModels/TaskDetailViewModel.cs`
- Modify: `windows/desktop/src/PicotooPet.Desktop/Views/Pages/TaskDetailWindow.xaml`
- Test: `tests/contract/test_phase2_windows_source.py`

**Interfaces:**
- Consumes: `GET /api/v1/tasks/{task_id}/progress` returning Mac Core durable progress snapshots.
- Produces: safe Windows progress projection with stage, optional `completed/total/percent`, latest message, last activity and bounded recent events.

- [ ] **Step 1: Write failing Windows source-contract assertions**

Assert that Windows defines `TaskProgressSnapshot`, exposes a `GetTaskProgressAsync` client/session method, and binds progress/activity text in `TaskDetailWindow.xaml`.

- [ ] **Step 2: Run contract test to verify RED**

Run: `python -m pytest tests/contract/test_phase2_windows_source.py -q`
Expected: FAIL only on the new progress-projection assertions.

- [ ] **Step 3: Add minimal safe progress contracts and client wiring**

Mirror only the existing server fields; keep `details` as JSON and do not expose arbitrary file browsing or provider secrets.

- [ ] **Step 4: Add task-detail presentation**

For running/queued tasks, show current stage, truthful `N/M` only when both values exist, server percent only when supplied, latest durable message, last activity time and recent activity. Keep result rendering unchanged for completed known task types.

- [ ] **Step 5: Run Windows contract regression**

Run: `python -m pytest tests/contract/test_phase2_windows_source.py -q`
Expected: PASS.

### Task 9: Public product identity and recovery/fault acceptance

**Files:**
- Modify: Windows shell/product identity surfaces already used by the Preview build.
- Modify/Test: existing Windows self-test/diagnostics acceptance sources.

**Interfaces:**
- Consumes: existing engineering version `2.3.x` and dual-channel connection state.
- Produces: public identity `PicotooPet AI — Superpower v1.0` while preserving engineering build/version metadata.

- [ ] **Step 1: Add failing contract assertions**

Assert public product identity is present and that REST-healthy/WS-degraded is represented as degraded realtime rather than whole-system offline.

- [ ] **Step 2: Verify RED**

Run the focused contract suite and native Windows build gate.

- [ ] **Step 3: Implement minimal identity/status projection**

Do not alter Mac Core/Worker ownership or formal release gate semantics.

- [ ] **Step 4: Run native fault-injection/self-test**

Verify: REST healthy + WS unavailable, WS reconnect, task progress polling, no fake percent, and no loss of authoritative Core state.

### Task 10: Final packaging and acceptance

**Files:**
- Reuse existing Mac Core/Worker arm64 packaging workflows.
- Reuse existing Windows UI Preview workflow with `-ValidationScope UiPreview`.

- [ ] **Step 1: Run full Python contract/security regression**
- [ ] **Step 2: Run Mac Core native arm64 CI and lifecycle**
- [ ] **Step 3: Run Mac Worker native arm64 CI and lifecycle**
- [ ] **Step 4: Run Windows native .NET 10 build/self-test/lifecycle**
- [ ] **Step 5: Build Windows Preview artifact and verify SHA + archive integrity**
- [ ] **Step 6: Record acceptance evidence on PR #41**

Acceptance is complete only when all applicable native gates are green and the installable Preview artifact has a verified digest. Formal Full Release remains separately gated on the genuine Maotai V2 art asset.
