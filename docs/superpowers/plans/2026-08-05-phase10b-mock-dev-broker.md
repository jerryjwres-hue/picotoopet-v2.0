# Phase 10B-B Mock Dev Broker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver product version `2.3.12.1` with an on-demand Windows Mock Dev Broker child process, fixed LocalAppData sandbox, Windows Job Object timeout/cancellation, strict session-bound Return ingestion in Mac Core, and native WPF observation.

**Architecture:** Mac Core remains the only fact source and adds durable Broker Session records plus strict Mock Return ingestion. The existing `Picotoo Pet AI.exe` launches itself in a hidden fixed child mode, never through a shell, and the parent contains the process tree with a Windows Job Object. The child creates only a deterministic fixture change in an application-owned sandbox and returns a bounded JSON envelope that Mac Core independently validates.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLite, pytest, JSON Schema, .NET 10, C# 14, native WPF, Windows Job Objects, GitHub Actions native Windows and macOS arm64 runners.

## Global Constraints

- Product version is exactly `2.3.12.1` after all functional gates are green.
- Handoff / Return Contract remains `1.0.0`.
- Formal Windows UI remains the existing native WPF `Picotoo Pet AI.exe`.
- No second user-facing program, Windows service, administrator privilege, browser UI, WebView, Electron, localhost UI, CLI or script UI.
- No Codex, Grok Build or other external Provider installation, login, authentication or invocation.
- No arbitrary command, path, file picker, upload, environment variable, credential or Provider parameter input.
- No user repository, Protected original, Raw Evidence, project scan, code build, project test, Git worktree, push, PR, merge, tag or release.
- Mac Core + SQLite is the only fact source.
- Windows may execute only the fixed internal Mock Broker child mode and may not invent terminal state.
- PR remains Draft, open and unmerged; `main` remains unchanged.
- User machines receive prebuilt packages and do not compile source or install development SDKs.
- All new code comments must use aligned formatting consistent with surrounding files.

---

### Task 1: RED — Broker Session migration, models and policy contracts

**Files:**
- Create: `tests/unit/db/test_broker_session_migration.py`
- Create: `tests/unit/broker/test_broker_session_service.py`
- Create: `tests/contract/test_phase10b_mock_broker_contract.py`
- Create: `tests/security/test_mock_broker_security.py`
- Create: `contracts/handoff/v1/schemas/broker_session_preview.schema.json`
- Modify: `tests/contract/test_schema_registry.py`

**Interfaces:**
- Produces failing specifications for `BrokerSessionStatus`, `BrokerSessionRecord`, `BrokerSessionCreateResult`, `MockBrokerReturnEnvelope`, migration 5 and `BrokerSessionService`.
- Existing Phase 10B-A Return types and routes remain unchanged during RED.

- [ ] **Step 1: Write migration RED**

Add tests that apply migrations 1–4, insert Handoff and Return rows, run migration 5 twice, and assert a new `broker_sessions` table preserves all old rows. Expected columns must include `session_id`, `handoff_id`, `status`, `provider`, `timeout_seconds`, digests, `return_id`, `event_count`, `sandbox_digest`, `failure_code`, `idempotency_key`, timestamps and indexes.

- [ ] **Step 2: Write domain RED**

Add tests requiring:

```python
result = service.reserve_mock_session(
    approved_handoff.handoff_id,
    idempotency_key="broker-create-001",
)
assert result.record.status == BrokerSessionStatus.RESERVED
assert result.record.provider == "local-mock-dev-broker"
assert result.record.timeout_seconds == 30
assert result.capability
```

Cover rejected/expired/prepared Handoffs, same-key replay, cross-Handoff key conflict, capability determinism and absence of capability from `model_dump()` of the public record.

- [ ] **Step 3: Write Return policy RED**

Create strict valid and invalid Mock Return fixtures. Require exactly one changed file `docs/mock-provider-proof.txt`, four ordered events, `not_run` test/build claims, exact SHA coverage, fixed Provider and matching session/Handoff/request/package digests.

- [ ] **Step 4: Write security RED**

Require rejection or quarantine for extra fields, extra files, traversal, drive/UNC paths, reparse/link entry flags, binary content, oversize body, wrong capability, wrong Session/Handoff binding, command fields, environment fields, Authorization, Token, password, private key, Protected original and Raw Evidence patterns.

- [ ] **Step 5: Run RED**

Run:

```bash
PYTHONPATH=.:src python -m pytest -q \
  tests/unit/db/test_broker_session_migration.py \
  tests/unit/broker/test_broker_session_service.py \
  tests/contract/test_phase10b_mock_broker_contract.py \
  tests/security/test_mock_broker_security.py
```

Expected: collection or assertion failures caused only by missing migration 5 and Broker Session implementation. Existing focused Handoff/Return tests must still pass.

- [ ] **Step 6: Commit RED**

```bash
git add tests contracts/handoff/v1/schemas/broker_session_preview.schema.json
git commit -m "test: define Phase 10B-B broker session RED"
```

### Task 2: GREEN — Mac Core Broker Session domain and migration 5

**Files:**
- Create: `src/picotoopet_core/broker/__init__.py`
- Create: `src/picotoopet_core/broker/models.py`
- Create: `src/picotoopet_core/broker/service.py`
- Modify: `src/picotoopet_core/db/schema.py`
- Modify: `src/picotoopet_core/db/database.py`
- Modify: `src/picotoopet_core/services.py`

**Interfaces:**
- Produces `BrokerSessionService.reserve_mock_session()`, `list_sessions()`, `get_session()`, `cancel_session()` and `ingest_mock_return()`.
- Consumes existing `HandoffService`, `ReturnValidationService`, `AppSettings.api_token` and `Database`.

- [ ] **Step 1: Add migration 5**

Add `MIGRATION_005` and register it after migration 4. Use foreign keys to `handoffs` and optional `returns`, unique `idempotency_key`, status/created indexes and no raw capability or content columns.

- [ ] **Step 2: Add strict models**

Define:

```python
class BrokerSessionStatus(StrEnum):
    RESERVED    = "reserved"
    RUNNING     = "running"
    RETURNING   = "returning"
    COMPLETED   = "completed"
    CANCELLED   = "cancelled"
    TIMED_OUT   = "timed_out"
    FAILED      = "failed"
    QUARANTINED = "quarantined"
```

Use `ConfigDict(extra="forbid")` for all request models. File names must be an enum, not a free path string. Limit each UTF-8 content field to 32 KiB and the file list to the exact fixed set.

- [ ] **Step 3: Implement deterministic capability**

Implement:

```python
def _session_capability(self, session_id: str, handoff_id: str) -> str:
    message = f"broker-session-v1:{session_id}:{handoff_id}".encode("utf-8")
    return hmac.new(self.api_token.encode("utf-8"), message, hashlib.sha256).hexdigest()
```

Use constant-time comparison on Return ingestion. Never persist or log the returned capability.

- [ ] **Step 4: Implement reservation and state transitions**

Only approved Handoffs may reserve. Fixed Provider is `local-mock-dev-broker`; timeout is 30. Same key and Handoff replay the same record and capability. Cross-resource reuse raises a fixed conflict.

- [ ] **Step 5: Implement bounded persistence**

Persist only safe fields and fixed error codes. Serialize event summaries and public preview with canonical JSON. State transitions must be compare-and-set and reject terminal-state mutation.

- [ ] **Step 6: Wire services**

Add `broker_sessions: BrokerSessionService` to `Services` and construct it with `settings.api_token`, `database`, `handoffs` and `returns`.

- [ ] **Step 7: Run focused GREEN**

Run the Task 1 test set plus existing Handoff and Return unit tests. Expected: pass.

- [ ] **Step 8: Commit**

```bash
git add src/picotoopet_core/broker src/picotoopet_core/db src/picotoopet_core/services.py tests contracts
git commit -m "feat: add durable mock broker sessions"
```

### Task 3: GREEN — Generalize Return validator without weakening Phase 10B-A

**Files:**
- Modify: `src/picotoopet_core/returns/models.py`
- Modify: `src/picotoopet_core/returns/service.py`
- Modify: `tests/unit/returns/test_return_validation_service.py`
- Modify: `tests/security/test_return_validation_security.py`

**Interfaces:**
- Produces `ReturnValidationService.validate_mock_broker_entries(...)` for `BrokerSessionService`.
- Preserves `run_self_test()` and its zero-change Provider-specific policy.

- [ ] **Step 1: Add provider-specific policy object**

Create an internal frozen policy with Provider, required files, allowed event types, exact changed-file rule, max sizes and execution notice. Define two immutable policies: `local-contract-self-test` and `local-mock-dev-broker`.

- [ ] **Step 2: Preserve self-test invariants**

Keep self-test at changed file count 0, three events and no `changes/` entry. Add mutation tests proving the self-test cannot use the mock policy.

- [ ] **Step 3: Add mock broker validation**

Validate exact fixed files, one changed path, four events, text-only content, manifest coverage, session binding and secret scan. Persist through the existing `returns` table with `contract_validated` or `quarantined`.

- [ ] **Step 4: Expand only safe projection bounds**

Allow exactly two Provider values and changed count `0..1`. Keep all paths and file contents out of `ReturnRecord`. Use an execution notice that distinguishes self-test from Mock Broker.

- [ ] **Step 5: Run regression**

Run all Return, Handoff, contract and security tests. Expected: Phase 10B-A tests remain unchanged and green; new mock policy tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/picotoopet_core/returns tests/unit/returns tests/security
git commit -m "feat: validate fixed mock broker returns"
```

### Task 4: RED/GREEN — Broker REST API and body limit

**Files:**
- Create: `src/picotoopet_core/api/routes/broker_sessions.py`
- Create: `tests/integration/api/test_broker_session_api.py`
- Modify: `src/picotoopet_core/api/app.py`
- Modify: `src/picotoopet_core/api/errors.py`
- Modify: `src/picotoopet_core/api/middleware.py`
- Modify: `tests/contract/test_openapi_contract.py`

**Interfaces:**
- Produces authenticated list/get/reserve/cancel/return endpoints.
- Return endpoint consumes `MockBrokerReturnEnvelope` and `X-Picotoo-Broker-Session`.

- [ ] **Step 1: Write API RED**

Assert route absence first. Tests must cover authentication, `Idempotency-Key`, content type, 128 KiB request limit, capability header, bodyless reserve/cancel, bounded public projections and no capability in list/get responses.

- [ ] **Step 2: Implement request-size middleware**

Add a route-specific ASGI body limiter that rejects oversized Broker Return requests before JSON parsing with fixed `BROKER_OUTPUT_TOO_LARGE`. It must not read or log the rejected body.

- [ ] **Step 3: Implement routes**

Map domain conflicts/policy errors to fixed API codes. Do not echo request data. Require `Content-Type: application/json` for Return and reject multipart.

- [ ] **Step 4: Verify OpenAPI**

Require the five new paths, forbidden extras on request schemas, no binary/multipart fields and no arbitrary path/command/provider configuration properties.

- [ ] **Step 5: Run Python gates**

Run focused API tests, then:

```bash
PYTHONPATH=.:src python -m pytest -q tests/contract tests/security
PYTHONPATH=.:src python -m pytest -q
python -m ruff check src tests
```

Expected: all pass, with only existing platform-specific skips.

- [ ] **Step 6: Commit**

```bash
git add src/picotoopet_core/api tests/integration/api tests/contract
git commit -m "feat: expose bounded mock broker API"
```

### Task 5: RED — Windows Broker domain, process policy and typed client

**Files:**
- Create: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/DevBrokerPolicySmokeTests.cs`
- Create: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/DevBrokerProcessSmokeTests.cs`
- Create: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/MacCoreBrokerClientSmokeTests.cs`
- Modify: smoke test registration entry point.

**Interfaces:**
- Requires types `BrokerSessionRecord`, `BrokerSessionCreateResult`, `MockBrokerReturnEnvelope`, `BrokerCommandPolicy`, `BrokerSandboxPaths`, `DevBrokerProcessRunner` and `MacCoreBrokerClient`.

- [ ] **Step 1: Write command-policy RED**

Require that only an internal enum action is accepted. Tests must prove no API accepts command strings and that names such as `cmd.exe`, `powershell.exe`, `bash`, `wsl`, `git`, `curl` and arbitrary executables are denied.

- [ ] **Step 2: Write sandbox RED**

Require UUID-only session IDs, LocalAppData fixed root, no caller path, traversal/UNC/drive rejection, reparse-point rejection and deterministic cleanup.

- [ ] **Step 3: Write process RED**

Require fixed self-child arguments, `UseShellExecute=false`, no shell executable, bounded stdout/stderr, 30-second timeout, cancellation and no surviving child process.

- [ ] **Step 4: Write client RED**

Require bodyless reserve/cancel, strict JSON Return upload, capability header, bounded reads and one retry with the same idempotency key.

- [ ] **Step 5: Run native RED**

Run the smoke project on Windows. Expected: compile failures only for missing Phase 10B-B types.

- [ ] **Step 6: Commit RED**

```powershell
git add windows/desktop/tests
git commit -m "test: define Windows Mock Dev Broker RED"
```

### Task 6: GREEN — Windows fixed sandbox and headless Mock child

**Files:**
- Create: `windows/desktop/src/PicotooPet.Desktop.Core/Contracts/BrokerContracts.cs`
- Create: `windows/desktop/src/PicotooPet.Desktop.Core/DevBroker/BrokerCommandPolicy.cs`
- Create: `windows/desktop/src/PicotooPet.Desktop.Core/DevBroker/BrokerSandboxPaths.cs`
- Create: `windows/desktop/src/PicotooPet.Desktop.Core/DevBroker/BrokerSandboxBuilder.cs`
- Create: `windows/desktop/src/PicotooPet.Desktop.Core/DevBroker/MockProviderChild.cs`
- Create: `windows/desktop/src/PicotooPet.Desktop.Core/DevBroker/WindowsJobObject.cs`
- Create: `windows/desktop/src/PicotooPet.Desktop.Core/DevBroker/DevBrokerProcessRunner.cs`
- Modify: `windows/desktop/src/PicotooPet.Desktop/App.xaml.cs`
- Modify: `windows/desktop/src/PicotooPet.Desktop/PicotooPet.Desktop.csproj`

**Interfaces:**
- `MockProviderChild.TryRun(string[] args, TextWriter stdout, TextWriter stderr)` returns true when child mode handled the process.
- `DevBrokerProcessRunner.RunAsync(BrokerSessionCreateResult session, CancellationToken)` returns a parsed `MockBrokerReturnEnvelope`.

- [ ] **Step 1: Implement fixed contracts**

Use `required` init-only properties, JSON source-generation context where the project pattern supports it, maximum lengths and immutable collections. No raw path or command properties are public.

- [ ] **Step 2: Implement safe path derivation**

Derive the root from `Environment.SpecialFolder.LocalApplicationData`. Validate UUID with `Guid.TryParseExact(..., "D", ...)`. Use `Path.GetFullPath` and ordinal-insensitive containment check. Reject existing reparse points before traversal.

- [ ] **Step 3: Implement deterministic fixture**

Generate fixed UTF-8 fixture files, copy to workspace, create only `docs/mock-provider-proof.txt`, compute SHA-256 and assemble the fixed Return envelope. Keep every code comment aligned with surrounding style.

- [ ] **Step 4: Implement Job Object containment**

P/Invoke `CreateJobObject`, `SetInformationJobObject`, `AssignProcessToJobObject` and `CloseHandle`. Set `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`. Treat assignment or cleanup failure as a fixed terminal error.

- [ ] **Step 5: Implement bounded process runner**

Resolve `Environment.ProcessPath`, launch the same EXE with fixed arguments, read streams with explicit character/byte caps, enforce 30 seconds and cancellation, close the Job Object on all paths, parse strict JSON and delete the session sandbox.

- [ ] **Step 6: Add child-mode startup gate**

At the earliest application entry point, execute child mode before WPF application initialization. Child mode must not create a Dispatcher window or load normal Session services.

- [ ] **Step 7: Run native focused tests**

Run command, sandbox and process smoke tests, including a test-only fixed hang mode and spawned-child cleanup witness. Expected: pass with zero warnings.

- [ ] **Step 8: Commit**

```powershell
git add windows/desktop/src windows/desktop/tests
git commit -m "feat: add contained Windows Mock Dev Broker"
```

### Task 7: GREEN — Windows typed client, Session and WPF status surface

**Files:**
- Create: `windows/desktop/src/PicotooPet.Desktop.Core/Networking/MacCoreBrokerClient.cs`
- Create: `windows/desktop/src/PicotooPet.Desktop/Services/IBrokerSessionGateway.cs`
- Create: `windows/desktop/src/PicotooPet.Desktop/Services/ControlCenterSession.Broker.cs`
- Create: `windows/desktop/src/PicotooPet.Desktop/ViewModels/BrokerSessionState.cs`
- Modify: `windows/desktop/src/PicotooPet.Desktop/Services/ControlCenterSession.cs`
- Modify: `windows/desktop/src/PicotooPet.Desktop/ViewModels/CloudDevelopmentPageViewModel.cs`
- Modify: `windows/desktop/src/PicotooPet.Desktop/Views/Pages/CloudDevelopmentPage.xaml`
- Modify: `windows/desktop/src/PicotooPet.Desktop/Views/Pages/CloudDevelopmentPage.xaml.cs`
- Modify: `windows/desktop/src/PicotooPet.Desktop/Services/AppSelfTest.cs`
- Create: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/CloudDevelopmentPhase10BBLayoutSmokeTests.cs`

**Interfaces:**
- WPF consumes only `IBrokerSessionGateway`; process runner remains behind the Session.
- Selected Handoff, Broker Session and Return previews are independent logical identities.

- [ ] **Step 1: Implement typed client**

Use existing Bearer, trace, timeout and bounded-read patterns. Generate each idempotency key once and reuse it for one bounded retry. Keep capability only in memory until Return submission completes.

- [ ] **Step 2: Implement Session orchestration**

Sequence: reserve → mark running → execute child → submit Return → refresh facts. On cancellation call Mac Core cancel and retain the last safe preview. Never synthesize `completed` locally.

- [ ] **Step 3: Implement ViewModel state**

Enable start only for approved Handoff and no active Session. Enable cancel only for reserved/running/returning. Preserve selection by `session_id` and `return_id`; ignore transient null during ItemsSource replacement.

- [ ] **Step 4: Implement native WPF panel**

Show fixed Provider, sandbox mode, 30-second timeout, status, failure code, Return ID, changed count, event count and explicit non-execution notice. Add no input fields other than existing Handoff controls.

- [ ] **Step 5: Add real STA layout tests**

Construct the production page, inject a fake gateway, run DataBind, Measure, Arrange and UpdateLayout, start a session, replace ItemsSource with equivalent IDs and require exact preview object retention. Assert no PasswordBox, browser, path picker, terminal or command control.

- [ ] **Step 6: Extend published self-test**

Require one Broker panel, the three native buttons, fixed boundary text and `ProviderConfigured=false`. Child mode must also have a deterministic self-test without creating a visible window.

- [ ] **Step 7: Run Windows gates**

Run legacy Task Center RED, complete WPF smoke, solution build with warnings as errors and published EXE self-test.

- [ ] **Step 8: Commit**

```powershell
git add windows/desktop
git commit -m "feat: expose Mock Dev Broker in native WPF"
```

### Task 8: Security mutation tests and full regression

**Files:**
- Create: `tests/security/test_broker_api_attack_surface.py`
- Create: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/DevBrokerMutationSmokeTests.cs`
- Modify: release and project-goal invariant tests as required.

**Interfaces:**
- Proves product and test suites fail when a shell, arbitrary command/path, capability leak, output limit removal or process-tree cleanup removal is introduced.

- [ ] **Step 1: Add Python mutations**

Mutate schemas and service policies to permit extra fields/files, wrong Provider or secret content and require the security suite to fail.

- [ ] **Step 2: Add Windows mutations**

Create test-only witnesses that replace the fixed executable with `cmd.exe`, remove Job Object kill-on-close, accept a caller path or exceed output limits. Each witness must observe failure before restoring sources.

- [ ] **Step 3: Run full regression**

Run all Python tests, Ruff, all Windows smoke tests and warnings-as-errors build. Record exact counts.

- [ ] **Step 4: Commit**

```bash
git add tests windows/desktop/tests contracts/release
git commit -m "test: harden Mock Dev Broker boundaries"
```

### Task 9: Version freeze to 2.3.12.1

**Files:**
- Modify: `src/picotoopet_core/product-version.txt`
- Modify: active current-version tests and package fixtures only.
- Modify: Windows title/shortcut/release assertions that intentionally track the current version.

**Interfaces:**
- Keeps historical 2.3.9.1, 2.3.10.1 and 2.3.11.1 evidence unchanged.

- [ ] **Step 1: Update the unique version source**

Set exactly:

```text
2.3.12.1
```

- [ ] **Step 2: Update active assertions**

Update health, WPF title, left header, shortcut, Manifest, package baseline and current compatibility tests. Do not alter contract version `1.0.0` or historical evidence.

- [ ] **Step 3: Run complete pre-release gates**

Run full Python regression, Ruff, Windows smoke and warnings-as-errors. Expected: green before triggering formal native release workflows.

- [ ] **Step 4: Commit**

```bash
git add src windows tests scripts contracts
git commit -m "release: freeze product version 2.3.12.1"
```

### Task 10: Exact-head native CI and formal packages

**Files:**
- Modify workflow files only if an actual exact-head gate identifies a workflow defect.
- Do not weaken any gate, runner target, lifecycle or evidence requirement.

**Interfaces:**
- Produces exact-head native evidence and formal prebuilt artifacts.

- [ ] **Step 1: Trigger/observe exact-head workflows**

Require:

- Windows Control Center WPF CI;
- Windows formal prebuilt Release and PowerShell 5.1 install/upgrade/activation-failure recovery/rollback;
- Mac Core arm64 full regression, Ruff, OpenAPI, offline install/verify/rollback;
- Mac Worker impact detection.

- [ ] **Step 2: Fix only observed defects**

For every failure, add or use a focused regression, make the smallest fix, commit and rerun all affected exact-head workflows.

- [ ] **Step 3: Confirm Worker impact result**

If Mac Worker runtime is unchanged, require the impact gate to pass and skip duplicate packaging. Do not force a cosmetic Worker release.

### Task 11: Independent artifact verification and Draft PR evidence

**Files:**
- Create local delivery manifest, checksums, independent verification JSON and Chinese real-machine validation steps.
- Update Draft PR body only after fresh evidence exists.

**Interfaces:**
- Produces user-installable Windows and Mac Core packages only when native gates authorize them.

- [ ] **Step 1: Download exact artifacts**

Download Windows formal package, Mac Core arm64 package and authoritative OpenAPI from exact-head successful runs.

- [ ] **Step 2: Independently verify**

Recompute outer and inner SHA-256, archive traversal/link safety, single top-level root, Manifest exact coverage, payload sizes/hashes, product version, source head, merge-test commit, executable allowlist, scripts, install boundaries and Broker OpenAPI paths/schemas.

- [ ] **Step 3: Verify Windows payload behavior**

Require published self-test markers for Control Center, Task Center, Handoff, Phase 10B-A Return and Phase 10B-B Broker. Confirm no additional executable and no shell/script daily UI.

- [ ] **Step 4: Update Draft PR**

Record exact source head, PR merge-test commit, run IDs, test counts, filenames, SHA-256, architecture and limitations. Keep Draft, open and unmerged.

- [ ] **Step 5: Deliver prebuilt packages**

Provide Mac Core first, then Windows, no Worker package when unchanged. User real-machine acceptance freezes `2.3.12.1` only after successful completed and cancelled Broker Session evidence.
