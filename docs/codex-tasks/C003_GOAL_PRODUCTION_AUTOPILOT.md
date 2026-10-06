# C003 — Goal Production Autopilot

## Goal

Close the remaining product gap after C001/C002:

```
Goal
  -> research
  -> manual Web GPT
  -> Windows paste return
  -> Core validates/adopts
  -> Creative package
  -> Production job
  -> Windows automatically executes the existing closed Production plan
  -> Goal Center observes production_ready / failure
```

Today the Production plane already exists, but normal execution is still manually triggered from ProductionPanelViewModel via selecting a job and calling StartSelectedAsync().

C003 must reuse the existing ProductionExecutionService and Core Production APIs. Do not create another renderer/executor/pipeline.

## Branch / baseline

Work only on:
`feature/goal-production-autopilot`

Baseline:
`a56cd192c33be2c13e6f64f99552f0cd1e24ea2f`

Do not rebase or merge other feature branches.

## Existing components — MUST reuse

- C001/C002 GoalVideoContinuationRecord
- GoalVideoContinuationViewModel
- ProductionExecutionService
- ControlCenterSession Production API methods
- Core ProductionService claim / heartbeat / attempt / result / failure / package lifecycle
- source-controlled Comfy workflow catalog
- fixed production profile `production.comfyui.v1`
- loopback Comfy endpoint
- existing Core lease/idempotency/restart rules

## Required behavior

### 1. Automatic handoff from Goal continuation to local Production executor

When the current completed video Goal has a continuation with:
- a non-empty `production_job_id`
- a recoverable Production status

Windows should automatically start/resume the existing Production job without requiring the user to open the Production panel and click Start.

The trigger must be scoped only to the Production Job ID returned by that Goal continuation.
Do NOT scan arbitrary jobs and auto-run them.

### 2. Non-blocking UI

Rendering can take minutes.

The existing Goal Center 5-second refresh MUST NOT await an entire render.

Add a small long-lived Windows coordinator/service that:
- observes the current Goal continuation
- starts at most one execution task per production job at a time
- returns immediately to UI refresh
- owns cancellation/disposal
- does not launch duplicate runs on every 5-second tick
- uses `ProductionExecutionService.RunAsync(productionJobId)`

### 3. Restart-safe behavior

Reuse Core claim/lease/recovery semantics.

Do not invent Windows durable lifecycle state.

After Windows/app restart:
- Goal Center refresh reconstructs continuation from Core
- if the Production job is recoverable, coordinator may resume it through the existing executor/claim path
- already `production_ready`, Failed, NeedsHuman, or Cancelled jobs must not be re-rendered

Treat the actual serialized Core statuses as source of truth:
- initial job status is `Ready`, not `Planned`
- recoverable active statuses must be evidence-backed by existing Production claim behavior

Also fix any existing Windows status mismatch where the UI expects `Planned` while Core serializes `Ready`.

### 4. Safety

Autopilot may only execute the existing immutable Core Production Plan.

No new inputs for:
- workflow
- model
- endpoint
- local path
- command
- prompt
- seed
- dimensions
- renderer

Preflight remains mandatory because `ProductionExecutionService.RunAsync` already performs it.

If preflight fails:
- do not submit Comfy prompts
- do not loop aggressively
- expose a safe bounded status in Goal Center
- allow a later refresh/retry after the local condition is corrected

### 5. Goal Center status

Do not expose raw Production status strings directly to the user.

Map known states to bounded UI text with an unknown fallback.

At minimum distinguish:
- waiting to start
- preflight / rendering / collecting / quality check
- production ready
- needs human
- failed
- cancelled
- temporary local execution/preflight failure

Keep raw Core facts internally if needed, but user-facing text must be bounded.

### 6. Manual Production panel remains

Do NOT remove the Production panel.

Its manual controls remain available for diagnostics/recovery.

Fix the existing `Ready` vs `Planned` mismatch if confirmed.

Autopilot and manual panel must share the same `ProductionExecutionService` behavior and Core lease semantics; no second execution implementation.

## Suggested implementation surface

Prefer minimal additions/changes in Windows only:

- new small coordinator/service under:
  `windows/desktop/src/PicotooPet.Desktop/Services/`
- `OperatorHomePageViewModel.cs` and/or Goal continuation projection
- Goal Center status presentation
- `ProductionPanelViewModel.cs` if fixing the Ready/Planned mismatch
- focused Windows smoke tests

Backend changes are NOT expected.
If a Core contract is actually missing, stop and report it before building a parallel workaround.

## Concurrency requirements

- one in-flight local render task per Production Job ID
- repeated 5-second observations of the same active job must not create duplicate `RunAsync`
- switching current Goal must not let a stale completion overwrite the new Goal UI
- disposal/app shutdown cancels local observation cleanly
- Core remains the durable concurrency authority through claim/lease

Do not add a Windows database/table/file for this.

## Error behavior

- auth/pairing error: safe connection message
- preflight/local Comfy unavailable: safe local-production message
- Core state conflict: refresh/reconcile from Core
- terminal Production state: do not retry automatically
- no raw exception body, local path, token, prompt, or model internals in Goal Center UI

Avoid hot retry loops.
Use the existing 5-second Goal refresh as the observation cadence; coordinator should suppress duplicate launches.

## Tests required

At minimum:

1. Autopilot coordinator
- Ready Goal Production job starts automatically
- repeated observations while one run is active do not duplicate RunAsync
- production_ready / Failed / NeedsHuman / Cancelled never start
- dispose cancels/ignores late completion
- switch Goal ignores stale completion
- transient/preflight failure does not invent success
- later observation may retry after failure without busy loop

2. Goal Center
- submit return remains manual
- after accepted continuation, Production execution is automatic
- UI refresh remains non-blocking
- mapped production status has unknown fallback
- no raw error/path/token/prompt shown

3. Existing Production panel
- Core serialized `Ready` job is startable
- existing manual preflight/start/cancel behavior remains

4. Regression
- existing C002 smoke tests
- existing Production smoke tests
- Windows Control Center CI

## Architecture invariants

- Mac Core is source of truth.
- Windows is a closed local GPU executor only.
- No new Production lifecycle or job store.
- No duplicate Creative/Production implementation.
- No arbitrary workflow/model/endpoint/path/command authority.
- No provider credentials.
- No browser automation.
- Do not touch Research Gateway.
- Do not touch Mac Worker/Ollama lifecycle code (Claude owns S001).
- Do not touch deploy/macos.
- Do not touch Natural Motion/torso asset gate.

## Acceptance

PASS when a normal user can:

1. complete a video Goal
2. manually send handoff to Web GPT
3. paste the return in Goal Center
4. C001/C002 creates the canonical Production job
5. Windows automatically preflights and claims that exact job
6. existing Comfy executor renders it
7. Core reaches `production_ready` or a bounded terminal state
8. Goal Center displays the resulting Production state without requiring the user to open Production panel

No merge/tag/release.
