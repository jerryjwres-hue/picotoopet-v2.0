# Phase 10A Handoff Preparation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver product version `2.3.10.1` with deterministic Handoff preparation, safe preview, digest-bound approval, and a native WPF Phase 10A workflow without invoking any Provider.

**Architecture:** Mac Core remains the fact source and stores prepared Handoffs in SQLite. A focused HandoffService resolves a single built-in template, normalizes user input, creates deterministic digests, exposes bounded REST contracts, and binds an existing Approval record. Windows uses typed API contracts and a native WPF page to prepare, preview, list, and submit Handoffs; Provider execution remains unavailable.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, SQLite, pytest, JSON Schema, .NET 10, WPF, C#, Windows PowerShell 5.1, GitHub Actions.

## Global Constraints

- Product version is exactly `2.3.10.1`.
- Base product version `2.3.9.1` remains independently installable and rollback-safe.
- PRs remain Draft; do not merge `main`.
- Mac Core + SQLite is the Handoff and approval fact source.
- Windows is a native WPF client only.
- No Provider installation, authentication, invocation, upload, Dev Broker, shell command, real worktree, push, merge, tag, or release.
- No arbitrary repository, path, command, test command, secret, token, environment variable, or manifest field input.
- Protected originals never enter Handoff data, preview, approval scope, logs, fixtures, or responses.
- User machines receive prebuilt packages and do not compile source.

---

## File Structure

### Create

- `src/picotoopet_core/handoffs/__init__.py` — public Handoff package exports.
- `src/picotoopet_core/handoffs/models.py` — strict template, request, record, preview, and status models.
- `src/picotoopet_core/handoffs/service.py` — deterministic normalization, digest creation, persistence, idempotency, and approval reconciliation.
- `src/picotoopet_core/api/routes/handoffs.py` — bounded authenticated REST routes.
- `contracts/handoff/v1/schemas/handoff_draft.schema.json` — Phase 10A pre-approval contract.
- `tests/unit/handoffs/test_handoff_service.py` — normalization and digest tests.
- `tests/integration/api/test_handoff_preparation_api.py` — prepare/list/get/submit/approval API tests.
- `tests/security/test_handoff_preparation_security.py` — Protected, traversal, secret, main, and response-boundary tests.
- `windows/desktop/src/PicotooPet.Desktop/Services/ControlCenterSession.Handoffs.cs` — typed session operations.
- `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/HandoffPreparationSmokeTests.cs` — typed workflow smoke tests.
- `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/HandoffPreparationPageWpfLayoutSmokeTests.cs` — real STA WPF layout and binding tests.

### Modify

- `src/picotoopet_core/db/schema.py` — migration 3 and handoffs table.
- `src/picotoopet_core/db/database.py` — apply migration 3 idempotently.
- `src/picotoopet_core/approvals/service.py` — taskless resource approvals and Handoff-safe summary fields.
- `src/picotoopet_core/services.py` — construct and expose HandoffService.
- `src/picotoopet_core/api/app.py` — register Handoff routes.
- `src/picotoopet_core/product-version.txt` — `2.3.10.1`.
- `scripts/export_slice_d_openapi.py` — include the new API automatically through the app schema.
- `tests/unit/db/test_migrations.py` — migration count, columns, idempotency, and partial state.
- `tests/integration/approvals/test_control_center_approval.py` — taskless approval behavior.
- `tests/contract/test_phase23_diagnostic_contract.py` — preserve existing API contract assumptions.
- `windows/desktop/src/PicotooPet.Desktop.Core/Contracts/ApiContracts.cs` — typed Handoff contracts.
- `windows/desktop/src/PicotooPet.Desktop.Core/Networking/MacCoreClient.cs` — bounded Handoff REST operations.
- `windows/desktop/src/PicotooPet.Desktop/ViewModels/CloudDevelopmentPageViewModel.cs` — Phase 10A state, commands, preview, and recent Handoffs.
- `windows/desktop/src/PicotooPet.Desktop/Views/Pages/CloudDevelopmentPage.xaml` — native preparation and preview UI.
- `windows/desktop/src/PicotooPet.Desktop/ViewModels/ShellViewModel.cs` — construct the page with the live session.
- `windows/desktop/src/PicotooPet.Desktop/Services/AppSelfTest.cs` — assert Phase 10A available while ProviderConfigured remains false.
- `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/Program.cs` — run new smoke tests.
- `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/CloudDevelopmentSmokeTests.cs` — update frozen milestone expectations.
- `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/CloudDevelopmentPageWpfLayoutSmokeTests.cs` — retain no-WebView and layout gates while permitting bounded buttons.
- release/version assertions and package labels that represent the current formal release.

---

### Task 1: Freeze the Phase 10A contracts with RED tests

**Files:**
- Create: `contracts/handoff/v1/schemas/handoff_draft.schema.json`
- Create: `tests/unit/handoffs/test_handoff_service.py`
- Create: `tests/integration/api/test_handoff_preparation_api.py`
- Create: `tests/security/test_handoff_preparation_security.py`
- Modify: `tests/unit/db/test_migrations.py`
- Modify: `tests/integration/approvals/test_control_center_approval.py`

**Interfaces:**
- Produces `HandoffPrepareRequest`, `HandoffRecord`, `HandoffPreview`, `HandoffTemplate`, and `HandoffStatus` requirements.
- Requires API paths `/api/v1/handoffs/templates`, `/api/v1/handoffs`, `/api/v1/handoffs/{id}`, and `/api/v1/handoffs/{id}/submit-approval`.

- [ ] **Step 1: Write migration RED tests**

Require migration version 3, a `handoffs` table with all columns from the design, upgrade from a version-2 database, repeated migration safety, and handling when the table already exists but migration row 3 is absent.

- [ ] **Step 2: Write service RED tests**

Test exact normalization, stable digests for equivalent input, changed digest for title/objective/expiry changes, template-only repository/base/path/test values, rejection of control characters, secret-like values, path traversal, `main`/`master`, and Protected markers.

- [ ] **Step 3: Write API RED tests**

Test authenticated template listing, idempotent prepare, bounded list/get, idempotent submit-approval, approval scope digest binding, and no Provider execution side effects.

- [ ] **Step 4: Write security RED tests**

Recursively inspect API JSON and database JSON to ensure no `token`, `token_hash`, `secret`, `credential`, environment variable, arbitrary path, raw command, or Protected source content is returned or persisted.

- [ ] **Step 5: Run RED**

```bash
PYTHONPATH=.:src python -m pytest -q \
  tests/unit/db/test_migrations.py \
  tests/unit/handoffs/test_handoff_service.py \
  tests/integration/api/test_handoff_preparation_api.py \
  tests/integration/approvals/test_control_center_approval.py \
  tests/security/test_handoff_preparation_security.py
```

Expected: failure because migration 3, HandoffService, and routes do not exist.

- [ ] **Step 6: Commit RED**

```bash
git add contracts/handoff/v1/schemas/handoff_draft.schema.json tests

git commit -m "test: freeze Phase 10A handoff preparation contracts"
```

### Task 2: Implement migration 3 and deterministic HandoffService

**Files:**
- Create: `src/picotoopet_core/handoffs/__init__.py`
- Create: `src/picotoopet_core/handoffs/models.py`
- Create: `src/picotoopet_core/handoffs/service.py`
- Modify: `src/picotoopet_core/db/schema.py`
- Modify: `src/picotoopet_core/db/database.py`

**Interfaces:**
- Produces `HandoffService.prepare(request, idempotency_key) -> HandoffRecord`.
- Produces `HandoffService.list(limit)`, `get(handoff_id)`, `submit_for_approval(handoff_id, idempotency_key)`, and `reconcile_approval(record)`.

- [ ] **Step 1: Add migration 3**

Create `handoffs` with unique idempotency keys for prepare and approval submission, immutable request/package digests, JSON payloads, nullable approval_id, timestamps, and indexes on status and created_at.

- [ ] **Step 2: Add strict models**

Use enums and Pydantic constraints. Normalize title to 120 characters and objective to 1000 characters. Only template ID `picotoopet-repo-maintenance-v1` and Provider `manual` are accepted.

- [ ] **Step 3: Implement canonical JSON and digest helpers**

Use `json.dumps(..., ensure_ascii=False, sort_keys=True, separators=(",", ":"))` and SHA-256. Never hash mutable status or approval decision fields into `request_digest`.

- [ ] **Step 4: Implement prepare idempotency**

The same Idempotency-Key returns the existing Handoff. A reused key with different normalized input raises a conflict error.

- [ ] **Step 5: Implement safe preview projection**

Return only fixed model fields. Keep complete manifest JSON internal to Mac Core and never expose package file contents.

- [ ] **Step 6: Run focused GREEN**

Run migration, unit, and security tests. Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add src/picotoopet_core/db src/picotoopet_core/handoffs

git commit -m "feat: add deterministic Phase 10A handoff preparation"
```

### Task 3: Bind taskless resource approvals and expose REST API

**Files:**
- Modify: `src/picotoopet_core/approvals/service.py`
- Modify: `src/picotoopet_core/services.py`
- Create: `src/picotoopet_core/api/routes/handoffs.py`
- Modify: `src/picotoopet_core/api/routes/approvals.py`
- Modify: `src/picotoopet_core/api/app.py`

**Interfaces:**
- Produces `ApprovalService.request_resource(...) -> ApprovalGrant`.
- Handoff submit returns the updated `HandoffRecord` with `waiting_approval` and approval_id.
- Approval decision reconciliation transitions only the linked Handoff.

- [ ] **Step 1: Add taskless approval creation**

Share canonical scope and token hashing with existing task approvals. Do not query or transition the queue when task_id is null.

- [ ] **Step 2: Add Handoff routes**

Require authentication and bounded limits. Require `Idempotency-Key` for prepare and submit-approval. Map domain errors to existing API error handling.

- [ ] **Step 3: Reconcile approval decisions**

After the existing Approval Center decision returns, call HandoffService reconciliation. Approved Handoffs become `approved`; rejected and expired records become their matching terminal state. No task is queued.

- [ ] **Step 4: Run API GREEN**

Run all Task 1 tests plus full approval integration tests.

- [ ] **Step 5: Export and validate OpenAPI**

```bash
PYTHONPATH=.:src python scripts/export_slice_d_openapi.py --output artifacts/openapi/mac_core_v1.openapi.json
python -m json.tool artifacts/openapi/mac_core_v1.openapi.json >/dev/null
```

- [ ] **Step 6: Commit**

```bash
git add src/picotoopet_core/api src/picotoopet_core/approvals src/picotoopet_core/services.py

git commit -m "feat: expose digest-bound handoff approval API"
```

### Task 4: Add Windows typed client and session workflow with RED tests

**Files:**
- Modify: `windows/desktop/src/PicotooPet.Desktop.Core/Contracts/ApiContracts.cs`
- Modify: `windows/desktop/src/PicotooPet.Desktop.Core/Networking/MacCoreClient.cs`
- Create: `windows/desktop/src/PicotooPet.Desktop/Services/ControlCenterSession.Handoffs.cs`
- Create: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/HandoffPreparationSmokeTests.cs`
- Modify: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/Program.cs`

**Interfaces:**
- Produces typed records for template, prepare request, preview, record, and submit response.
- Produces `GetHandoffTemplatesAsync`, `GetHandoffsAsync`, `PrepareHandoffAsync`, `GetHandoffAsync`, and `SubmitHandoffApprovalAsync`.

- [ ] **Step 1: Write typed-client RED tests**

Use a fake HttpMessageHandler to assert exact routes, headers, JSON fields, bounded response limits, no arbitrary path/command properties, and Idempotency-Key reuse.

- [ ] **Step 2: Add bounded contracts and client methods**

Use a dedicated 128 KiB maximum for Handoff list/detail responses. Keep typed responses strict and avoid `JsonElement` for user-facing preview data.

- [ ] **Step 3: Add session methods**

Generate operation-specific idempotency keys once per user action and preserve them across bounded network retry. Do not add Handoffs to periodic high-frequency task polling.

- [ ] **Step 4: Run native smoke executable**

Expected: typed workflow tests pass with warnings-as-errors.

- [ ] **Step 5: Commit**

```bash
git add windows/desktop/src/PicotooPet.Desktop.Core windows/desktop/src/PicotooPet.Desktop/Services windows/desktop/tests

git commit -m "feat: add typed Windows handoff preparation client"
```

### Task 5: Implement native WPF Phase 10A page

**Files:**
- Modify: `windows/desktop/src/PicotooPet.Desktop/ViewModels/CloudDevelopmentPageViewModel.cs`
- Modify: `windows/desktop/src/PicotooPet.Desktop/Views/Pages/CloudDevelopmentPage.xaml`
- Modify: `windows/desktop/src/PicotooPet.Desktop/ViewModels/ShellViewModel.cs`
- Modify: `windows/desktop/src/PicotooPet.Desktop/Services/AppSelfTest.cs`
- Create: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/HandoffPreparationPageWpfLayoutSmokeTests.cs`
- Modify: existing Cloud Development smoke/layout tests.

**Interfaces:**
- `CloudDevelopmentPageViewModel` exposes title, objective, templates, recent Handoffs, selected preview, busy state, status message, prepare command, submit command, and refresh command.
- `ProviderConfigured` remains false.

- [ ] **Step 1: Write ViewModel RED tests**

Require input validation, busy-state duplicate prevention, preview retention after refresh/network error, submit availability only for prepared status, and no Provider execution properties.

- [ ] **Step 2: Write real STA WPF RED test**

Instantiate the page, bind a deterministic ViewModel, invoke DataBind, Measure, Arrange, UpdateLayout, and verify the preparation form, preview, recent list, and bounded buttons render without exceptions.

- [ ] **Step 3: Implement focused ViewModel**

Use existing async command patterns. Keep network exceptions bounded. Do not clear a prepared preview when recent-list refresh replaces record instances with the same handoff_id.

- [ ] **Step 4: Implement native XAML**

Use TextBox, ItemsControl/ListView, Button, Border, Grid, ScrollViewer, and TextBlock only. No WebView, Hyperlink navigation, file picker, command shell, path input, credential input, or external process.

- [ ] **Step 5: Preserve frozen contract visibility**

Keep contract version, trust chain, security boundaries, and Phase 10B unavailable status visible below the active Phase 10A workflow.

- [ ] **Step 6: Run all WPF smoke tests**

Include Task Center binding RED regression, Results preview persistence, Approval Center, navigation reconnect, Cloud Development, and published self-test.

- [ ] **Step 7: Commit**

```bash
git add windows/desktop/src/PicotooPet.Desktop windows/desktop/tests

git commit -m "feat: add native Phase 10A handoff preparation page"
```

### Task 6: Stamp 2.3.10.1 and run affected-component release gates

**Files:**
- Modify: `src/picotoopet_core/product-version.txt`
- Modify: current-version assertions, package labels, delivery manifests, and release tests only where they represent the active release.

**Interfaces:**
- Produces exact product version `2.3.10.1` on Mac Core health, WPF title, left header, shortcuts, manifests, reports, and package names.

- [ ] **Step 1: Change canonical version**

Set `src/picotoopet_core/product-version.txt` to exactly `2.3.10.1`.

- [ ] **Step 2: Update current-version assertions**

Do not modify internal distribution version, schema version, Handoff contract `1.0.0`, or diagnostic schema versions.

- [ ] **Step 3: Run full Python and contract regression**

```bash
PYTHONPATH=.:src python -m pytest -q
ruff check src tests scripts
```

- [ ] **Step 4: Run Windows native behavior and formal release**

Require warnings-as-errors, real STA WPF tests, published self-test, executable allowlist, manifest/hash verification, and PowerShell 5.1 install/upgrade/failure-recovery/rollback lifecycle.

- [ ] **Step 5: Run Mac Core arm64 package gate**

Require full Python regression, Ruff, OpenAPI, arm64 package, install, API fixture, and rollback fixture.

- [ ] **Step 6: Confirm Worker impact gate**

If Worker source/runtime/package files are unchanged, require impact detection PASS and intentionally skip Worker packaging.

- [ ] **Step 7: Independently verify artifacts**

Recompute archive SHA-256, inspect traversal/link safety, verify manifest coverage and payload hashes, verify exact source head/product version, and record Artifact IDs.

- [ ] **Step 8: Update Draft PR body**

Record exact source head, merge-test SHA, CI run IDs, package names, SHA-256 values, known non-goals, and user-machine installation steps. Keep the PR Draft and unmerged.