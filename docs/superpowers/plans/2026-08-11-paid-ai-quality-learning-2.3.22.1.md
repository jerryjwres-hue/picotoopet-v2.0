# PicotooPet 2.3.22.1 Paid-AI Escalation + Quality Learning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an approval-gated, API-first Deep-AI escalation plane with real paid execution disabled by default, plus an append-only Quality Learning ledger, while preserving all cumulative 18/19/20/21 behavior.

**Architecture:** Mac Core remains the durable authority and stores no provider secret. A new `deep_ai` domain owns schema-15 escalation jobs, immutable sanitized request packages, approval-bound cost envelopes, attempt reservations, provider-result validation, and learning facts. Mac Worker alone owns trusted provider credentials/adapters; Windows only displays state/budgets, invokes exact approval flows, and records bounded feedback inside existing Business Automation/Approval/Results surfaces.

**Tech Stack:** Python 3.12, SQLite, Pydantic/FastAPI, existing PicotooPet queue/approval services, .NET 10 WPF, GitHub Actions native macOS/Windows release pipelines.

## Global Constraints

- Product version is exactly `2.3.22.1`; database schema target is exactly `15`.
- Base is exact 2.3.21.1 source head `c4ccdf26e85381c354d01aa51a45c5c93ae72610`.
- Real paid-provider execution is disabled by default and CI/package verification must make zero paid network calls.
- Core never stores provider API keys; Windows never receives provider secrets.
- A paid escalation can originate only from an existing durable `NEEDS_DEEP_AI` semantic/reasoning fact.
- Provider profile is selected by trusted escalation policy and frozen at prepare time; Work Package/model output/Windows/API caller cannot override provider/model/endpoint/tools.
- One primary paid call plus at most one structural repair call, both inside one approval-bound total budget.
- No automatic budget increase, provider switching, tool calling, shell/browser/Git/GitHub/ComfyUI authority, cloud-renderer fallback, publication, main merge, tag, or GitHub Release.
- Migrations 1–14 remain unchanged and sequentially precede Migration 15.
- User machines consume prebuilt artifacts only and never compile source.

---

### Task 1: Schema 15 durable escalation and learning facts

**Files:**
- Create: `src/picotoopet_core/db/migration_015.py`
- Modify: `src/picotoopet_core/db/database.py`
- Create: `src/picotoopet_core/deep_ai/__init__.py`
- Create: `src/picotoopet_core/deep_ai/models.py`
- Create: `src/picotoopet_core/deep_ai/repository.py`
- Test: `tests/deep_ai/test_deep_ai_repository.py`
- Modify current-schema assertions in existing migration/version tests only after RED proves they are old baselines.

**Interfaces:**
- Produces `DeepAiEscalationStatus`, `DeepAiValidationOutcome`, `DeepAiEscalationRecord`, `DeepAiAttemptRecord`, `DeepAiLearningEvent`, and `DeepAiRepository`.
- Repository provides idempotent `prepare_job(...)`, `get/list`, write-once package/provider/approval identities, attempt reservation/binding, usage accumulation, terminal state update, and append/query learning facts.

- [ ] **Step 1: Write RED repository/schema tests** that require schema 15, idempotent job creation by `(source_kind, source_id, source_digest, policy_version)`, write-once immutable execution identities, and append-only learning events.
- [ ] **Step 2: Run native Mac Core/full Python regression** and require failure only because Migration 15 / `deep_ai` objects do not exist.
- [ ] **Step 3: Implement Migration 15** with normalized tables for escalation jobs, attempts, immutable package/envelope metadata, provider result/usage facts, and learning events. Use managed-file relpaths/digests instead of large SQLite BLOBs.
- [ ] **Step 4: Register Migration 15 after 14** in `Database.apply_migrations()` without altering migrations 1–14.
- [ ] **Step 5: Implement models/repository minimally** so duplicate prepare returns one job; provider profile/package digest/approval identity cannot be rebound to different values; attempts are unique per `(job_id, attempt_number)`; usage/cost cannot decrease.
- [ ] **Step 6: Run focused + full regression and lint**; update only genuine current-schema assertions from 14 to 15.
- [ ] **Step 7: Commit as one GREEN batch.**

### Task 2: Sanitized package, trusted policy, exact approval, and zero-spend readiness

**Files:**
- Create: `src/picotoopet_core/deep_ai/policy.py`
- Create: `src/picotoopet_core/deep_ai/sanitizer.py`
- Create: `src/picotoopet_core/deep_ai/store.py`
- Create: `src/picotoopet_core/deep_ai/service.py`
- Modify: `src/picotoopet_core/services.py`
- Test: `tests/deep_ai/test_sanitizer.py`
- Test: `tests/deep_ai/test_escalation_service.py`

**Interfaces:**
- `EscalationPolicy` maps eligible source class/profile to a fixed `provider_profile_id` and immutable default cost envelope.
- `DeepAiEscalationService.prepare_from_source(...)` derives eligibility from Core facts; caller supplies source identity only, never prompt/provider/model/endpoint.
- `DeepAiSanitizedPackageStore` writes immutable managed JSON/package bytes and returns SHA-256 identity.

- [ ] **Step 1: Write RED tests** for eligibility-only `NEEDS_DEEP_AI`, deterministic sanitizer digest, secret/path/raw-dataset exclusion, trusted provider-profile mapping, exact approval binding, approval rejection/expiry convergence, and execution-disabled non-spending readiness.
- [ ] **Step 2: Confirm RED** is isolated to missing policy/sanitizer/service behavior.
- [ ] **Step 3: Implement sanitizer** that constructs context only from trusted Business/Creative records, bounded evidence snippets, deterministic quality reasons, source-controlled instruction template, fixed return schema, sanitizer version, and provenance digests. Explicitly reject/strip secrets, absolute paths, auth material, arbitrary URLs/tool definitions, and unrelated raw archives.
- [ ] **Step 4: Implement trusted policy** with closed 22.1 provider profile identifiers and a default `execution_enabled=False`; freeze provider-profile digest and max calls/input/output/cost at job preparation.
- [ ] **Step 5: Reuse existing approval service** to create a dedicated exact approval whose digest covers source/package/provider/model/token/call/cost/expiry/policy fields. Any mismatch prevents readiness.
- [ ] **Step 6: Implement readiness reconciliation** where Accepted approval alone yields `Approved`; `ProviderReady` additionally requires trusted provider profile, explicit execution-enabled configuration, Worker capability/secret readiness and budget preflight. Disabled/absent provider stays non-spending and leaves manual Handoff available.
- [ ] **Step 7: Run focused/full regression + lint and commit GREEN.**

### Task 3: Closed Mac Worker provider executor and duplicate-spend prevention

**Files:**
- Create: `src/picotoopet_core/deep_ai/provider.py`
- Create: `src/picotoopet_core/deep_ai/execution.py`
- Modify: `src/picotoopet_core/worker/handlers.py`
- Modify: `src/picotoopet_core/worker/runtime.py` and/or Worker registration surface only where required by existing pattern.
- Modify trusted Worker config models/loader only for provider secret/profile configuration; never Core SQLite.
- Test: `tests/deep_ai/test_provider_execution.py`
- Test: `tests/worker/test_deep_ai_worker.py`

**Interfaces:**
- `PaidAiProviderAdapter` accepts the frozen sanitized package plus reserved attempt identity and returns `ProviderResponse` containing provider request ID, result bytes/JSON, input/output tokens, pricing provenance, and cost.
- `DeepAiExecutionCoordinator` performs claim → reserve → provider submit/reconcile → bind result.

- [ ] **Step 1: Write RED tests with a fake local provider** proving zero calls when disabled, reserve-before-submit ordering, at-most-two total calls, shared total budget, structural-repair-only second call, restart after committed response causes zero duplicate call, and ambiguous transport without provider reconciliation converges `NeedsHuman` rather than spending again.
- [ ] **Step 2: Confirm RED** without any real external provider/network dependency.
- [ ] **Step 3: Implement closed adapter interface and fake/test adapter.** Production profile config supplies endpoint/model/key from Worker-owned trusted settings; request does not accept arbitrary tools/URL/model/temperature.
- [ ] **Step 4: Implement attempt reservation protocol**: Core reservation before submit; bind provider request/result/usage to same reservation; read durable attempt before any retry.
- [ ] **Step 5: Enforce budget preflight before every call** using approved max calls/tokens/cost and trusted pricing metadata. A call that cannot fit is never sent.
- [ ] **Step 6: Implement one bounded structural repair path** only after deterministic schema failure; semantic failure does not loop.
- [ ] **Step 7: Register Worker capability only when trusted paid-AI provider configuration is present and explicitly enabled. Default installation therefore exposes no paid execution capability.
- [ ] **Step 8: Run Worker/full regression/lint and commit GREEN.**

### Task 4: Deterministic validation, source-stage continuation, and Quality Learning ledger

**Files:**
- Create: `src/picotoopet_core/deep_ai/validation.py`
- Create: `src/picotoopet_core/deep_ai/learning.py`
- Modify: `src/picotoopet_core/deep_ai/service.py`
- Modify originating Business/Creative continuation glue only at explicit `NEEDS_DEEP_AI` resumption seam; do not rewrite stage logic.
- Test: `tests/deep_ai/test_validation.py`
- Test: `tests/deep_ai/test_learning.py`
- Test: `tests/deep_ai/test_source_continuation.py`

**Interfaces:**
- Validation outcomes are exactly `PASS`, `NEEDS_HUMAN`, `REJECT`.
- Learning writer records immutable observation/event facts and explicit human feedback `Accepted | Rejected | Modified | NoDecision`.

- [ ] **Step 1: Write RED tests** for schema/bounds/provenance/evidence-reference validation, forbidden authority in output, PASS-only source continuation, and append/query/idempotent learning facts.
- [ ] **Step 2: Implement deterministic validator** and accepted-result managed artifact with digest/source binding.
- [ ] **Step 3: Continue originating Business/Creative stage only from validated PASS**; NeedsHuman/Reject remain terminal for the escalation and do not silently rewrite source facts.
- [ ] **Step 4: Implement learning ledger writer/query** capturing local stage/profile/model/template/attempts/outcome/reasons, escalation/provider/model, sanitized input/output digests, usage/cost, human action/reason tags/final-content digest and downstream artifact refs.
- [ ] **Step 5: Add explicit assertions that learning facts cannot mutate prompt/provider/model/budget, retrain, republish, or trigger a new paid call.
- [ ] **Step 6: Run full regression/lint and commit GREEN.**

### Task 5: Strict Core API and Windows bounded UX

**Files:**
- Create: `src/picotoopet_core/api/routes/deep_ai.py`
- Modify: `src/picotoopet_core/api/app.py`
- Modify: `src/picotoopet_core/services.py`
- Test: `tests/integration/api/test_deep_ai_api.py`
- Create: `windows/desktop/src/PicotooPet.Desktop.Core/Contracts/DeepAiContracts.cs`
- Create: `windows/desktop/src/PicotooPet.Desktop.Core/Networking/MacCoreClient.DeepAi.cs`
- Create: `windows/desktop/src/PicotooPet.Desktop/Services/ControlCenterSession.DeepAi.cs`
- Create: `windows/desktop/src/PicotooPet.Desktop/ViewModels/DeepAiEscalationPanelViewModel.cs`
- Create: `windows/desktop/src/PicotooPet.Desktop/Views/DeepAiEscalationPanel.xaml`
- Create: `windows/desktop/src/PicotooPet.Desktop/Views/DeepAiEscalationPanel.xaml.cs`
- Modify: existing Business Automation page/view model to embed panel; no Shell navigation change.
- Test: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/DeepAiClientSmokeTests.cs`
- Test: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/DeepAiEscalationPanelWpfSmokeTests.cs`
- Modify: smoke-test `Program.cs`.

**Interfaces:**
- User-facing create accepts only trusted source identity/idempotency inputs needed to locate an eligible fact.
- Forbidden extras include `prompt`, `endpoint`, `url`, `model`, `api_key`, `provider_key`, `temperature`, `tools`, `command`, `shell`, `path`, `workflow`.
- Windows shows immutable state/budget/usage/manual-Handoff/result and bounded feedback; it never edits provider/model/endpoint/key.

- [ ] **Step 1: Write Core API RED** for create/list/get/reconcile, budget/usage read, manual Handoff metadata, bounded feedback, worker claim/reserve/bind operations, authentication, and 422 rejection of execution-injection fields.
- [ ] **Step 2: Implement strict FastAPI routes and app wiring** with separate Worker execution endpoints and user-facing endpoints.
- [ ] **Step 3: Write Windows RED smoke** for fixed paths/contracts, no execution configuration properties, record bindings explicitly OneWay, and real `Measure/Arrange/UpdateLayout`.
- [ ] **Step 4: Implement REST client/session/view model/panel** embedded under existing Business Automation/Approval/Results surfaces. `执行未启用` must be a first-class visible readiness state; feedback actions never trigger paid execution.
- [ ] **Step 5: Run Windows native .NET/WPF smoke with warnings-as-errors and published self-test; fix only concrete analyzer/WPF defects.
- [ ] **Step 6: Commit GREEN.**

### Task 6: Product 2.3.22.1 / schema 15 release freeze and cumulative verification

**Files:**
- Modify: `src/picotoopet_core/product-version.txt`
- Modify current product-version tests/contracts and `contracts/release/project-goal-invariants.json`.
- Add: `tests/contract/test_paid_ai_quality_learning_23221_contract.py`
- Modify Windows product-version smoke/goal-integrity surfaces only where current version is asserted.
- Update PR body after exact-head verification; do not merge.

**Interfaces:**
- Release contract proves cumulative 18.1/19.1/20.1/21.1 abilities remain present plus 22.1 schema/provider/learning boundaries.

- [ ] **Step 1: Write release RED** requiring `2.3.22.1`, schema 15, `deep_ai` modules/API, execution-disabled default, closed provider controls, learning ledger, Windows WPF smoke entry, and retained Business/Creative/Production/Pipeline capabilities.
- [ ] **Step 2: Run RED** and confirm failures are only old product/schema surfaces or missing 22.1 rollup declarations.
- [ ] **Step 3: Advance canonical current-version surfaces once** to 2.3.22.1 / schema 15 while preserving historical feature schema numbers.
- [ ] **Step 4: Run exact-head four native gates:** Mac Core, Mac Worker, Windows Control Center, Windows Prebuilt Release. CI queue/running state does not block independent work; only exact-head concrete failures trigger fixes.
- [ ] **Step 5: Windows Prebuilt must pass** release contracts, exact .NET SDK gate, legacy Task Center regression, real WPF smoke, warnings-as-errors, published self-test, installer goal-integrity and packaged install/upgrade/recovery/rollback on Windows PowerShell 5.1.
- [ ] **Step 6: Download final Mac Core, Mac Worker and Windows artifacts; independently verify wrapper digest, formal package SHA-256, archive traversal/duplicates/links, manifest file size/hash, Mac arm64, Windows AMD64, product version 2.3.22.1, schema 15 and cumulative wheel contents.
- [ ] **Step 7: Generate unified SHA list, delivery manifest, independent verification JSON and cumulative Chinese real-machine acceptance checklist.
- [ ] **Step 8: Update Draft PR with exact source/build identities, four CI run IDs, package filenames/SHA and `CI_PACKAGE_PASS_REAL_MACHINE_PENDING`; keep Draft/Open/Unmerged. No main merge/tag/GitHub Release.
