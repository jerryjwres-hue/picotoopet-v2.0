# Superpower v1.0 Reliability & Progress Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make PicotooPet AI — Superpower v1.0 resilient to long local-model jobs and transient event-stream failures while exposing durable, truthful progress and diagnosable component health.

**Architecture:** Keep Mac Core as the source of truth and preserve Goal → Discovery → Synthesis → Handoff. Add durable progress facts, independent Worker liveness heartbeat, REST snapshot fallback beside WebSocket realtime delivery, and isolate Ollama calls behind a bounded model-runner subprocess with watchdog/circuit-breaker semantics. Public UI identity becomes `PicotooPet AI — Superpower v1.0`; `2.3.27.1+<build>.<sha>` remains engineering metadata only.

**Tech Stack:** Python 3.14, FastAPI, SQLite, Pydantic v2, PydanticAI/Ollama, macOS LaunchAgent, WPF/.NET 10, ClientWebSocket, pytest, native macOS/Windows GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-20-superpower-v1-reliability-progress-design.md`

## Global Constraints

- Windows remains control-only: no crawler, arbitrary shell, or arbitrary task authority.
- Mac Core remains the single source of truth for Goal, Task, Workflow, Result, Progress, Health, and Audit.
- Research Gateway remains read-only; browser/crawler account writes remain forbidden.
- Web ChatGPT upload remains manual.
- Natural Motion V2 remains an independent asset-gated line.
- `gpt-oss:20b` remains the default local model and is never auto-downloaded/replaced.
- Local-model concurrency defaults to 1; all retries are bounded and persisted.
- Public identity: `PicotooPet AI — Superpower v1.0`.
- Engineering build identity: `2.3.27.1+<build>.<sha>`.

---

### Task 1: Durable Worker Liveness Heartbeat

**Files:**
- Modify: `src/picotoopet_core/worker/state.py`
- Modify: `src/picotoopet_core/worker/runtime.py`
- Test: `tests/unit/worker/test_worker_runtime_foundation.py`
- Create/Test: `tests/unit/worker/test_worker_state.py`

**Interfaces:** Produces `WorkerLivenessHeartbeat` and backward-compatible optional `active_stage` / `last_progress_at` status fields.

- [ ] Add a failing test where a handler runs >45s while task lease is healthy; assert Worker status never becomes stale/offline.
- [ ] Run `pytest -q tests/unit/worker/test_worker_runtime_foundation.py -k liveness` and confirm RED.
- [ ] Implement a separate liveness thread that refreshes `worker-status.json` every configured heartbeat interval while the handler runs. Do not couple it to lease renewal.
- [ ] Keep liveness writes atomic through `WorkerStateStore.publish(...)`.
- [ ] Run Worker state/runtime tests and confirm GREEN.
- [ ] Commit: `fix: keep worker liveness fresh during long tasks`.

### Task 2: Canonical Progress Ledger and Snapshot API

**Files:**
- Create: `src/picotoopet_core/db/migration_016.py`
- Modify: `src/picotoopet_core/db/database.py`
- Create: `src/picotoopet_core/progress/{__init__.py,models.py,repository.py,service.py}`
- Modify: `src/picotoopet_core/services.py`
- Modify: `src/picotoopet_core/api/app.py`
- Create: `src/picotoopet_core/api/routes/progress.py`
- Create/Test: `tests/unit/progress/test_repository.py`
- Create/Test: `tests/integration/api/test_progress_api.py`

**Interfaces:** `ProgressEvent`, `ProgressSnapshot`, `ProgressRepository.append(...)`, `ProgressService.snapshot_for_task(task_id)`, `GET /api/v1/tasks/{task_id}/progress`.

- [ ] Add RED tests for monotonic per-task progress sequence and a bounded latest snapshot.
- [ ] Migration creates `task_progress_events(task_id, sequence, stage, completed, total, message, component, details_json, created_at)` with primary key `(task_id, sequence)` and bounded indexes.
- [ ] Implement bounded Pydantic models; reject oversized `details_json` and invalid completed/total combinations.
- [ ] API returns current stage, completed/total, truthful percent only when total exists, latest message, last activity, and at most 50 recent events.
- [ ] Run progress unit/API tests GREEN.
- [ ] Commit: `feat: persist canonical task progress`.

### Task 3: Instrument Discovery → Synthesis → Handoff

**Files:**
- Modify: `src/picotoopet_core/autonomous/discovery.py`
- Modify: `src/picotoopet_core/autonomous/human_pipeline.py`
- Modify: `src/picotoopet_core/worker/handlers.py`
- Modify: `src/picotoopet_core/worker/runtime.py`
- Test: existing autonomous tests plus progress API integration tests.

**Interfaces:** `ProgressReporter.emit(stage, completed, total, message, component, details)` bound to the current task ID by Worker runtime.

- [ ] Add RED tests proving a six-query discovery emits `research-search` progress `0/6 ... 6/6`.
- [ ] Add a narrow reporter protocol; autonomous coordinators do not receive a database handle.
- [ ] Emit objective stages only: `prepare`, `connected-evidence`, `research-search`, `radar-normalize`, `local-scout`, `discovery-complete`, `load-evidence`, `local-analysis`, `synthesis-complete`, `build-handoff`, `handoff-ready`.
- [ ] Never invent progress from elapsed time.
- [ ] Run autonomous/progress tests GREEN.
- [ ] Commit: `feat: report durable goal progress`.

### Task 4: Reliability Diagnostic Black Box

**Files:**
- Create: `src/picotoopet_core/diagnostics/reliability.py`
- Create: `src/picotoopet_core/diagnostics/reliability_bundle.py`
- Modify: `src/picotoopet_core/diagnostics/models.py`
- Modify: `src/picotoopet_core/health/supervisor.py`
- Modify: `src/picotoopet_core/ollama/client.py`
- Modify: existing diagnostics API route.
- Test: `tests/unit/diagnostics/`, `tests/unit/health/`, diagnostics API integration tests.

**Interfaces:** `ReliabilityFaultCode`, `ReliabilitySnapshot`, sanitized reliability ZIP.

- [ ] RED tests classify at least: `WORKER_STATUS_HEARTBEAT_STALE_WHILE_LEASE_ALIVE`, `EVENT_STREAM_TRANSIENT`, `CORE_UNREACHABLE`, `OLLAMA_SERVER_UNREACHABLE`, `MODEL_JOB_TIMEOUT`, `MODEL_OUTPUT_INVALID`, `MEMORY_PRESSURE_HIGH`.
- [ ] Add read-only Ollama `/api/version` and `/api/ps` observation methods; never unload/download models.
- [ ] Bundle component health, worker/lease facts, last 100 progress events, Ollama observations, tail of `~/.ollama/logs/server.log` when readable, memory-pressure summary, current stage/input-size metadata.
- [ ] Explicitly exclude tokens, cookies, credentials, browser storage, and arbitrary file contents.
- [ ] Run diagnostic/health/API tests GREEN.
- [ ] Commit: `feat: add reliability fault diagnostics`.

### Task 5: Isolated Local Model Runner, Watchdog, Circuit Breaker

**Files:**
- Create: `src/picotoopet_core/model_runner/{__init__.py,contracts.py,cli.py,process.py,circuit.py}`
- Modify: `src/picotoopet_core/autonomous/local_intelligence.py`
- Modify: `pyproject.toml`
- Create/Test: `tests/unit/model_runner/test_process.py`, `test_circuit.py`
- Test: local intelligence + Worker runtime tests.

**Interfaces:** `ModelRunnerRequest`, `ModelRunnerResult`, `ModelRunnerProcess.run(...)`, console script `picotoopet-model-runner`.

- [ ] RED test: a hanging model child is terminated at deadline while Worker liveness continues.
- [ ] JSON request stays bounded (`text <= 24_000`, evidence IDs <=64); subprocess uses `shell=False` and temporary bounded input/output.
- [ ] Watchdog polls cancel/deadline, terminates child, escalates after a short grace period, cleans temp files, never kills Ollama server.
- [ ] Circuit states: `closed -> open -> half_open -> closed/open`; consecutive failures and cooldown are bounded/persisted.
- [ ] Production `LocalIntelligenceAdapter` becomes a runner client; deterministic test adapters may remain in-process.
- [ ] Run model-runner/local-intelligence/Worker tests GREEN.
- [ ] Commit: `feat: isolate local model execution`.

### Task 6: Adaptive Input Budget and Checkpoint Resume

**Files:**
- Create: `src/picotoopet_core/model_runner/budget.py`
- Modify: discovery/human pipeline/model runner.
- Test: `tests/unit/model_runner/test_budget.py` and autonomous pipeline tests.

- [ ] RED test: high memory pressure reduces chunk size and concurrency remains 1.
- [ ] RED test: model timeout/resume does not repeat completed Research Gateway searches.
- [ ] Budget inputs: estimated tokens, memory-pressure category, loaded-model count, `/api/ps` metadata when present.
- [ ] Never increase context merely to fit oversized input; dedupe/chunk/summarize first.
- [ ] Completed Workflow steps remain canonical checkpoints; retry only the current local-analysis stage.
- [ ] Run budget/autonomous tests GREEN.
- [ ] Commit: `feat: bound local model load and resume checkpoints`.

### Task 7: Windows Dual-Channel Connectivity

**Files:**
- Modify: `windows/desktop/src/PicotooPet.Desktop.Core/Networking/EventStreamClient.cs`
- Modify: `windows/desktop/src/PicotooPet.Desktop.Core/Networking/ReconnectPolicy.cs`
- Create: `windows/desktop/src/PicotooPet.Desktop.Core/Networking/CoreSnapshotPoller.cs`
- Modify: existing connection-state model and `MainWindowViewModel.cs`
- Test: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/Program.cs`
- Test: `tests/contract/test_phase2_windows_source.py`

- [ ] RED smoke: 3s delayed pong does not mark Core offline; inbound business traffic resets liveness; WS down + REST healthy => Core online/EventStream reconnecting; resume sequence dedupes.
- [ ] Default ping/pong moves from current 1s/2s behavior to conservative realtime liveness (target 5s ping / 15s pong deadline), with any valid inbound message refreshing liveness.
- [ ] Add bounded REST snapshot polling only while realtime stream is degraded; stop it when WS is healthy.
- [ ] Split Mac Core, Worker, Research, Ollama, Realtime Event, Last Sync states; one WebSocket state may not represent whole Mac health.
- [ ] Run Windows smoke/contracts GREEN.
- [ ] Commit: `fix: keep windows control plane alive across event stream jitter`.

### Task 8: Windows Live Progress UI + Superpower v1.0 Identity

**Files:**
- Modify: `windows/desktop/src/PicotooPet.Desktop/MainWindow.xaml`
- Modify: `windows/desktop/src/PicotooPet.Desktop/ViewModels/MainWindowViewModel.cs`
- Modify: existing task-detail XAML/ViewModel files.
- Modify: `src/picotoopet_core/product-version.txt` and release/build projection scripts.
- Test: Windows source/package contracts, native UI interaction smoke.

- [ ] RED identity tests: normal UI says `Superpower v1.0`, normal UI hides `autonomous.discovery.v1`, advanced diagnostics retain engineering build.
- [ ] RED task-detail test: running task with progress shows stage, completed/total, latest message, last activity, recent activity, component health; it must not show only “没有可显示结果”.
- [ ] User stage labels: 准备研究 / 搜集资料 / 整理证据 / 本地分析 / 生成结论 / 生成交接包 / 交接包已就绪.
- [ ] Public title becomes `PicotooPet AI — Superpower v1.0`; `2.3.27.1+<build>.<sha>` moves to Advanced/Diagnostics only.
- [ ] Run WPF build, UI smoke, self-test, source/package contracts GREEN.
- [ ] Commit: `feat: expose superpower v1 progress and identity`.

### Task 9: Fault-Injection Gates and Delivery

**Files:**
- Modify/add relevant `.github/workflows/` entries.
- Modify Mac Core/Worker packaging and verification scripts.
- Create: `scripts/mac/VERIFY_SUPERPOWER_RELIABILITY.command`.
- Modify Windows UI Preview release workflow/scripts.
- Test: release/contract/macOS deployment fixtures.

- [ ] Add deterministic gates for: >60s Worker task, delayed pong, WS hard disconnect + REST fallback, Ollama refused, model hang, invalid output, circuit open/recovery, Windows restart progress restore, Worker restart checkpoint resume, no research repetition, secret-free diagnostic bundle.
- [ ] Real-machine verifier reports `SUPERPOWER_WORKER_LIVENESS`, `SUPERPOWER_RESEARCH_GATEWAY`, `SUPERPOWER_OLLAMA_SERVER`, `SUPERPOWER_OLLAMA_MODEL`, `SUPERPOWER_MODEL_RUNNER`, `SUPERPOWER_PROGRESS_LEDGER`, `SUPERPOWER_RELIABILITY_CLASSIFIER`, `SUPERPOWER_READY` without triggering paid research/Codex/Claude/browser login.
- [ ] Run full native Mac Core + Worker CI: pytest, Ruff, shell syntax, arm64 offline build, install/verify/fault fixtures/rollback, wheel-content verification.
- [ ] Run full native Windows Preview CI: WPF 0 warnings/0 errors, contracts, UI smoke, publish/self-test, install/upgrade/recovery/rollback. Keep `full_release=false` until Natural Motion V2 asset gate passes.
- [ ] Verify CRC, manifest semantics, internal checksums, external SHA-256, commit/run/artifact digest for every delivery artifact.
- [ ] Commit: `test: gate superpower v1 reliability delivery`.

## Plan Self-Review

- Spec coverage: Worker heartbeat, dual-channel connectivity, durable progress, model isolation, watchdog, circuit breaker, adaptive budget, checkpoint resume, diagnostics, public identity, fault injection, install/rollback, and frozen safety boundaries all map to explicit tasks.
- Placeholder scan: no TBD/TODO/“implement later” requirement remains.
- Type consistency: progress/model-runner interfaces are introduced before consumers.
- Scope: all tasks serve one reliability + truthful-progress product contract; no unrelated feature work is included.
