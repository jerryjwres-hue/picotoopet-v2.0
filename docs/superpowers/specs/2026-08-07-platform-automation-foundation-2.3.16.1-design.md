# Phase 2.3.16.1 — Platform Automation Foundation + Core UI Completion

## Goal

Finish the shared automation platform before any Amazon/灵感助手 business adapter is connected. PicotooPet must own durable projects, workflow orchestration, artifact provenance, capability routing, quality decisions, generalized handoff/return continuation, and useful operational UI.

## Existing facts reused

- Mac Core + SQLite remains the fact source.
- Existing `projects`, `artifacts`, `tasks`, `task_dependencies`, `task_attempts`, `task_events`, `approvals`, `handoffs`, `returns`, and outbox tables are preserved.
- Existing task queue semantics (priority, attempts, timeout, idempotency, leases) remain authoritative.
- Windows remains the existing native WPF `Picotoo Pet AI.exe`; it is observation/control only and never becomes a Worker.
- Mac Worker executes only registered task types.
- Existing cloud-development safety boundaries remain unchanged.

## New platform model

A Workflow is durable orchestration metadata above existing queue tasks. A workflow contains ordered/dependency-linked steps, and every executable step is materialized as a normal queue task. The workflow never bypasses the queue.

State machine:

`Draft -> Ready -> Running -> Paused -> Running -> Completed`

Terminal alternatives: `Cancelled`, `NeedsAttention`, `Failed`.

Step states: `Pending`, `Blocked`, `Ready`, `Running`, `Succeeded`, `RetryWaiting`, `NeedsHuman`, `NeedsDeepAI`, `Rejected`, `Cancelled`, `Failed`.

Transitions are deterministic and persisted transactionally. A process restart reconstructs state from SQLite; no in-memory-only terminal facts exist.

## Required controls

- DAG validation rejects missing dependencies, self-dependencies and cycles.
- Each step has bounded `max_attempts` and `timeout_seconds`.
- Workflow has bounded concurrency and priority.
- Pause stops creation/dispatch of new executable work but does not invent cancellation of already leased work.
- Resume recomputes eligible steps from persisted facts.
- Cancel marks not-yet-running steps cancelled and uses the existing task cancellation path for queue-backed work.
- Idempotency keys make create/resume/reconcile replay-safe.
- Checkpoints are persisted after every orchestration decision.

## Artifact provenance

Existing `artifacts` is retained and extended with provenance/link metadata rather than replaced. Every recorded artifact carries SHA-256, producer workflow/step/task, optional model/capability, and immutable parent/input links. This is metadata only: the platform never enumerates arbitrary user directories while creating provenance records.

## Capability router

Workers register typed capabilities, not model brand assumptions. Initial normalized capabilities:

- `local.text.analysis`
- `local.text.generation`
- `local.vision.analysis`
- `local.image.generation`
- `local.video.generation`
- `external.deep.reasoning`

Routing is deterministic from required capability + health + registration freshness + explicit policy. No paid/cloud provider call is performed by registration or routing.

## Quality gate

A step may emit one of:

- `PASS`
- `RETRY`
- `NEEDS_DEEP_AI`
- `NEEDS_HUMAN`
- `REJECT`

The decision is persisted with rule/evidence metadata. `RETRY` is bounded by the step retry policy. `NEEDS_DEEP_AI` creates a generalized handoff continuation request but does not itself call a paid provider. `NEEDS_HUMAN` pauses the affected path for explicit approval/review.

## Generalized handoff/return continuation

The existing Handoff/Return records are reused. New workflow continuation metadata binds a handoff to an exact workflow/step/checkpoint digest. Return validation must match that digest before the step can resume. This generalizes the mechanism without weakening the existing cloud-development provider boundaries.

## Health and diagnostics

Health is structured facts: Core, DB, queue/outbox, Worker heartbeat/capabilities, and registered execution services. Diagnostics is structured operational metadata: recent workflow/task failures, retry counts, correlation/trace identifiers and safe error codes/messages. It must not add project scans, log-body capture, tokens, paid inference or user-file enumeration to `system.diagnostic_snapshot`.

## Windows WPF completion

Replace major placeholder surfaces with native pages backed by Mac Core facts:

- Projects: list/create/archive project metadata and status.
- Automation: workflow list/detail, step state, progress, pause/resume/cancel.
- Health: structured service/capability/queue health.
- Diagnostics: recent structured failures and correlation IDs.

No fake/sample operational rows in formal runtime. Empty states are allowed only when the fact source truly has no records.

## Security boundaries

- No arbitrary shell/command field in workflows.
- No arbitrary Worker execution type: only registered task types/capabilities.
- No implicit cloud upload or provider call.
- No token/log-body/user-file enumeration added to diagnostics.
- No merge/release/push automation is added in this version.
- Business program adapters are intentionally deferred.

## Release gates

1. RED regression proves the capability is absent before production implementation.
2. Python unit/integration tests for migration, DAG, replay, pause/resume/cancel, routing, quality decisions, provenance and continuation.
3. Windows native compile + real WPF Measure/Arrange/UpdateLayout tests for all four completed pages.
4. Mac Core native CI.
5. Mac Worker native CI, unless an explicit impact gate proves no Worker payload change (not expected here because capability registration is added).
6. Prebuilt Windows + Mac Core + Mac Worker packages; no user-side compilation/SDK.
7. Independent manifest/hash/archive/architecture verification and manual acceptance document.
8. Draft PR only; no main merge/tag/release without explicit authorization.
