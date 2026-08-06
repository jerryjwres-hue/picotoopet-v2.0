# Phase 10C Event-Stream Recovery Rollup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver `2.3.13.1` with the complete `2.3.12.5` cold-start recovery fix retained and promoted into formal published-EXE and release-contract verification.

**Architecture:** Keep the existing `EventStreamClient` behavior and add a deterministic published self-test that exercises the bounded event backlog/Pong-expiry boundary in the actual packaged assemblies. Update every canonical product-version contract from `2.3.12.5` to `2.3.13.1` without changing UI, persistence, Provider or execution boundaries.

**Tech Stack:** Python 3.12, pytest, FastAPI TestClient, JSON policy contracts, .NET 10, C# 14, native WPF, GitHub Actions Windows 2025 and macOS 15 arm64.

## Global Constraints

- Product version is exactly `2.3.13.1`.
- Base commit is `a2b4d0c83cbad81dc8b5bf210ef1875bb0c290bd`.
- The `2.3.12.5` `EventStreamClient` recovery code and `EventStreamColdStartSmokeTests` remain present.
- No new UI, Provider, arbitrary input, real worktree, repository mutation, service, browser surface or executable.
- `main` remains unchanged; create a stacked Draft PR based on `feature/phase10b-mock-dev-broker`.
- User machines install only prebuilt packages and never compile project source.
- All new C# comments use aligned formatting consistent with surrounding code.

---

### Task 1: RED — Define the 2.3.13.1 rollup contract

**Files:**
- Create: `tests/contract/test_phase10c_event_stream_recovery_rollup.py`

**Interfaces:**
- Consumes: canonical version file, release goal policy, Windows version tests, `EventStreamClient`, cold-start smoke test and `AppSelfTest` source.
- Produces: a failing source/release contract for the exact 2.3.13.1 rollup.

- [ ] **Step 1: Write the failing contract**

Create assertions requiring:

```python
assert VERSION_FILE.read_text(encoding="utf-8").strip() == "2.3.13.1"
assert goal["windows"]["product_version"]["value"] == "2.3.13.1"
assert "DeferPingWhileEventsPending" in event_stream_source
assert "EventStreamColdStartSmokeTests.RunAsync" in smoke_program
assert "VerifyColdStartEventStreamRecovery();" in app_self_test
assert '["event_stream_cold_start_recovery"] = "pass"' in app_self_test
assert "PHASE10C_EVENT_STREAM_RECOVERY_SELF_TEST=PASS" in app_self_test
```

Also require every active version assertion file to contain `2.3.13.1` and not `2.3.12.5`.

- [ ] **Step 2: Verify RED**

Run:

```bash
PYTHONPATH=.:src python -m pytest -q \
  tests/contract/test_phase10c_event_stream_recovery_rollup.py
```

Expected: FAIL because the repository still reports `2.3.12.5` and `AppSelfTest` lacks the Phase 10C recovery check.

- [ ] **Step 3: Commit RED**

```bash
git add tests/contract/test_phase10c_event_stream_recovery_rollup.py
git commit -m "test: define 2.3.13.1 recovery rollup RED"
```

### Task 2: GREEN — Promote the cold-start fix into published self-test

**Files:**
- Modify: `windows/desktop/src/PicotooPet.Desktop/Services/AppSelfTest.cs`

**Interfaces:**
- Consumes: `EventStreamClient`, `EventEnvelope`, private `_channel`, `_pendingPings` and `ThrowIfPongExpired` behavior already frozen by `EventStreamColdStartSmokeTests`.
- Produces: `VerifyColdStartEventStreamRecovery()` and report marker `event_stream_cold_start_recovery=pass`.

- [ ] **Step 1: Add the self-test call**

Call `VerifyColdStartEventStreamRecovery();` after Mac Core client-options verification and record:

```csharp
checks["event_stream_cold_start_recovery"] = "pass";
```

- [ ] **Step 2: Implement the deterministic published-assembly probe**

Instantiate `EventStreamClient` with a 50 ms Pong timeout and 10 ms Ping interval. Reflect `_channel`, `_pendingPings` and `ThrowIfPongExpired`. Queue one `EventEnvelope`, insert an expired Ping timestamp, invoke the timeout check and fail if a `TimeoutException` occurs. Drain the event, insert another expired Ping and require a `TimeoutException`.

- [ ] **Step 3: Add bounded console markers**

Success:

```text
PHASE10C_EVENT_STREAM_RECOVERY_SELF_TEST=PASS
```

Failure:

```text
PHASE10C_EVENT_STREAM_RECOVERY_SELF_TEST=FAIL | <bounded message>
```

- [ ] **Step 4: Run focused Windows smoke tests**

```powershell
dotnet run --project windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/PicotooPet.Desktop.Core.SmokeTests.csproj -c Release
```

Expected: `PHASE2_CORE_SMOKE=PASS`.

### Task 3: GREEN — Freeze product version 2.3.13.1 end to end

**Files:**
- Modify: `src/picotoopet_core/product-version.txt`
- Modify: `contracts/release/project-goal-invariants.json`
- Modify: `tests/contract/test_product_version_goal_integrity.py`
- Modify: `tests/contract/test_windows_product_version_surfaces.py`
- Modify: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/ProductVersionWpfSmokeTests.cs`
- Modify: `tests/contract/test_phase23_worker_product_version.py`
- Modify: `tests/unit/test_product_version.py`
- Modify: `tests/integration/api/test_product_version_api.py`
- Modify: `tests/contract/test_phase23_mac_delta_source.py`

**Interfaces:**
- Consumes: the canonical four-part product version parser and existing build/package propagation.
- Produces: exact `2.3.13.1` Mac Core health, Windows title/subtitle, Worker verification and release policy.

- [ ] **Step 1: Replace active version assertions**

Change only active release assertions from `2.3.12.5` to `2.3.13.1`; retain historical documentation unchanged.

- [ ] **Step 2: Run focused Python tests**

```bash
PYTHONPATH=.:src python -m pytest -q \
  tests/contract/test_phase10c_event_stream_recovery_rollup.py \
  tests/contract/test_product_version_goal_integrity.py \
  tests/contract/test_windows_product_version_surfaces.py \
  tests/contract/test_phase23_worker_product_version.py \
  tests/contract/test_phase23_mac_delta_source.py \
  tests/unit/test_product_version.py \
  tests/integration/api/test_product_version_api.py
```

Expected: all PASS.

- [ ] **Step 3: Run full contract and unit gates**

```bash
PYTHONPATH=.:src python -m pytest -q tests/contract tests/unit tests/integration/api
```

Expected: no failures caused by version drift or recovery-contract drift.

- [ ] **Step 4: Commit GREEN atomically**

```bash
git add src contracts tests windows/desktop/src windows/desktop/tests
git commit -m "feat: roll cold-start recovery into 2.3.13.1"
```

### Task 4: Native CI, package and Draft PR

**Files:**
- No source changes unless a gate exposes a real regression.

**Interfaces:**
- Consumes: final exact source head.
- Produces: four native gate results, Windows/Mac artifacts, independent verification and a stacked Draft PR.

- [ ] **Step 1: Open a stacked Draft PR**

Base: `feature/phase10b-mock-dev-broker`

Head: `feature/phase10c-event-stream-recovery`

- [ ] **Step 2: Run exactly one CI set**

Require:

- Windows Control Center native WPF gate;
- Windows prebuilt release gate;
- Mac Core arm64 gate;
- Mac Worker impact gate.

Do not create overlapping `synchronize`, `reopened`, rerun or second dispatch events.

- [ ] **Step 3: Verify artifacts independently**

Check path traversal, links, Manifest coverage, sizes, SHA-256, target architecture, product version, Windows EXE allowlist, install/upgrade/activation-failure recovery/rollback and Mac offline install/rollback.

- [ ] **Step 4: Prepare user acceptance**

Require two complete Windows application exits and restarts without opening Settings or re-entering/saving the Token. Both starts must reach online automatically and preserve approvals, tasks, results, approved Handoffs and Broker Session history.
