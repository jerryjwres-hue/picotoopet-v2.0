# Phase 2 Performance Vertical Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first durable, low-latency Windows-to-Mac task submission and WebSocket feedback slice without reducing security, audit, recovery, or the frozen feature scope.

**Architecture:** Mac Core writes task state and replayable events atomically to SQLite, dispatches them through a bounded broker, and exposes traceable REST/WebSocket contracts. A .NET 10 Windows core client reuses pooled connections, resumes event streams by sequence, coalesces state updates off the UI thread, and feeds a WPF MVVM shell.

**Tech Stack:** Python 3.12/3.13, FastAPI, SQLite WAL, pytest, .NET 10 LTS, C# 14, WPF, MVVM, HttpClient, ClientWebSocket, System.Threading.Channels.

## Global Constraints

- V1 remains frozen and unmodified.
- Protected original data is never modified.
- Cloud upload still requires human approval.
- No Windows copy of `gpt-oss:20b` and no generic Windows 8B LLM.
- No feature, audit, recovery, or permission capability may be removed to improve performance.
- All code contains aligned Chinese comments.
- Daily operation must not require Terminal, CMD, or PowerShell.
- Every task includes tests, logs, installation, verification, and rollback where applicable.

---

### Task 1: Freeze Phase 2 Contracts and Performance Targets

**Files:**
- Create: `contracts/schemas/event_envelope_v2.schema.json`
- Create: `contracts/schemas/performance_report_v2.schema.json`
- Create: `docs/phase2/PERFORMANCE_SLO_CN.md`
- Test: `tests/contract/test_phase2_contracts.py`

**Interfaces:**
- Produces: `EventEnvelopeV2`, `PerformanceReportV2`, fixed p50/p95/p99 fields and event resume semantics.

- [ ] Write failing schema contract tests.
- [ ] Run the focused tests and confirm missing-file failures.
- [ ] Add exact schemas and SLO document.
- [ ] Run focused and full Python tests.
- [ ] Commit `docs: freeze phase2 event and performance contracts`.

### Task 2: Add Trace and Server Timing Middleware

**Files:**
- Create: `src/picotoopet_core/api/middleware.py`
- Modify: `src/picotoopet_core/api/app.py`
- Test: `tests/integration/api/test_trace_middleware.py`

**Interfaces:**
- Consumes: optional `X-Picotoo-Trace-Id` request header.
- Produces: response headers `X-Picotoo-Trace-Id` and `Server-Timing`.

- [ ] Write failing tests for generated and propagated trace IDs.
- [ ] Run tests and confirm headers are absent.
- [ ] Implement monotonic request timing and redacted logging context.
- [ ] Run focused and full tests.
- [ ] Commit `feat: add traceable api timing middleware`.

### Task 3: Make Task Events and Outbox Atomic

**Files:**
- Modify: `src/picotoopet_core/events/outbox.py`
- Modify: `src/picotoopet_core/queue/repository.py`
- Test: `tests/integration/queue/test_task_outbox_atomicity.py`

**Interfaces:**
- Produces: one durable `task.updated` envelope for each committed task state change.
- Produces: stable SQLite `sequence` derived from Outbox row order.

- [ ] Write failing atomicity and idempotency tests.
- [ ] Run tests and confirm no outbox event exists.
- [ ] Implement transaction-local Outbox append.
- [ ] Run focused and full tests.
- [ ] Commit `feat: persist task events in transactional outbox`.

### Task 4: Add Replayable Bounded Event Delivery

**Files:**
- Modify: `src/picotoopet_core/events/broker.py`
- Create: `src/picotoopet_core/events/dispatcher.py`
- Modify: `src/picotoopet_core/events/outbox.py`
- Modify: `src/picotoopet_core/api/routes/events.py`
- Modify: `src/picotoopet_core/api/app.py`
- Modify: `src/picotoopet_core/services.py`
- Test: `tests/integration/events/test_replayable_stream.py`
- Test: `tests/integration/api/test_websocket_resume.py`

**Interfaces:**
- Consumes: WebSocket query `after_sequence`.
- Produces: ordered `EventEnvelopeV2` JSON and application `ping/pong`.

- [ ] Write failing replay, ordering, bounded-queue and reconnect tests.
- [ ] Run tests and confirm current broker cannot satisfy them.
- [ ] Implement replay queries, background dispatcher and bounded subscriber queues.
- [ ] Run focused and full tests.
- [ ] Commit `feat: add replayable bounded websocket event stream`.

### Task 5: Add Mac Performance Benchmark Endpoint and Runner

**Files:**
- Create: `src/picotoopet_core/performance/percentiles.py`
- Create: `src/picotoopet_core/performance/__init__.py`
- Create: `scripts/benchmark_mac_core.py`
- Create: `tests/unit/performance/test_percentiles.py`
- Create: `tests/integration/performance/test_local_latency.py`

**Interfaces:**
- Produces: count, p50, p95, p99 and maximum in milliseconds.

- [ ] Write failing percentile tests with deterministic samples.
- [ ] Implement nearest-rank percentile calculation.
- [ ] Add local TestClient benchmark runner and JSON report.
- [ ] Run tests and generate a local baseline report.
- [ ] Commit `perf: add phase2 latency measurement harness`.

### Task 6: Create .NET 10 Windows Core Client

**Files:**
- Create: `windows/desktop/global.json`
- Create: `windows/desktop/Directory.Build.props`
- Create: `windows/desktop/PicotooPet.Desktop.slnx`
- Create: `windows/desktop/src/PicotooPet.Desktop.Core/PicotooPet.Desktop.Core.csproj`
- Create: `windows/desktop/src/PicotooPet.Desktop.Core/Contracts/*.cs`
- Create: `windows/desktop/src/PicotooPet.Desktop.Core/Networking/*.cs`
- Create: `windows/desktop/src/PicotooPet.Desktop.Core/State/*.cs`
- Create: `windows/desktop/src/PicotooPet.Desktop.Core/Security/*.cs`
- Create: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/*`

**Interfaces:**
- Produces: `MacCoreClient`, `EventStreamClient`, `AppStateStore`, `LatencyRecorder`, `CredentialManagerTokenStore`.

- [ ] Write a no-third-party-package smoke-test console first.
- [ ] Add immutable contracts matching JSON schemas.
- [ ] Implement pooled REST client with idempotency and trace headers.
- [ ] Implement resumable WebSocket client with bounded Channel and jittered reconnect.
- [ ] Implement state reducer, percentile recorder and Credential Manager storage.
- [ ] Add Windows build and test script that returns nonzero on failure.
- [ ] Commit `feat: add high performance windows core client`.

### Task 7: Build the WPF MVVM Vertical Slice

**Files:**
- Create: `windows/desktop/src/PicotooPet.Desktop/PicotooPet.Desktop.csproj`
- Create: `windows/desktop/src/PicotooPet.Desktop/App.xaml*`
- Create: `windows/desktop/src/PicotooPet.Desktop/MainWindow.xaml*`
- Create: `windows/desktop/src/PicotooPet.Desktop/ViewModels/*.cs`
- Create: `windows/desktop/src/PicotooPet.Desktop/Views/*.xaml`
- Create: `windows/desktop/src/PicotooPet.Desktop/Services/*.cs`

**Interfaces:**
- Consumes: `MacCoreClient`, `EventStreamClient`, `AppStateStore`.
- Produces: dashboard, quick task submit, live task list, connection and latency status.

- [ ] Create ViewModel tests in the smoke-test console.
- [ ] Implement command feedback before awaiting network I/O.
- [ ] Enable ListView virtualization and recycling.
- [ ] Keep network work off the Dispatcher thread.
- [ ] Add clear offline, authentication and reconnect states.
- [ ] Commit `feat: add phase2 wpf task feedback slice`.

### Task 8: Add Installation, Verification, Diagnostics and Rollback

**Files:**
- Create: `windows/desktop/scripts/BUILD_PHASE2_WINDOWS.cmd`
- Create: `windows/desktop/scripts/VERIFY_PHASE2_WINDOWS.vbs`
- Create: `windows/desktop/scripts/INSTALL_PHASE2_WINDOWS.vbs`
- Create: `windows/desktop/scripts/ROLLBACK_PHASE2_WINDOWS.vbs`
- Create: `windows/desktop/scripts/*.ps1`
- Create: `docs/phase2/INSTALLATION_GUIDE_CN.md`
- Create: `docs/phase2/REAL_MACHINE_ACCEPTANCE_CN.md`
- Test: `tests/contract/test_phase2_windows_package.py`

**Interfaces:**
- Produces: no-terminal double-click install/verify/rollback entry points and machine-readable reports.

- [ ] Write failing package and encoding tests.
- [ ] Implement UTF-8 BOM PowerShell scripts and hidden VBS launchers.
- [ ] Add build, health, credential, WebSocket and latency verification.
- [ ] Add atomic version switch and rollback metadata.
- [ ] Run package tests and release scan.
- [ ] Commit `release: package phase2 performance vertical slice`.

### Task 9: Final Verification and Handoff

**Files:**
- Create: `docs/phase2/PHASE2_VERTICAL_SLICE_STATUS.md`
- Create: `docs/phase2/PHASE2_LOCAL_VERIFICATION_REPORT.json`
- Modify: `scripts/verify_release.py`

**Interfaces:**
- Produces: source verification evidence and explicit Windows real-machine gaps.

- [ ] Run all Python tests with `PYTHONPATH=src`.
- [ ] Run Ruff on Python sources and tests.
- [ ] Run contract/static checks for Windows source.
- [ ] Generate source ZIP and SHA-256.
- [ ] Record what was and was not compiled in this environment.
- [ ] Commit `release: phase2 vertical slice source handoff`.
