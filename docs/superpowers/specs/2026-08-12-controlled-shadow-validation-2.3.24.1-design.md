# PicotooPet 2.3.24.1 — Controlled Shadow / A-B Validation Design

Date: 2026-08-12
Target product version: `2.3.24.1`
Target database schema: `17`
Base: PicotooPet `2.3.23.1` frozen feature head `4a19528868b835a8b214f0aff11e7215b31f97d3`

## 1. Goal

Turn a human-reviewed `AcceptedForShadow` 2.3.23.1 Improvement Candidate into a deterministic, offline, restart-safe shadow validation run that tests whether the candidate signal reproduces across two immutable holdout arms.

The cumulative learning chain becomes:

`Quality Learning Facts → Evaluation Snapshot → Offline Evaluation → Improvement Candidate → AcceptedForShadow → Controlled Shadow Run → Shadow Report → shadow_review_ready`

2.3.24.1 does not change runtime prompts, models, providers, endpoints, budgets, workflows, publication state, or paid-execution policy. It does not automatically promote a candidate.

## 2. Architecture boundary

### 2.1 Mac Core

Mac Core remains the durable authority and owns:

- eligibility checks for `AcceptedForShadow` candidates;
- immutable shadow-run identity and input digest;
- deterministic sample partitioning under `quality.shadow.v1`;
- per-arm metric facts, comparison deltas, verdict, and report digest;
- append-only shadow review facts;
- schema 17 persistence and restart-safe reconciliation;
- authenticated APIs consumed by Windows.

### 2.2 Mac Worker

Mac Worker gains no new execution role. Shadow validation performs zero local-model calls, zero paid-provider calls, zero ComfyUI calls, zero shell/browser/Git/GitHub actions, and zero publication actions.

### 2.3 Windows

Windows extends the existing Business Automation `质量评估` area with bounded shadow controls. It may:

- start a shadow validation for the currently selected `AcceptedForShadow` candidate;
- refresh the run and per-arm comparison facts;
- record one bounded human review action.

It cannot supply arbitrary prompt text, model IDs, endpoints, provider keys, API keys, budgets, temperature, tools, commands, paths, workflow JSON, SQL, formulas, split rules, thresholds, or scoring expressions.

No new top-level navigation route is added.

## 3. Eligibility

A shadow run may be created only when all of the following are true:

1. the candidate exists and has status exactly `AcceptedForShadow`;
2. its source Evaluation Run exists and is `Completed`;
3. its source Evaluation Snapshot exists and matches the candidate's immutable references;
4. candidate/snapshot/run digests are valid frozen identities;
5. no different shadow run already exists for the same candidate.

A terminal or non-accepted candidate is never made eligible by history/read APIs.

## 4. Frozen profile and split

The only profile is:

- `shadow_profile_id = quality.shadow.v1`
- `split_version = quality.shadow.split.v1`

The run uses the immutable source snapshot members only.

Each logical evaluation sample is assigned deterministically to one arm by:

`sha256(split_version + candidate_digest + sample_key)`

- even low bit → `baseline`
- odd low bit → `shadow`

The split is deterministic, source-controlled, and not caller-configurable. Reconcile must produce the same membership and result digest.

## 5. What A/B means in 2.3.24.1

2.3.23.1 candidates are review signals, not executable policy patches. Therefore 2.3.24.1 does **not** pretend that a replacement prompt/model/provider exists.

Instead, A/B validation tests whether the candidate's triggering quality signal is reproducible across two independent deterministic holdout arms from the same immutable snapshot.

For each arm Core recomputes only the fixed metrics needed by that candidate class using the 2.3.23.1 frozen semantics.

### Candidate rules reused unchanged

- `PROMPT_REVIEW`: human decisions >= 5 and `(Rejected + Modified) / HumanDecisions >= 0.35`.
- `LOCAL_REASONING_REVIEW`: human decisions >= 5, local `NEEDS_DEEP_AI` rate >= 0.30, paid `PASS` count >= 3, paid `PASS` rate >= 0.70.
- `EVIDENCE_SELECTION_REVIEW`: human decisions >= 5, evidence-related feedback count >= 3, evidence-related feedback rate >= 0.25.
- `PAID_ESCALATION_REVIEW`: paid validation count >= 5 and paid `NEEDS_HUMAN + REJECT` rate >= 0.30.
- `COST_POLICY_REVIEW`: paid validated `PASS` count >= 5 and cost per paid validated `PASS` >= `$0.30`.

No threshold is caller-editable.

## 6. Verdict

Canonical verdicts:

- `Supported`: the frozen candidate rule is satisfied independently in both arms.
- `NeedsMoreData`: either arm lacks the frozen minimum denominator/sample requirement.
- `NotReproduced`: both arms have enough data but the rule fails in at least one arm.

The verdict is evidence only. It does not change the Improvement Candidate status or any runtime policy.

## 7. Schema 17 persistence

Migration 17 adds normalized durable facts for at least:

- `quality_shadow_runs`;
- `quality_shadow_arm_metrics`;
- `quality_shadow_reviews`.

A shadow run stores candidate/source identities and digests, profile/split versions, status, verdict, input/report digests, and timestamps.

Arm metrics store only bounded structured values, numerators/denominators, availability, and arm identity.

Reviews store append-only action facts and digests.

No raw provider secret, API key, unrestricted prompt/body, arbitrary path, raw dataset, binary artifact, workflow JSON, or shell command is copied into schema 17.

Migrations 1–16 remain unchanged and apply sequentially before Migration 17.

## 8. Run lifecycle and reconciliation

Canonical run status:

- `Completed`

The deterministic run is materialized transactionally enough to support an interruption window. Reconcile always re-derives missing arm metrics/report facts under the same `shadow_run_id`; it never creates a second run for the same candidate.

Running or reconciling a shadow experiment must not:

- change the candidate status;
- reopen a terminal Deep-AI escalation;
- create or reserve a paid attempt;
- change Provider/Model/Endpoint/Prompt/Budget policy;
- execute local AI or ComfyUI;
- publish, push, merge, tag, or release.

## 9. Human shadow review

Allowed actions are closed to:

- `Reviewed`
- `AcceptedForPromotionReview`
- `Rejected`
- `Cancelled`

Review is append-only and idempotent by `idempotency_key`.

`AcceptedForPromotionReview` is terminal for 2.3.24.1 and is only an auditable review fact. It performs no policy promotion, no runtime mutation, no paid call, no publication, and no Git operation.

## 10. API boundary

Mac Core adds authenticated APIs for:

- create/list/get Shadow Runs;
- reconcile one Shadow Run;
- list arm metrics/comparison facts;
- record bounded Shadow Review actions.

Create accepts only `candidate_id`. Reconcile accepts an empty body. Review accepts only the closed action enum and an idempotency key.

Strict user-facing request models use `extra="forbid"` and reject fields including `prompt`, `model`, `endpoint`, `api_key`, `provider_key`, `budget`, `temperature`, `tools`, `command`, `shell`, `path`, `workflow`, `sql`, `formula`, `threshold`, `split`, and `seed`.

## 11. Windows UX

The existing `质量评估` panel gains a `影子验证` subsection with:

- selected candidate eligibility/readiness;
- `运行影子验证` button;
- run status and verdict;
- baseline/shadow sample/trigger metric summary;
- bounded review buttons;
- refresh support.

All record-only WPF bindings are explicit `Mode=OneWay`. Real STA `Measure/Arrange/UpdateLayout` coverage is required.

## 12. Security invariants

2.3.24.1 preserves every 2.3.23.1 invariant and adds:

- only `AcceptedForShadow` candidates can create a run;
- immutable snapshot members are the only input;
- split/profile/thresholds are source-controlled and caller-invariant;
- history visibility never reactivates a candidate or Deep-AI escalation;
- shadow execution makes zero model/provider/ComfyUI/publication calls;
- no runtime policy mutation or automatic promotion;
- no arbitrary executable configuration enters schema 17 or APIs;
- restart/reconcile never duplicates runs or spend;
- no automatic main merge, tag, or GitHub Release.

## 13. TDD and native verification

Required regression groups:

1. Migration 17 applies after Migration 16 and preserves schema 1–16.
2. Only `AcceptedForShadow` candidates are eligible.
3. Create is idempotent on candidate identity and immutable source digests.
4. Deterministic split is stable across restart/reconcile.
5. Both arm metrics preserve explicit denominator and missing-data semantics.
6. All five candidate classes reuse exactly the frozen 2.3.23.1 thresholds.
7. Verdict is `Supported`, `NeedsMoreData`, or `NotReproduced` only under the defined rules.
8. Shadow run/reconcile writes zero paid attempts and does not mutate Deep-AI/candidate execution state.
9. Shadow review is append-only/idempotent and `AcceptedForPromotionReview` is fact-only.
10. Strict API extra-field rejection.
11. Windows REST contracts, bounded controls, `Mode=OneWay`, and real STA WPF layout smoke.
12. Release rollup: product `2.3.24.1`, schema `17`, cumulative 18–23 capabilities retained.

Final exact-head native gates:

- Mac Core native CI;
- Mac Worker native CI;
- Windows Control Center native WPF CI;
- Windows Prebuilt release lifecycle CI.

Delivery must contain prebuilt Mac Core, Mac Worker, and Windows packages; SHA-256 evidence; independent package verification; and cumulative real-machine acceptance instructions. User machines must not compile source.

## 14. Explicit non-goals

2.3.24.1 does not include:

- replacement prompt authoring;
- local or paid model shadow execution;
- provider/model/endpoint/budget selection;
- automatic policy mutation;
- automatic policy promotion;
- fine-tuning/training;
- paid execution caused by shadow validation;
- ComfyUI/cloud-renderer execution caused by shadow validation;
- automatic publication;
- automatic main merge/tag/GitHub Release.

## 15. Release state

2.3.24.1 is developed as a stacked Draft PR directly on frozen 2.3.23.1 head `4a19528868b835a8b214f0aff11e7215b31f97d3`.

Feature branch: `feature/controlled-shadow-validation-2.3.24.1`.

It remains Draft/Open/Unmerged through CI/package freeze and later cumulative real-machine acceptance.