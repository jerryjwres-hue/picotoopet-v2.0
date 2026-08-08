# 2.3.16.1 Platform Automation Foundation — Implementation Plan

**Approved direction:** finish generic automation/platform capabilities before Amazon/灵感助手 integration. Preserve Mac Core + SQLite fact-source and existing WPF delivery surface.

## Task 1 — RED contracts

Files:
- `tests/unit/automation/test_workflow_foundation.py`
- `tests/unit/automation/test_platform_contract_source.py`

First prove current head lacks the new `picotoopet_core.automation` contract. Tests require deterministic DAG validation, durable workflow creation, capability routing, quality decisions and explicit new Windows navigation/page source names. Run native CI and retain the expected failing evidence before production code.

## Task 2 — Database migration 9

Modify:
- `src/picotoopet_core/db/schema.py`
- `src/picotoopet_core/db/database.py`

Add durable tables:
- `workflow_runs`
- `workflow_steps`
- `workflow_step_dependencies`
- `workflow_checkpoints`
- `artifact_provenance`
- `artifact_links`
- `capability_registrations`
- `quality_decisions`
- `workflow_handoff_continuations`

Migration is append-only/idempotent and must preserve every existing table and migration 1–8.

## Task 3 — Automation domain and repository

Create:
- `src/picotoopet_core/automation/__init__.py`
- `src/picotoopet_core/automation/models.py`
- `src/picotoopet_core/automation/repository.py`
- `src/picotoopet_core/automation/dag.py`

Model workflow/run/step/checkpoint/capability/quality/provenance facts with strict Pydantic validation. Repository owns transactional serialization/deserialization only.

Tests:
- missing/self/cyclic dependency rejection
- deterministic topological order
- create idempotency
- restart reload equality

## Task 4 — Workflow service and scheduler

Create:
- `src/picotoopet_core/automation/service.py`
- `src/picotoopet_core/automation/scheduler.py`

Reuse existing task queue. Materialize ready executable steps as registered queue task types. Enforce priority, timeout, max attempts and concurrency. Pause/resume/cancel/reconcile are durable and replay-safe.

Tests:
- dependency unlock
- bounded concurrency
- pause prevents new materialization
- resume recomputes readiness
- cancel does not fabricate success
- restart reconcile recovers persisted state
- terminal workflow state derived only from step/task facts

## Task 5 — Artifact provenance

Create:
- `src/picotoopet_core/automation/artifacts.py`

Persist producer workflow/step/task, SHA-256, capability/model metadata and parent links. Reject provenance records without immutable digest. Never scan/enumerate a user directory as a side effect.

## Task 6 — Capability router

Create:
- `src/picotoopet_core/automation/capabilities.py`

Typed capability names and heartbeat freshness. Routing is deterministic and local policy-only; registration/routing cannot call providers.

Tests include stale registration rejection and deterministic tie-breaking.

## Task 7 — Quality gate + generalized continuation

Create:
- `src/picotoopet_core/automation/quality.py`
- `src/picotoopet_core/automation/continuation.py`

Persist `PASS/RETRY/NEEDS_DEEP_AI/NEEDS_HUMAN/REJECT`. Bind generalized Handoff/Return continuation to exact workflow/step/checkpoint digest. `NEEDS_DEEP_AI` may prepare continuation facts only; no paid provider invocation.

## Task 8 — Mac Core API

Create/update FastAPI routes for:
- projects
- workflows
- capabilities
- automation health
- structured diagnostics

Update service container/app router registration. Use existing authentication/error middleware. API mutations require explicit commands and idempotency where applicable.

## Task 9 — Worker capability registration

Add Worker startup capability declaration/heartbeat using the existing Core control path. It advertises only capabilities backed by registered task handlers. No dynamic arbitrary command registration.

## Task 10 — Windows native WPF completion

Add typed contracts/gateway methods and native pages/viewmodels:
- Projects
- Automation
- Health
- Diagnostics

Wire existing shell navigation to these real pages. Keep Task Center, Results, Approvals, Cloud Development and Settings unchanged except shared DTO/client additions.

Add real WPF page construction plus `Measure/Arrange/UpdateLayout` regression coverage for the four pages. No browser/helper executable/fake runtime data.

## Task 11 — Product version and release invariants

Set product version to `2.3.16.1` everywhere governed by existing version contracts. Update expected latest migration to 9. Preserve formal installer lifecycle and `user_install_allowed` invariants.

## Task 12 — Native verification and packaging

Run/fix until green:
- Python full regression + Ruff
- Windows WPF native CI
- Windows prebuilt installer workflow
- Mac Core arm64 native CI/package
- Mac Worker arm64 native CI/package

Use systematic debugging for any failure; do not weaken tests or gates to obtain green.

## Task 13 — Draft PR and formal evidence

Create/maintain Draft PR based on the 2.3.15.1 feature branch. Record exact source head/build commit/tree and native run IDs/artifact IDs.

Download formal artifacts and independently verify:
- version
- exact commit/tree provenance
- target architecture
- archive path safety/no duplicates/no unsafe links
- manifest coverage/hash/size
- no user-side build requirement

Generate:
- `PicotooPet-2.3.16.1-INDEPENDENT-VERIFICATION.json`
- `PicotooPet-2.3.16.1-MANUAL-ACCEPTANCE-CN.md`

Do not merge/tag/release. Real-machine acceptance is the final gate before any later merge authorization.
