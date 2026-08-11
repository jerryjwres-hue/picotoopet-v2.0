# PicotooPet 2.3.21.1 — End-to-End Business Automation V1

## Status and base

This design is stacked directly on the 2.3.20.1 release-freeze source head `32f504344a343a6dd39d42609b2eb4ecc30574c1`.

Product version: `2.3.21.1`  
Database schema target: `14`  
PR policy: Draft/Open/Unmerged; no main merge, tag, or GitHub Release without explicit approval.

## Goal

Turn the already-shipped 2.3.18.1 → 2.3.19.1 → 2.3.20.1 capabilities into one durable daily business pipeline:

`Business Adapter → Work Package v1 → Business Local Intelligence → PASS Result Package v1 → Creative Intelligence → Creative Package v1 → ComfyUI Production → Production Package v1 → Return Package v1`

The run is quality-gated and restart-safe. Mac Core remains the source of truth. Windows remains the human control/data/GPU plane.

## Non-goals

2.3.21.1 does not add paid AI, cloud rendering, arbitrary ComfyUI workflows, arbitrary models, shell execution, arbitrary filesystem access, or automatic main/release publication. Those remain outside producer authority.

## Architecture

### 1. Mac Core: Business Pipeline Run

Add a durable `business_pipeline` module with a single orchestration aggregate, `BusinessPipelineRun`.

A run stores only immutable child identities and orchestration state; it does not duplicate child package contents.

Required identity chain:

- `pipeline_run_id`
- `work_package_id`
- `result_package_id`
- `creative_job_id`
- `creative_package_id`
- `production_job_id`
- `production_package_id`
- `return_package_id`
- `project_key`
- `adapter_profile`
- `producer_id` / `producer_version`

Durable statuses:

- `Ready`
- `BusinessAnalysis`
- `CreativeIntelligence`
- `AwaitingGpu`
- `Rendering`
- `QualityCheck`
- `Completed`
- `NeedsDeepAI`
- `NeedsHuman`
- `Rejected`
- `Failed`
- `Cancelled`

Every advance operation is idempotent. Child package/job IDs are write-once. A completed child stage is never recreated after restart.

### 2. Core background reconciler

Add a lightweight `BusinessPipelineScheduler` to the existing FastAPI lifespan, next to WorkflowScheduler.

It periodically reconciles non-terminal pipeline runs:

1. Observe Work Package state.
2. On `Completed`, require `BusinessResultPackage.quality_outcome == PASS`; bind the Result Package once.
3. Create one Creative job with fixed `creative.content_plan.v1`; bind its identity once.
4. Observe Creative state. On `creative_ready`, bind Creative Package once.
5. Create one Production job with fixed `production.comfyui.v1`; bind its identity once.
6. Wait for Windows GPU execution through the 2.3.20.1 production lease protocol.
7. Observe `production_ready`; bind Production Package once.
8. Build immutable Return Package v1 and transition the pipeline to `Completed`.

Quality outcomes do not get silently converted:

- business/creative `NEEDS_DEEP_AI` → pipeline `NeedsDeepAI`
- business/creative/production `NEEDS_HUMAN` → pipeline `NeedsHuman`
- reject → `Rejected`
- durable execution failure → `Failed`
- user cancellation → `Cancelled`

No unbounded retries are introduced. Existing stage retry limits remain authoritative.

### 3. Return Package v1

Core writes one immutable return package for the originating program. It contains references/digests, not duplicated large source data.

Required fields:

- schema version
- return package ID / pipeline run ID
- producer and adapter identity
- project key
- Work/Result/Creative/Production package IDs and digests
- final production outputs with relative path, media type, bytes, SHA-256
- source evidence/provenance chain inherited from Production Package v1
- stage status summary and quality outcome
- warnings/failures
- completed timestamp

The Return Package cannot contain commands, executable paths, credentials, arbitrary URLs, or user-selected model/workflow identities.

### 4. Windows adapters

Add a closed adapter layer under the existing Business Automation surface. V1 ships two first-party adapter profiles:

- `amazon.reviews_export.v1` → `reviews.voice_of_customer.v1`
- `inspiration.ideas_export.v1` → `ideas.pattern_analysis.v1`

Adapters accept only user-selected files/directories and create a valid Work Package v1 locally. They do not call models or Core internals directly.

Amazon adapter accepts CSV/JSON/JSONL/text review/product exports and normalizes them into bounded input artifacts. Inspiration adapter accepts JSON/JSONL/CSV/text idea/inspiration exports. The adapter does not invent business fields; unsupported formats fail closed.

Default bridge directories remain under `%LOCALAPPDATA%\PicotooPet\BusinessBridge`, with explicit subdirectories for `Inbox`, `Outbox`, and `Runs`. External applications may integrate by writing exports into their own locations and invoking the adapter/bridge contract; they never receive arbitrary path authority inside Core.

### 5. Windows End-to-End panel

Extend the existing Business Automation page rather than adding a new top-level Shell route.

The panel shows:

- adapter profile
- selected source
- project key / business objective
- pipeline run ID
- current stage/status
- bound Result / Creative / Production package IDs
- GPU waiting/rendering state
- final Return Package location
- quality outcome and actionable failure reason

Actions are bounded to:

- create Work Package from a first-party adapter
- submit/start pipeline
- refresh
- cancel active run
- open the managed Outbox/Return Package location

No endpoint/model/workflow/path/command editor is exposed.

## API

Add `/api/v1/business-pipeline` routes:

- `POST /runs` — create/idempotently bind a pipeline to an immutable Work Package
- `GET /runs`
- `GET /runs/{pipeline_run_id}`
- `POST /runs/{pipeline_run_id}/cancel`
- `POST /runs/{pipeline_run_id}/reconcile` — explicit idempotent diagnostic/manual reconciliation; background scheduler uses the same service
- `GET /runs/{pipeline_run_id}/return-package`
- `GET /runs/{pipeline_run_id}/return-package/archive`

Request models reject extra fields. Producer cannot submit child job/package IDs, model IDs, workflow IDs, endpoints, filesystem paths, commands, or provider selections.

## Migration 14

Add durable tables:

- `business_pipeline_runs`
- `business_return_packages`

Use unique constraints for `idempotency_key`, `work_package_id`, child package/job identities where applicable, and immutable package identity. Add indexes on status, project key, created/updated timestamps.

## Security invariants

1. Mac Core is the only pipeline state authority.
2. Business producer controls only business semantics/data, project key, objective, and first-party adapter/profile.
3. Creative profile is fixed to `creative.content_plan.v1`.
4. Production profile is fixed to `production.comfyui.v1`.
5. ComfyUI stays loopback-only at `127.0.0.1:8188` and uses the 2.3.20.1 source-controlled allowlist.
6. No arbitrary model/endpoint/prompt/system-prompt/workflow/command/tool/Git/GitHub authority is added.
7. No paid AI or cloud renderer is invoked automatically.
8. Existing Work/Result/Creative/Production packages remain immutable provenance anchors.

## Failure and recovery

- Reconcile is safe after Core restart and can run repeatedly.
- Bound child IDs are never replaced.
- Existing succeeded business, creative, or production stages are never rerun merely because the coordinator restarts.
- A Windows/GPU outage leaves the run at `AwaitingGpu`/`Rendering`; it does not fail the earlier stages.
- A failed or exhausted child stage converges the parent pipeline to the corresponding terminal outcome.
- Cancel requests delegate cancellation to the active child stage where supported, then converge the pipeline to `Cancelled` without rewriting completed child packages.

## Testing and release gates

TDD is required.

Core tests:

- Migration 14 and idempotency
- pipeline state transitions
- restart/reconcile does not duplicate Creative or Production children
- terminal quality propagation
- Return Package provenance/digest integrity
- API extra-field/security rejection
- scheduler recovery

Windows tests:

- Amazon and Inspiration adapter contract tests
- path traversal/unsupported extension/oversize rejection
- Work Package manifest/digest correctness
- End-to-End panel ViewModel smoke
- real WPF `Measure/Arrange/UpdateLayout`
- published EXE self-test

Final exact-head gates:

- Mac Core native CI
- Mac Worker native CI when impact gate says affected
- Windows Control Center native WPF CI
- Windows Prebuilt release lifecycle

Formal delivery includes all affected installers, SHA-256 values, independent artifact verification, and a daily/manual acceptance checklist.
