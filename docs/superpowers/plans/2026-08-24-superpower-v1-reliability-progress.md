# Superpower v1 Reliability + Progress Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Superpower v1 resilient to long local-model work, prevent false disconnects, expose durable task progress, generate sanitized reliability diagnostics, and keep the public identity separate from engineering build numbers.

**Architecture:** Mac Core remains the source of truth for task/progress/health facts. Mac Worker owns independent lease and liveness heartbeats; Windows treats WebSocket as a realtime accelerator while REST/Core health remains authoritative. Local-model work is bounded and isolated so Ollama or one model job cannot take down Worker/Core.

**Tech Stack:** Python 3.12, FastAPI, SQLite, Pydantic, macOS launchd, Ollama OpenAI-compatible endpoint, .NET 10 WPF, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-20-superpower-v1-reliability-progress-design.md`

## Global Constraints

- Public product name is `PicotooPet AI`; public release label is `Superpower v1.0`.
- Engineering `2.3.x` versions remain diagnostics/build metadata and do not replace the public release identity.
- Mac Core is the unique source of truth for Goals, Tasks/Workflows, Evidence, Results, Audit, and durable progress.
- Windows is a control plane and must not directly execute crawlers, shell commands, Ollama, Codex, or Claude Code.
- Mac Worker executes only fixed registered capabilities; no task-supplied arbitrary shell execution.
- WebSocket degradation must not be displayed as Mac Core offline while REST health remains reachable.
- Long-running handlers must refresh Worker liveness independently of task lease renewal.
- Progress must be measured from durable units/stages; do not synthesize fake percentages from elapsed time.
- Reliability bundles must be bounded and sanitized; never include cookies, passwords, tokens, browser storage, API keys, full prompts, or full research bodies.
- Natural Motion V2 formal-release asset gate remains intact and must not be bypassed.

---

### Task 1: Worker liveness independent from task lease

**Files:**
- Modify: `src/picotoopet_core/worker/runtime.py`
- Modify: `src/picotoopet_core/worker/state.py`
- Test: `tests/unit/worker/test_worker_runtime.py`
- Test: `tests/unit/worker/test_worker_state.py`

**Interfaces:**
- Consumes: existing `LeaseHeartbeat`, `WorkerStateStore.publish(...)`, handler execution lifecycle.
- Produces: an execution-scoped liveness heartbeat that refreshes worker status while a handler is still running.

- [ ] **Step 1: Write the failing long-handler liveness test**

```python
def test_executing_worker_stays_fresh_while_handler_runs(tmp_path):
    # Use a short stale threshold and a blocking fixture handler.
    # Assert Worker status stays available after the threshold while the lease remains alive.
    ...
```

- [ ] **Step 2: Run the focused worker tests and verify the stale-status regression fails**

Run: `python -m pytest -q tests/unit/worker/test_worker_runtime.py tests/unit/worker/test_worker_state.py`
Expected: the long handler becomes `worker_heartbeat_stale` before the fix.

- [ ] **Step 3: Implement a bounded execution liveness heartbeat**

```python
class WorkerLivenessHeartbeat:
    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self._stop.set()
        self._thread.join(timeout=self._join_timeout)
```

The heartbeat only republishes the already-known executing state and current task id; it must not mutate task outcome or lease ownership.

- [ ] **Step 4: Run focused worker tests and full worker contract tests**

Run: `python -m pytest -q tests/unit/worker tests/contract/test_worker*.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/picotoopet_core/worker tests/unit/worker
git commit -m "fix: keep worker liveness fresh during long handlers"
```

### Task 2: WebSocket false-disconnect elimination

**Files:**
- Modify: `windows/desktop/src/PicotooPet.Desktop.Core/Networking/EventStreamClient.cs`
- Test: `tests/contract/test_phase2_windows_source.py`
- Test: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/EventStreamColdStartSmokeTests.cs`

**Interfaces:**
- Consumes: event stream `ping`, `pong`, `EventEnvelope`, reconnect policy.
- Produces: `RecordInboundActivity()` and tolerant defaults: 10-second app ping, 30-second pong deadline, 30-second transport keepalive.

- [ ] **Step 1: Require valid inbound activity to suppress stale Ping samples**

```csharp
pending["delayed-pong-with-business-traffic"] = 0;
recordInbound.Invoke(client, parameters: null);
InvokeWithoutTimeout(timeoutCheck, client, "业务入站后不得误判 Pong 超时");
SmokeAssert.True(pending.IsEmpty, "业务入站后旧 Ping 样本必须清空");
```

- [ ] **Step 2: Verify RED in Windows contract CI**

Run: `python -m pytest -q tests/contract/test_phase2_windows_source.py`
Expected: FAIL because `RecordInboundActivity` / tolerant defaults are absent.

- [ ] **Step 3: Implement tolerant liveness**

```csharp
_pongTimeout  = pongTimeout  ?? TimeSpan.FromSeconds(30);
_pingInterval = pingInterval ?? TimeSpan.FromSeconds(10);

private void RecordInboundActivity() => _pendingPings.Clear();
```

Call it for every valid inbound application JSON message and use `KeepAliveInterval = TimeSpan.FromSeconds(30)`.

- [ ] **Step 4: Run contract + native smoke + WPF build**

Run: `python -m pytest -q tests/contract tests/security`
Run: `dotnet run --project windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/PicotooPet.Desktop.Core.SmokeTests.csproj --configuration Release -- --ui-interaction-only`
Run: `dotnet build windows/desktop/PicotooPet.Desktop.sln --configuration Release -warnaserror`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/contract/test_phase2_windows_source.py windows/desktop
git commit -m "fix: tolerate valid websocket inbound activity"
```

### Task 3: Separate realtime Event Stream health from Mac Core reachability

**Files:**
- Modify: `windows/desktop/src/PicotooPet.Desktop/ViewModels/MainWindowViewModel.cs`
- Modify: `windows/desktop/src/PicotooPet.Desktop/Services/ControlCenterSession.cs`
- Test: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/DualChannelSyncSmokeTests.cs`

**Interfaces:**
- Consumes: REST `/api/v1/health`, WebSocket `ConnectionState`.
- Produces: Core status derived from REST reachability; Event Stream status remains an independent degraded/reconnecting signal.

- [ ] **Step 1: Add a failing dual-channel state test**

```csharp
// REST health succeeds while Event Stream is reconnecting.
// Expected UI: Mac Core online; realtime updates reconnecting/degraded.
```

- [ ] **Step 2: Run native smoke and verify the current conflated status fails**

Run: `dotnet run --project windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/PicotooPet.Desktop.Core.SmokeTests.csproj --configuration Release -- --ui-interaction-only`
Expected: FAIL on the dual-channel assertion.

- [ ] **Step 3: Make REST authoritative for Core reachability**

Keep WebSocket state as an independent property. A WebSocket reconnect must not set the Core badge to offline when the most recent bounded REST probe succeeds.

- [ ] **Step 4: Run native smoke and build**

Run the two commands from Task 2 Step 4.
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add windows/desktop
git commit -m "fix: separate event stream from core health"
```

### Task 4: Durable task progress and Windows task-detail projection

**Files:**
- Create/modify: `src/picotoopet_core/automation/progress.py`
- Modify: `src/picotoopet_core/api/routes/tasks.py`
- Modify: fixed autonomous discovery/synthesis handlers to publish exact units.
- Create/modify: `windows/desktop/src/PicotooPet.Desktop.Core/Contracts/TaskProgressContracts.cs`
- Modify: `windows/desktop/src/PicotooPet.Desktop/Services/ControlCenterSession.TaskProgress.cs`
- Modify: `windows/desktop/src/PicotooPet.Desktop/ViewModels/TaskDetailViewModel.cs`
- Modify: `windows/desktop/src/PicotooPet.Desktop/Views/Pages/TaskDetailWindow.xaml`
- Test: progress repository/API tests and WPF smoke.

**Interfaces:**
- Produces: `TaskProgressSnapshot` and bounded `TaskProgressEvent` history with task_id, goal_id, workflow_id, stage_key, stage_label, state, completed_units, total_units, unit_label, last_activity_at, message, attempt, checkpoint_version, component.

- [ ] **Step 1: Write failing persistence/API tests for exact-unit progress**
- [ ] **Step 2: Verify RED for missing snapshot/history behavior**
- [ ] **Step 3: Persist latest progress plus bounded history inside the existing Core database**
- [ ] **Step 4: Add fixed `/api/v1/tasks/{task_id}/progress` read projection and event publication**
- [ ] **Step 5: Emit exact query/chunk/evidence units from discovery and synthesis**
- [ ] **Step 6: Project stage/value/recent activity in Task Detail without elapsed-time percentage guesses**
- [ ] **Step 7: Run Python API tests, Windows contracts, native smoke, and build**
- [ ] **Step 8: Commit with `feat: expose durable autonomous task progress`**

### Task 5: Reliability Black Box and sanitized bundle

**Files:**
- Create/modify: `src/picotoopet_core/diagnostics/reliability.py`
- Create/modify: `src/picotoopet_core/diagnostics/reliability_service.py`
- Create/modify: `src/picotoopet_core/diagnostics/reliability_bundle.py`
- Modify: `src/picotoopet_core/api/routes/status.py`
- Test: reliability classification, bundle allowlist, redaction, and API tests.

**Interfaces:**
- Produces: stable fault codes and `/api/v1/status/reliability`; fixed POST bundle endpoint returns a sanitized ZIP.

- [ ] **Step 1: Write failing classification tests for Core/WS/Worker/Ollama/model timeout separation**
- [ ] **Step 2: Verify RED**
- [ ] **Step 3: Implement deterministic classification with explicit fault priority**
- [ ] **Step 4: Write failing ZIP allowlist/redaction test**
- [ ] **Step 5: Implement fixed bundle entries and bounded log tails; never scan browser credential/storage locations**
- [ ] **Step 6: Run diagnostics, security, and API test suites**
- [ ] **Step 7: Commit with `feat: add superpower reliability black box`**

### Task 6: Local-model containment and recovery policy

**Files:**
- Create/modify: `src/picotoopet_core/autonomous/model_job_runner.py`
- Modify: `src/picotoopet_core/autonomous/local_intelligence.py`
- Modify: `src/picotoopet_core/ollama/client.py`
- Test: subprocess timeout, invalid output, Ollama refused/HTTP error, cancellation, and checkpoint recovery tests.

**Interfaces:**
- Produces fixed states: `queued`, `starting`, `ollama_probe`, `running`, `validating`, `completed`, `retry_wait`, `circuit_open`, `failed`, `cancelled`.

- [ ] **Step 1: Write failing stuck-runner timeout test**
- [ ] **Step 2: Verify RED while proving Worker/Core process remains alive in the fixture**
- [ ] **Step 3: Implement a fixed short-lived runner subprocess with parent watchdog and bounded input/output schema**
- [ ] **Step 4: Add one bounded shrink-and-retry path, repeated-timeout circuit opening, and lightweight recovery probe**
- [ ] **Step 5: Preserve completed research/checkpoints; never restart the full goal after model-only failure**
- [ ] **Step 6: Run model runner, autonomous, worker, diagnostics, and security tests**
- [ ] **Step 7: Commit with `fix: contain local model failures and resume checkpoints`**

### Task 7: Public Superpower v1.0 identity

**Files:**
- Modify: `windows/desktop/src/PicotooPet.Desktop/Versioning/ProductVersionInfo.cs`
- Modify: `windows/desktop/src/PicotooPet.Desktop/Views/ShellWindow.xaml.cs`
- Test: `tests/contract/test_picotoopet_ai_product_identity.py`

**Interfaces:**
- Produces: `ProductName = "PicotooPet AI"`, `SuperpowerLabel = "Superpower v1.0"`, window title and Control Center subtitle; engineering version remains diagnostic metadata.

- [ ] **Step 1: Write identity contract test and verify RED**
- [ ] **Step 2: Implement additive identity normalization without replacing the existing Maotai host/layout**
- [ ] **Step 3: Run contracts and WPF build/smoke**
- [ ] **Step 4: Commit with `feat: brand control center as superpower v1`**

### Task 8: Native CI, installable packages, and final evidence

**Files:**
- Modify only package/workflow files if a CI defect is proven by logs.
- Use existing Mac Core, Mac Worker, Windows UI Preview package workflows.

**Interfaces:**
- Produces: installable Mac Core/Worker arm64 packages and a Windows UI Preview package tied to one source commit.

- [ ] **Step 1: Run Mac Core native arm64 CI and require focused + full Python regressions, shell syntax, offline install fixture, rollback fixture, and package hashes**
- [ ] **Step 2: Run Mac Worker native arm64 CI and require liveness regression coverage plus install/verify evidence**
- [ ] **Step 3: Run Windows Control Center CI and require contracts/security, pinned .NET SDK, WPF smoke, warnings-as-errors build, and published self-test**
- [ ] **Step 4: Run Windows UI Preview release lifecycle (install, upgrade, recovery, rollback) and upload artifact with SHA-256**
- [ ] **Step 5: Do not convert the preview into a formal Full Release while `torso_neutral.png` Natural Motion V2 gate is unmet**
- [ ] **Step 6: Download artifacts, verify outer/inner SHA-256 where provided, and hand off only packages whose native workflow concluded success**
