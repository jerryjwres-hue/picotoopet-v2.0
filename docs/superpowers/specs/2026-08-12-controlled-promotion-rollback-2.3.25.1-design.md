# PicotooPet 2.3.25.1 — Controlled Promotion / Rollback Design

Date: 2026-08-12
Target product version: `2.3.25.1`
Target database schema: `18`
Base: PicotooPet `2.3.24.1` frozen feature head `a3d77a9bdfc6d413565972971ed10dcb4c34045d`

## 1. Goal

Turn a human-reviewed 2.3.24.1 Shadow result into a versioned, auditable, reversible Promotion governance record without pretending that an executable prompt/model/provider patch exists.

The cumulative learning/governance chain becomes:

`Quality Learning Facts → Evaluation Snapshot → Offline Evaluation → Improvement Candidate → AcceptedForShadow → Controlled Shadow → AcceptedForPromotionReview → Promotion Proposal → exact human approval → Active Promotion Fact → exact rollback → restored prior Promotion Fact`

2.3.25.1 closes the governance loop. It does **not** make runtime prompts, models, providers, endpoints, budgets, ComfyUI workflows, or publication policy self-modifying.

## 2. Why Promotion is governance-only in 25.1

2.3.23.1 Improvement Candidates are closed review classes, not executable patches. 2.3.24.1 Shadow validates whether the quality signal reproduces across deterministic holdout arms; it does not author a replacement prompt, model, provider, endpoint, budget, or workflow.

Therefore 2.3.25.1 must not invent an executable policy payload. A Promotion means:

- an immutable Shadow-supported improvement signal has passed human promotion review;
- an exact proposal digest has been independently approved;
- the proposal is assigned a monotonically versioned Active governance record for its `(project_key, candidate_class)` slot;
- the previous Active record, if any, becomes `Superseded` and remains restorable;
- an exact rollback approval can mark the current version `RolledBack` and restore the immediately superseded prior version.

No 2.3.25.1 production runtime component reads the Active Promotion pointer to mutate execution. This is explicit, testable, and source-controlled.

## 3. Architecture boundary

### 3.1 Mac Core

Mac Core owns:

- Promotion eligibility checks against immutable 24.1 Shadow facts;
- proposal identity, version allocation, digests and state;
- exact activation approval requests/decisions;
- exact rollback approval requests/decisions;
- one-Active-per-slot registry semantics;
- transactional supersede/restore behavior;
- append-only decision/rollback evidence;
- schema 18 persistence and restart-safe reconciliation;
- authenticated APIs consumed by Windows.

### 3.2 Mac Worker

Mac Worker gains no Promotion execution role. Promotion/rollback performs zero local-model calls, zero paid-provider calls, zero ComfyUI calls, zero shell/browser/Git/GitHub/publication actions, and zero prompt/model/provider/endpoint/budget/workflow mutation.

### 3.3 Windows

Windows extends the existing Business Automation quality area with a bounded `受控晋级 / 回滚` subsection. It may:

- list eligible Shadow runs with terminal `AcceptedForPromotionReview` fact;
- create one immutable Promotion Proposal from a selected eligible Shadow run;
- display exact proposal and rollback approval digests;
- approve/reject/cancel bounded activation requests;
- request and approve/reject/cancel bounded rollback requests;
- display current Active/Superseded/RolledBack governance versions.

Windows cannot supply arbitrary prompt text, model IDs, provider IDs, endpoints, API keys, budgets, temperatures, tools, paths, workflow JSON, SQL, formulas, commands, shell, split rules, thresholds, or executable patch payloads.

No new top-level navigation route is added.

## 4. Eligibility

A Promotion Proposal may be created only when all are true:

1. the referenced Shadow Run exists and is `Completed`;
2. Shadow verdict is exactly `Supported`;
3. a terminal Shadow review fact exists with action exactly `AcceptedForPromotionReview`;
4. the referenced Improvement Candidate and Evaluation/Snapshot identities still match the immutable Shadow run digests;
5. no existing Promotion Proposal with a different immutable identity already claims the same Shadow run.

History/read APIs never create eligibility. `Reviewed`, `Rejected`, `Cancelled`, `NeedsMoreData`, or `NotReproduced` Shadow history can never be promoted.

## 5. Frozen profile and slot

The only Promotion profile is:

- `promotion_profile_id = quality.promotion.v1`

The governance slot is exactly:

- `slot_key = sha256(project_key + candidate_class + promotion_profile_id)`

The slot is not caller-configurable. There may be at most one `Active` Promotion per slot.

A Proposal receives a monotonically increasing integer `version_no` within its slot. Version allocation occurs transactionally in Mac Core and is not supplied by clients.

## 6. Proposal identity

A Promotion Proposal stores only immutable references and bounded governance metadata:

- `promotion_id`;
- `project_key`;
- `candidate_class`;
- `candidate_id`;
- `shadow_run_id`;
- `candidate_digest`;
- `shadow_report_digest`;
- `evaluation_report_digest`;
- `snapshot_digest`;
- `promotion_profile_id`;
- `slot_key`;
- `version_no`;
- `proposal_digest`;
- `status`;
- `supersedes_promotion_id` when activated;
- timestamps.

The proposal contains no raw prompt, provider secret, API key, arbitrary model/endpoint, budget, workflow JSON, path, SQL, formula, command, binary artifact, or raw dataset.

`proposal_digest` canonically binds all immutable proposal fields and version/slot identity.

## 7. Activation exact approval

Creating a Proposal does not activate it. It creates one bounded activation approval request with:

- `approval_kind = PromotionActivation`;
- exact `promotion_id`;
- exact `proposal_digest`;
- exact `slot_key` and `version_no`;
- state `Pending`;
- an approval `request_digest` derived from immutable request facts;
- expiry timestamp fixed by source-controlled policy;
- no secret token and no arbitrary payload.

Allowed activation decisions are closed to:

- `Approved`;
- `Rejected`;
- `Cancelled`.

The Windows decision request must echo the exact `request_digest` plus an `idempotency_key`. If the current request digest differs, Core rejects the decision and requires refresh.

`Approved` activates the Promotion transactionally:

1. re-check proposal eligibility and immutable source digests;
2. re-check there is no conflicting terminal decision;
3. mark any current Active record in the same slot as `Superseded`;
4. set its identifier as `supersedes_promotion_id` on the new Promotion;
5. mark the new Promotion `Active`;
6. append the exact decision fact.

`Rejected` and `Cancelled` are terminal and never activate.

## 8. Rollback exact approval

Rollback may be requested only for the current `Active` Promotion in a slot.

A rollback request contains only:

- `approval_kind = PromotionRollback`;
- exact current `promotion_id`;
- exact current `proposal_digest`;
- exact `slot_key` and `version_no`;
- exact `restore_promotion_id` if an immediately superseded prior version exists, otherwise null;
- bounded `rollback_reason_code` from a closed enum;
- request digest and expiry.

Closed rollback reason codes:

- `RegressionObserved`;
- `UnexpectedImpact`;
- `OperatorDecision`.

Allowed rollback decisions are closed to `Approved`, `Rejected`, `Cancelled`.

On exact rollback approval, Mac Core transactionally:

1. re-checks the current record is still Active and the request digest matches;
2. marks the current record `RolledBack`;
3. restores its `supersedes_promotion_id` to `Active` when present and still eligible for restoration;
4. records a rollback fact containing before/after promotion identities and digests;
5. performs no runtime policy mutation and no external execution.

If there is no prior Promotion, rollback leaves the slot with no Active record.

## 9. Status model

Canonical Promotion statuses:

- `AwaitingApproval`;
- `Active`;
- `Superseded`;
- `RolledBack`;
- `Rejected`;
- `Cancelled`.

Canonical approval request statuses:

- `Pending`;
- `Approved`;
- `Rejected`;
- `Cancelled`;
- `Expired`.

No other state is accepted or generated.

## 10. Schema 18 persistence

Migration 18 adds normalized durable facts for at least:

- `quality_promotions`;
- `quality_promotion_approval_requests`;
- `quality_promotion_decisions`;
- `quality_promotion_rollbacks`.

Required constraints include:

- unique Shadow-run-to-Promotion identity;
- unique `(slot_key, version_no)`;
- partial unique index allowing at most one `Active` Promotion per `slot_key`;
- unique idempotency keys for decisions;
- approval request identity bound to Promotion/action kind;
- append-only decision and rollback fact identities.

Migrations 1–17 remain unchanged and apply sequentially before Migration 18.

## 11. Restart safety and reconciliation

Promotion creation is idempotent on immutable Shadow identity. Activation and rollback decisions are idempotent on decision idempotency keys and exact request digests.

Core exposes reconcile for one Promotion. Reconcile may repair a missing derived approval-request status or registry pointer under the same identities, but it must never:

- allocate a new version for an existing Promotion;
- create a second Active version for one slot;
- re-approve a rejected/cancelled request;
- re-activate a RolledBack Promotion;
- reserve paid spend;
- call any model/provider/ComfyUI/publication executor;
- mutate prompt/model/provider/endpoint/budget/workflow policy.

## 12. API boundary

Mac Core adds authenticated APIs for:

- create/list/get Promotion Proposals;
- get current Active Promotion for a slot/project/candidate class;
- reconcile one Promotion;
- get activation approval request;
- decide activation with closed decision + exact request digest + idempotency key;
- create/get rollback approval request using only closed reason code;
- decide rollback with closed decision + exact request digest + idempotency key;
- list immutable Promotion decisions/rollback facts.

Strict request models use `extra="forbid"`.

Create accepts only `shadow_run_id`.

Activation decision accepts only:

- `decision` closed enum;
- `request_digest`;
- `idempotency_key`.

Rollback request accepts only closed `rollback_reason_code`.

Rollback decision accepts only the same bounded decision triple.

## 13. Windows UX

The existing Business Automation quality surface gains a `受控晋级 / 回滚` subsection with:

- eligible Shadow selection;
- Promotion proposal version/status/digest;
- exact approval request digest/status;
- `批准晋级`, `拒绝`, `取消` actions;
- current slot Active version;
- bounded rollback reason selector using the three fixed enum values;
- `申请回滚` plus exact rollback decision buttons;
- read-only Promotion history.

All record-only bindings are explicit `Mode=OneWay`. Real STA `Measure/Arrange/UpdateLayout` coverage is required.

There are no free-form policy/value editors.

## 14. Security invariants

2.3.25.1 preserves all 2.3.24.1 invariants and adds:

- only `Supported + AcceptedForPromotionReview` Shadow facts can create Promotion Proposals;
- exact immutable digests are rechecked before activation and rollback;
- one Active Promotion per slot;
- version numbers are Core-assigned and monotonic;
- activation and rollback require independent exact human decisions;
- rollback restores only the immediate immutable superseded predecessor;
- no runtime component consumes Active Promotion to mutate execution in 25.1;
- no automatic prompt/provider/model/endpoint/budget/workflow mutation;
- no automatic paid spend increase;
- no local/paid AI or ComfyUI execution caused by Promotion;
- no automatic publication, push, merge, tag, or GitHub Release;
- history visibility never reopens Shadow, Candidate, or Deep-AI eligibility.

## 15. TDD and native verification

Required regression groups:

1. Migration 18 applies after Migration 17 and preserves schema 1–17.
2. Only exact `Supported + AcceptedForPromotionReview` Shadow results are eligible.
3. Proposal creation is idempotent and source-digest-bound.
4. Version allocation is monotonic per slot and not client-controlled.
5. Activation approval request has immutable digest, expiry, and closed decisions.
6. Activation creates exactly one Active version and supersedes prior Active atomically.
7. Repeated activation decision is idempotent; conflicting or stale digest decisions fail closed.
8. Rollback request only targets current Active version and uses closed reason codes.
9. Approved rollback marks current RolledBack and restores immediate predecessor, or leaves slot empty.
10. Restart/reconcile preserves version/run/decision identities and never duplicates Active records.
11. Zero paid attempts, zero local/paid AI, zero ComfyUI, zero publication/Git execution, zero runtime policy mutation.
12. Strict API extra-field rejection.
13. Windows REST contracts, bounded controls, OneWay record bindings and real STA WPF layout smoke.
14. Release rollup: product `2.3.25.1`, schema `18`, cumulative 18–24 capabilities retained.

Final exact-head native gates:

- Mac Core native CI;
- Mac Worker native CI;
- Windows Control Center native WPF CI;
- Windows Prebuilt release lifecycle CI.

Delivery contains prebuilt Mac Core, Mac Worker and Windows packages, SHA-256 evidence, independent package verification and cumulative real-machine acceptance instructions. User machines do not compile source.

## 16. Explicit non-goals

2.3.25.1 does not include:

- authoring or editing replacement prompt text;
- selecting or changing provider/model/endpoint/budget;
- applying Promotion records to production runtime execution;
- autonomous policy mutation;
- automatic Promotion without exact human approval;
- fine-tuning/training;
- paid/local model execution caused by Promotion;
- ComfyUI/cloud-renderer execution caused by Promotion;
- automatic publication;
- automatic main merge/tag/GitHub Release.

## 17. Release state

2.3.25.1 is developed as a stacked Draft PR directly on frozen 2.3.24.1 head `a3d77a9bdfc6d413565972971ed10dcb4c34045d`.

Feature branch: `feature/controlled-promotion-rollback-2.3.25.1`.

It remains Draft/Open/Unmerged through CI/package freeze and later cumulative real-machine acceptance.