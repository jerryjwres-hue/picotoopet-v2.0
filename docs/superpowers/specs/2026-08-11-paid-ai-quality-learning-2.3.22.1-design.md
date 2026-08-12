# PicotooPet 2.3.22.1 — Paid-AI Escalation + Quality Learning Design

Date: 2026-08-11
Target product version: `2.3.22.1`
Target database schema: `15`
Base: PicotooPet `2.3.21.1` source head `c4ccdf26e85381c354d01aa51a45c5c93ae72610`

## 1. Goal

Add a bounded, approval-gated, API-first escalation plane for tasks that have already reached `NEEDS_DEEP_AI`, while preserving the existing manual Web GPT handoff as a fallback. Add a durable quality-learning ledger that records what happened and what humans accepted, rejected, or modified without automatically changing prompts, models, budgets, provider selection, or training data.

The cumulative business chain becomes:

`Business Adapter → Work Package v1 → Local Intelligence → Quality Gate → [PASS | NEEDS_DEEP_AI | NEEDS_HUMAN | REJECT] → Creative Intelligence → ComfyUI Production → Return Package`

For `NEEDS_DEEP_AI` only:

`NEEDS_DEEP_AI → Sanitized Escalation Package → exact Approval → ProviderReady → [execution disabled by default] → Paid-AI API Result → deterministic validation → PASS | NEEDS_HUMAN | REJECT`

Paid-AI execution is infrastructure-complete in 2.3.22.1 but disabled by default. Installing 2.3.22.1 must never create a paid API call automatically.

## 2. Architecture boundary

### 2.1 Mac Core

Mac Core remains the durable source of truth. It owns:

- Deep-AI Escalation Job identity and state;
- source task/result/package provenance;
- sanitized request-package digest and immutable payload identity;
- approval identity and approval-terminal reconciliation;
- provider-profile identity, but never provider secrets;
- budget ceilings and observed usage/cost facts;
- result validation outcome;
- Quality Learning ledger facts;
- authenticated APIs exposed to Windows and Mac Worker.

Core must not hold paid-provider API keys and must not perform paid-provider network execution.

### 2.2 Mac Worker

Mac Worker is the only component that may execute a paid-AI provider adapter. It:

- reads trusted provider configuration from Worker-owned configuration;
- claims only Core-authorized, approved, ProviderReady escalation jobs;
- validates the immutable request digest before sending;
- enforces call-count/token/cost ceilings before each provider call;
- calls only a closed provider adapter/profile;
- sends no tool, shell, browser, Git/GitHub, ComfyUI, arbitrary URL, or command authority;
- returns provider response, usage, cost, and error facts to Core;
- never broadens a task's budget or provider profile after approval.

### 2.3 Windows

Windows remains the business-data/control/GPU plane. It may:

- show escalation state and immutable budget summary;
- open the existing Approval Center for exact task approval/rejection;
- show observed provider usage after execution;
- collect explicit human feedback for Quality Learning;
- export/open the existing manual sanitized Handoff when API execution is unavailable or disabled.

Windows must not receive API keys, arbitrary provider endpoints, arbitrary model IDs, raw provider credentials, or free-form execution controls.

No new top-level Shell route is added. Escalation and Quality Learning surfaces are embedded under existing Business Automation / Approval / Results surfaces.

## 3. Closed escalation eligibility

A paid-AI escalation may be created only from an existing durable fact whose quality outcome is `NEEDS_DEEP_AI`.

Supported 2.3.22.1 source classes are closed to semantic/reasoning stages already represented by the product, including Business Local Intelligence and Creative Intelligence stages. Production/ComfyUI rendering failures are explicitly not eligible for automatic paid-video or cloud-renderer escalation in 2.3.22.1.

The caller cannot create an escalation from an arbitrary prompt or arbitrary file.

Creation is idempotent on the immutable source identity and escalation policy version. Repeated create/reconcile calls must return the same Escalation Job rather than creating duplicate paid opportunities.

## 4. Sanitized Escalation Package v1

Core derives a managed immutable package from trusted source records. The package includes only the minimum required context:

- schema/profile identifiers;
- source Work/Result/Creative identifiers and digests as applicable;
- bounded evidence snippets selected by trusted preprocessing;
- local result or stage result needed to explain the failure;
- deterministic quality reasons;
- fixed task instruction generated from source-controlled templates;
- fixed return schema;
- provenance digests;
- sanitizer version and request-package digest.

The package must exclude:

- API keys, tokens, passwords, cookies, authorization headers;
- absolute local paths, home-directory names, database paths, executable paths;
- arbitrary raw Work Package archives;
- unrelated project data;
- shell/PowerShell/command text intended for execution;
- tool definitions or tool-call authority;
- arbitrary URLs supplied by producer/model/user data;
- Git/GitHub/ComfyUI credentials or execution authority.

Large raw source datasets remain local by default. A bounded evidence subset is sent instead.

## 5. Provider profiles

Provider execution is API-first and closed-profile only.

A provider profile is a trusted local configuration object identified by `provider_profile_id`. It freezes or derives:

- provider adapter implementation;
- approved API endpoint family;
- approved model class/model identifier;
- request format/version;
- response format/version;
- pricing metadata/version used for preflight estimation;
- maximum request/response token policy;
- timeout/retry policy;
- whether real paid execution is enabled.

The source Work Package, local model output, Windows UI, and Core API request must not be allowed to override endpoint, model, temperature, tools, commands, provider URL, or API key.

`provider_profile_id` is resolved by a trusted Escalation Policy mapping owned by the product/administrator, based only on the closed source-stage/profile class. Resolution happens when the Escalation Job is prepared. The resolved provider profile identity and profile digest are frozen into the job and later approval envelope. Windows, the business producer, local/paid model output, and the approval action cannot swap the provider or model. Changing the trusted mapping affects only newly prepared jobs unless an existing job is explicitly cancelled and recreated under a new immutable policy version.

22.1 ships with real-execution policy disabled by default. CI uses fake/local provider adapters and performs no paid network request.

The existing manual Web GPT sanitized Handoff remains an explicit fallback path when no enabled API provider is configured or when the user chooses manual handling.

## 6. Exact approval and cost envelope

Every paid Escalation Job requires a dedicated approval that binds the exact immutable execution envelope:

- escalation job ID;
- source identity and source digests;
- sanitized request-package digest;
- provider profile ID and provider-profile version/digest;
- model identity/class;
- max input tokens;
- max output tokens;
- max provider calls;
- max cost in USD;
- approval expiry;
- policy version.

Approval must be invalidated or rejected if any bound field changes.

The default 2.3.22.1 execution envelope is bounded to:

- at most one primary paid call;
- at most one schema/structure repair call;
- both calls share the same approved total token and USD budget;
- no unlimited semantic retries;
- no automatic budget increase.

A repair call is allowed only when the first response is semantically acceptable enough to preserve but fails a deterministic structural/return-schema check. A true semantic failure transitions to `NeedsHuman` or `Rejected` according to policy rather than consuming repeated paid calls.

Before each provider call the Worker computes the bounded request-token estimate and worst-case call cost from the frozen request plus trusted provider pricing metadata. It then verifies that the remaining approved call/token/cost envelope can cover that call. If it cannot, no request is sent and the job converges to `NeedsHuman` with a durable budget/preflight reason.

Observed provider usage and actual/estimated cost are durably returned to Core after every accepted provider response. If a provider does not return an authoritative price, cost is computed from the trusted pricing metadata version and recorded as calculated rather than provider-reported.

## 7. Escalation state machine

Canonical job states:

- `Prepared`
- `WaitingApproval`
- `Approved`
- `ProviderReady`
- `Claimed`
- `Executing`
- `Validating`
- `Completed`
- `NeedsHuman`
- `Rejected`
- `Failed`
- `Cancelled`

`Approved` does not imply the provider is configured or enabled. `ProviderReady` requires all of:

1. exact approval still accepted and unexpired;
2. trusted provider profile exists;
3. real execution is explicitly enabled for that trusted profile;
4. required Worker secret/config is present;
5. budget preflight passes.

If execution is disabled or provider configuration is absent, the job remains non-spending in an approved/non-executing state and exposes the manual Handoff fallback rather than failing unpredictably.

Claim/retry behavior must be restart-safe. A provider response that has already been durably committed must never be paid for or requested again after Worker/Core restart.

## 8. Provider attempt protocol

To avoid an orphan paid request, Core reserves an immutable attempt before Worker performs the provider call.

Protocol:

1. Worker claims an eligible job with a lease.
2. Worker asks Core to reserve attempt N under the approved envelope.
3. Core atomically verifies lease, approval, remaining budget and call count, then writes the reservation.
4. Worker submits one provider request using the reserved attempt identity/idempotency metadata when supported by the provider.
5. Worker returns provider request ID, response digest, usage and cost to Core.
6. Core atomically binds the provider request/result to the same attempt and advances validation.
7. On restart, Worker reads durable attempts before any new paid call.

A transport ambiguity must not immediately cause another paid request. The adapter first performs provider-specific read/reconciliation when supported. If exact reconciliation is impossible, the job converges to `NeedsHuman` rather than risking duplicate spend.

## 9. Deterministic result validation

Paid-AI output does not bypass Quality Gates. Core/Worker apply deterministic checks including:

- expected schema and field bounds;
- evidence/source-reference validity;
- required provenance links;
- no forbidden execution instructions/authority;
- profile-specific semantic guardrails that can be checked deterministically;
- response digest and package identity.

Successful validation produces a durable accepted Deep-AI result that can satisfy the originating `NEEDS_DEEP_AI` stage and allow the existing pipeline to continue.

Validation outcomes are closed:

- `PASS`
- `NEEDS_HUMAN`
- `REJECT`

A structural-only failure may consume the one approved repair call if budget remains. It must not trigger an unbounded paid repair loop.

## 10. Quality Learning Ledger v1

Schema 15 adds append-only/durable learning facts. The ledger records observations; it does not autonomously modify runtime policy.

For each relevant stage/task, record where available:

- source project/task/work/result/creative/production identities;
- analysis/creative/production profile and template version;
- local model/adapter/version identity;
- local attempt count and quality outcome;
- quality reason codes;
- escalation job/provider profile/model identity;
- sanitized input digest and paid output digest;
- observed token usage/cost;
- paid validation outcome;
- human action: `Accepted`, `Rejected`, `Modified`, `NoDecision`;
- optional bounded reason tags;
- digest of human-modified final content rather than unrestricted raw history;
- downstream artifact/return-package reference when applicable;
- future business metric references such as CTR/completion/conversion when later imported through trusted adapters.

22.1 must not automatically:

- rewrite prompt templates;
- change provider or model;
- raise budgets;
- retrain/fine-tune a model;
- convert ledger facts into training data;
- retry old work because a later metric changed;
- publish content.

Those are later policy-learning features and require separate design/approval.

## 11. Schema 15 persistence

Migration 15 adds durable normalized facts for at least:

- escalation jobs;
- escalation attempts/reservations;
- sanitized request-package identity;
- approved cost envelope and usage/cost observations;
- provider result identity and validation outcome;
- learning ledger events / feedback facts.

Large sanitized packages and provider response artifacts remain managed files with SHA-256 identity; SQLite stores metadata, state, digests and bounded structured facts rather than large blobs.

Migrations 1–14 remain unchanged and are applied sequentially before Migration 15.

## 12. API boundary

Mac Core adds authenticated APIs for:

- create/list/get/reconcile Escalation Jobs from eligible existing source facts;
- read sanitized Handoff/package metadata;
- read immutable budget/envelope and usage facts;
- Worker claim/heartbeat/reserve/bind/failure/validation operations;
- record bounded human feedback / learning events;
- query learning facts by trusted project/task identity.

User-facing create/reconcile requests must not accept arbitrary `prompt`, `endpoint`, `url`, `model`, `api_key`, `provider_key`, `temperature`, `tools`, `command`, `shell`, `path`, or workflow JSON fields. Pydantic/contract models use `extra="forbid"` where applicable so these attempts fail at the API boundary.

Provider/Worker execution APIs remain distinct from user-facing APIs and require existing worker/authentication controls.

## 13. Windows UX

No new top-level navigation item.

Existing Business Automation / Approval / Results views gain a bounded Escalation section that shows:

- source task and quality reason;
- escalation state;
- provider profile display name/identity;
- approved maximum calls/tokens/cost;
- execution enabled/disabled readiness state;
- observed calls/tokens/cost after execution;
- manual Handoff availability;
- final Deep-AI validation outcome.

Windows allows explicit feedback actions `接受 / 拒绝 / 修改后采用` with bounded reason tags/notes. Feedback never triggers a new paid call by itself.

All record-only DataGrid bindings remain explicit `Mode=OneWay`. Real WPF `Measure/Arrange/UpdateLayout` coverage is required.

## 14. Security invariants

2.3.22.1 must preserve all earlier invariants and add:

- no paid provider request without exact accepted approval;
- no paid provider request while real-execution policy is disabled;
- API keys never stored in Core SQLite, packages, logs, Windows config, Return Packages or learning ledger;
- provider endpoint/model cannot be supplied by Work Package/model output/Windows user input;
- no provider tools/tool-calling authority;
- no shell/PowerShell/browser/Git/GitHub/ComfyUI authority for paid model output;
- no automatic cloud renderer/video API fallback;
- no automatic budget increase;
- at most two paid calls per escalation under one approved envelope;
- restart/reconcile must not duplicate a committed paid request/result;
- manual Handoff remains available without enabling API spend;
- no automatic main merge, tag or GitHub Release.

## 15. TDD and native verification

Implementation follows RED → GREEN for each contract group.

Required regression groups include:

1. Migration 15 and repository idempotency/state/write-once facts.
2. Eligibility: only durable `NEEDS_DEEP_AI` source facts can create Escalation Jobs.
3. Sanitizer: secret/path/raw-dataset leakage prevention and deterministic digest.
4. Exact approval-envelope binding and expiry/rejection convergence.
5. Execution-disabled invariant: zero provider requests even with an API key present.
6. Closed provider profile: producer/user/model cannot select endpoint/model/tools.
7. Attempt reservation before provider call and restart-safe no-duplicate-spend behavior.
8. Budget/call/token enforcement before every provider call.
9. Structural repair is capped at one additional paid call.
10. Provider result validation and source provenance binding.
11. Quality Learning ledger append/query/idempotency and no autonomous policy mutation.
12. Strict user-facing API extra-field rejection.
13. Windows REST contracts, read-only bindings and real WPF layout smoke.
14. Release rollup: product `2.3.22.1`, schema `15`, cumulative 18/19/20/21 capabilities retained.

Final candidate must pass exact-head native gates:

- Mac Core native CI;
- Mac Worker native CI;
- Windows Control Center native WPF CI;
- Windows Prebuilt release lifecycle CI.

The final delivery must contain prebuilt Mac Core, Mac Worker and Windows packages, SHA-256 sidecars/unified list, package-level independent verification, and a cumulative real-machine acceptance checklist. User machines must not compile source.

## 16. Explicit non-goals for 2.3.22.1

- enabling a real paid provider automatically on install;
- performing any real paid API call in CI or package verification;
- arbitrary provider/plugin marketplace;
- provider-selected tools or function calling;
- paid image/video generation or cloud-renderer fallback;
- autonomous prompt/model/provider/budget optimization;
- model fine-tuning or training-data generation;
- automated publication;
- automatic main merge/tag/GitHub Release.

## 17. Release state

2.3.22.1 will be developed as a stacked Draft PR based directly on the frozen 2.3.21.1 source head. It remains Draft/Open/Unmerged through CI/package freeze and later cumulative real-machine acceptance. No main merge, tag, or GitHub Release is part of this implementation task.
