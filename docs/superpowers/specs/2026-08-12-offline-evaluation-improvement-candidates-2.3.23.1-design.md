# PicotooPet 2.3.23.1 — Offline Evaluation + Improvement Candidates Design

Date: 2026-08-12
Target product version: `2.3.23.1`
Target database schema: `16`
Base: PicotooPet `2.3.22.1` frozen feature head `f018aa538253b12a72dca859981c37c8bd7bd685`

## 1. Goal

Turn the append-only Quality Learning facts introduced in 2.3.22.1 into a deterministic, auditable offline quality-evaluation layer that can create bounded Improvement Candidates without changing any runtime prompt, model, provider, endpoint, budget, workflow, publication state, or execution policy.

The cumulative learning chain becomes:

`Quality Learning Facts → Evaluation Dataset Snapshot v1 → Offline Evaluation v1 → Evaluation Report v1 → Improvement Candidate v1 → candidate_ready`

2.3.23.1 stops at `candidate_ready`. It does not perform Shadow/A-B execution and does not promote any candidate into production policy.

## 2. Architecture boundary

### 2.1 Mac Core

Mac Core remains the durable authority and owns:

- immutable Evaluation Dataset Snapshot identity and digest;
- selected learning-event identities and exact cohort definition;
- deterministic Evaluation Run identity and result digest;
- metric/cohort facts and evaluation reason codes;
- Improvement Candidate identity, evidence links, status, and review facts;
- authenticated APIs consumed by Windows;
- schema 16 persistence and restart-safe idempotency.

Core never applies an Improvement Candidate to production configuration.

### 2.2 Mac Worker

Mac Worker has no new autonomous model-execution role in 2.3.23.1. Offline evaluation is deterministic and runs in Core. The Worker must not use local or paid models to invent a candidate payload, rewrite prompts, select a new provider, or change budgets.

### 2.3 Windows

Windows extends the existing Business Automation / Quality surfaces with a bounded Quality Evaluation panel. It may:

- create a project-scoped evaluation snapshot from trusted existing learning facts;
- start/reconcile deterministic evaluation;
- display immutable metrics and reason codes;
- list Improvement Candidates;
- mark a candidate `Reviewed`, `AcceptedForShadow`, `Rejected`, or `Cancelled` as a human review fact.

`AcceptedForShadow` is only a durable review decision. It does not activate, edit, or execute any runtime policy in 2.3.23.1.

Windows cannot submit arbitrary prompt text, model IDs, provider endpoints, provider keys, API keys, workflow JSON, shell commands, executable paths, or arbitrary metric expressions.

No new top-level navigation route is added.

## 3. Evaluation scope

An Evaluation Dataset Snapshot may be created only from durable Quality Learning facts already stored by Mac Core.

The v1 public create contract is closed to:

- one existing `project_id`;
- one trusted `evaluation_profile_id = quality.offline.v1`;
- optional bounded `stage_profile` filter chosen from known stored profile identities;
- optional bounded UTC start/end timestamps;
- fixed maximum of `10000` learning facts per snapshot.

The caller cannot inject raw source rows, SQL, arbitrary filters, scoring formulas, prompts, model output, URLs, or files.

Snapshot creation is idempotent on the canonical scope plus the ordered selected learning-event identities/digests. Once created, a snapshot is immutable.

## 4. Evaluation Dataset Snapshot v1

The snapshot contains only normalized references and bounded facts needed for evaluation:

- snapshot ID and schema/profile version;
- project ID;
- canonical scope definition;
- ordered learning-event IDs;
- source task/stage/profile/template/model/provider identities where present;
- local quality outcome and attempt count;
- paid escalation/validation outcome where present;
- human action (`Accepted`, `Rejected`, `Modified`, `NoDecision`);
- bounded reason tags;
- observed paid calls/tokens/cost where present;
- downstream artifact/return-package reference where present;
- source event digests;
- snapshot digest.

No raw provider secret, API key, local absolute path, unrestricted user content, large dataset, or binary artifact is copied into the snapshot.

## 5. Offline Evaluation v1

Evaluation is deterministic and source-controlled. `quality.offline.v1` computes only fixed metrics; callers cannot supply a formula.

Required global metrics:

- sample count;
- human decision count;
- accepted / rejected / modified / no-decision counts and rates;
- local `PASS / NEEDS_DEEP_AI / NEEDS_HUMAN / REJECT` counts and rates where available;
- mean and p95 local attempt count;
- paid escalation count;
- paid `PASS / NEEDS_HUMAN / REJECT` validation counts and rates;
- total paid calls, input tokens, output tokens, and USD cost;
- cost per paid validated `PASS` when denominator is non-zero;
- downstream completion-reference rate when downstream references exist.

Required cohorts are bounded to identities already stored in learning facts:

- stage profile;
- template version;
- local model identity;
- provider profile identity;
- paid model identity.

Cohorts with fewer than `5` human-decision samples are marked `insufficient_sample` and cannot independently trigger an Improvement Candidate.

All rates use explicit numerators/denominators. Missing data is represented as `null` / `not_available`, never silently coerced to zero.

## 6. Improvement Candidate v1

Improvement Candidates are deterministic review signals, not executable configuration patches.

Allowed candidate classes are closed to:

1. `PROMPT_REVIEW`
2. `LOCAL_REASONING_REVIEW`
3. `EVIDENCE_SELECTION_REVIEW`
4. `PAID_ESCALATION_REVIEW`
5. `COST_POLICY_REVIEW`

A candidate contains:

- candidate ID;
- project ID;
- evaluation run/snapshot IDs and digests;
- evaluation rule version;
- candidate class;
- affected trusted profile/template/model/provider identities already present in the evaluated cohort;
- triggering metric names, exact values, numerators, denominators, and thresholds;
- bounded reason codes;
- evidence cohort identity and digest;
- human review state and review timestamp;
- candidate digest.

A candidate does not contain a replacement prompt body, new model ID, new provider endpoint, API key, arbitrary budget number, shell command, workflow JSON, or executable patch.

## 7. Deterministic candidate rules

Rules are source-controlled under `quality.offline.v1` and require the minimum sample gate.

### Rule A — Prompt review

Create `PROMPT_REVIEW` for a cohort when:

- human-decision sample count >= `5`; and
- `(Rejected + Modified) / HumanDecisions >= 0.35`.

### Rule B — Local reasoning review

Create `LOCAL_REASONING_REVIEW` when:

- human-decision sample count >= `5`; and
- local `NEEDS_DEEP_AI` rate >= `0.30`; and
- paid validated `PASS` count >= `3`; and
- paid validated `PASS` rate >= `0.70`.

### Rule C — Evidence selection review

Create `EVIDENCE_SELECTION_REVIEW` when:

- human-decision sample count >= `5`; and
- at least `3` human feedback events carry a trusted evidence-related reason tag; and
- evidence-related feedback rate >= `0.25`.

Trusted evidence-related tags are source-controlled and closed to:

- `missing_evidence`
- `weak_evidence`
- `wrong_evidence`
- `insufficient_context`

### Rule D — Paid escalation review

Create `PAID_ESCALATION_REVIEW` when:

- paid validation sample count >= `5`; and
- paid `NEEDS_HUMAN + REJECT` rate >= `0.30`.

### Rule E — Cost policy review

Create `COST_POLICY_REVIEW` when:

- paid validated `PASS` count >= `5`; and
- cost per paid validated `PASS` >= `$0.30`.

Candidate generation is idempotent on `(evaluation_run_id, rule_version, candidate_class, cohort_digest)`.

## 8. Candidate lifecycle

Canonical states:

- `Prepared`
- `Reviewed`
- `AcceptedForShadow`
- `Rejected`
- `Cancelled`

State transitions are append-only review facts. `AcceptedForShadow` is terminal for 2.3.23.1 and creates no runtime mutation.

Review actions must not:

- edit prompts/templates;
- edit model/provider/endpoint mappings;
- enable paid execution;
- raise or lower paid budgets;
- submit a provider request;
- execute ComfyUI;
- run shell/PowerShell/Git/GitHub commands;
- publish content;
- merge/tag/release.

## 9. Terminal-history rule inherited from 2.3.22.1

A completed/terminal Deep-AI escalation remains queryable for historical readiness, project/Handoff context, usage, feedback, and evaluation input. Historical queryability must never make a terminal escalation eligible again for initial paid escalation creation or provider execution.

Evaluation reads terminal history as immutable facts only. It cannot reopen or retry old paid work.

## 10. Schema 16 persistence

Migration 16 adds normalized durable facts for at least:

- evaluation dataset snapshots;
- snapshot member references;
- evaluation runs;
- evaluation metric/cohort facts;
- improvement candidates;
- candidate review facts.

Large raw source content remains outside SQLite. Schema 16 stores identities, bounded structured values, digests, statuses, and timestamps.

Migrations 1–15 remain unchanged and apply sequentially before Migration 16.

## 11. API boundary

Mac Core adds authenticated user-facing APIs for:

- create/list/get Evaluation Dataset Snapshots;
- create/list/get/reconcile Evaluation Runs;
- list/get Improvement Candidates;
- record bounded candidate review actions.

User-facing request models use `extra="forbid"` where applicable and reject fields including:

- `prompt`
- `prompt_template`
- `endpoint`
- `url`
- `model`
- `api_key`
- `provider_key`
- `budget`
- `temperature`
- `tools`
- `command`
- `shell`
- `path`
- `workflow`
- `sql`
- `formula`

## 12. Windows UX

The existing Business Automation area gains a `质量评估` subsection with:

- project-scoped snapshot creation;
- evaluation status and snapshot digest;
- metric summary;
- cohort summary;
- Improvement Candidate list;
- bounded candidate review actions.

All record-only WPF bindings are explicit `Mode=OneWay`. Real STA `Measure/Arrange/UpdateLayout` coverage is required.

## 13. Security invariants

2.3.23.1 must preserve every 2.3.22.1 invariant and add:

- learning facts cannot autonomously mutate production policy;
- evaluation cannot execute local or paid AI;
- evaluation cannot create a new paid escalation;
- candidate review cannot change runtime configuration;
- snapshot/candidate identities are immutable and digest-bound;
- no arbitrary scoring formula or SQL;
- no arbitrary file/data import into evaluation;
- no secrets copied into snapshots/reports/candidates;
- no terminal Deep-AI job can be reopened by evaluation;
- no automatic main merge, tag, or GitHub Release.

## 14. TDD and native verification

Implementation follows RED → GREEN.

Required regression groups:

1. Migration 16 applies after Migration 15 and preserves schema 1–15 behavior.
2. Snapshot scope is closed, project-scoped, bounded, immutable, and idempotent.
3. Snapshot contains normalized learning facts only and does not copy forbidden secrets/paths/raw payloads.
4. Evaluation metrics use explicit denominators and preserve missing-data semantics.
5. Cohort minimum-sample rules prevent small cohorts from triggering candidates.
6. All five deterministic candidate rules trigger only at frozen thresholds.
7. Candidate generation and review are idempotent and append-only.
8. `AcceptedForShadow` performs zero runtime policy mutation and zero local/paid model calls.
9. Terminal Deep-AI history is queryable but never re-eligible for paid execution.
10. Strict user-facing API extra-field rejection.
11. Windows REST contracts, `Mode=OneWay`, and real STA WPF layout smoke.
12. Release rollup: product `2.3.23.1`, schema `16`, cumulative 18/19/20/21/22 capabilities retained.

Final exact-head native gates:

- Mac Core native CI;
- Mac Worker native CI;
- Windows Control Center native WPF CI;
- Windows Prebuilt release lifecycle CI.

Delivery must contain prebuilt Mac Core, Mac Worker, and Windows packages; SHA-256 evidence; independent package verification; and cumulative real-machine acceptance instructions. User machines must not compile source.

## 15. Explicit non-goals

2.3.23.1 does not include:

- candidate-authored replacement prompt text;
- automatic prompt editing;
- automatic model/provider/endpoint selection;
- automatic budget changes;
- Shadow/A-B execution;
- policy promotion;
- fine-tuning or training-data generation;
- paid execution caused by evaluation;
- ComfyUI/cloud-renderer execution caused by evaluation;
- automatic publication;
- automatic main merge/tag/GitHub Release.

## 16. Release state

2.3.23.1 is developed as a stacked Draft PR directly on frozen 2.3.22.1 head `f018aa538253b12a72dca859981c37c8bd7bd685`.

The feature branch is `feature/offline-evaluation-improvement-candidates-2.3.23.1`.

It remains Draft/Open/Unmerged through CI/package freeze and later cumulative real-machine acceptance. No main merge, tag, GitHub Release, real paid-AI request, or automatic policy mutation is part of this version.
