# Phase 10D-C Local Commit Candidate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a digest-bound, explicitly approved local Git Commit Candidate stage that turns an existing `adoption_ready` candidate into a durable local commit object and fixed `refs/picotoopet/commit-candidates/<id>` ref without any push, PR, merge, tag, release, Provider call, hook, filter, or network activity.

**Architecture:** Mac Core owns the new commit-candidate state, approval fact, and read-only API. Mac Worker replays the already accepted normalized change set in a fresh worktree, then constructs the Git tree and commit with plumbing commands plus a temporary index so repository hooks and clean/smudge filters cannot run. Windows WPF only prepares the fixed operation and displays safe status/provenance; all free-form commit/ref/path/command input remains forbidden.

**Tech Stack:** Python 3.13+, FastAPI, Pydantic, SQLite, existing diagnostic queue/Worker runtime, Git plumbing via argument-vector subprocess calls, .NET/WPF native Windows client, GitHub Actions macOS arm64 + Windows native CI.

## Global Constraints

- Product version is `2.3.15.1`; base source is `3c2e741ffd69fef1fa12076467a61ab24c1c2286` from Draft PR #15.
- `main` remains unchanged; all work is stacked, Draft, and unmerged.
- Commit creation is allowed only from an existing `adoption_ready` candidate.
- Commit parent must equal the exact immutable adoption `base_commit`.
- Fixed local ref namespace is `refs/picotoopet/commit-candidates/`; never write `refs/heads/`, `refs/tags/`, or `refs/remotes/`.
- Commit identity is fixed to `PicotooPet Local Adoption <picotoopet@localhost>`; message and trailers are server-generated.
- API accepts no commit message, author, ref, path, command, model, environment, remote, URL, patch, or arbitrary JSON input.
- Git hooks and clean/smudge filters must not execute; no network or Provider invocation is permitted.
- No automatic push, Draft PR, merge, tag, or release.
- Already real-machine-accepted MacCore hotfix1 / MacWorker hotfix2 behavior is a non-regression baseline, not a separate 2.3.14.2 delivery.
- User machines receive precompiled packages only; no source build or development SDK install.
- Final delivery includes Windows + Mac Core + Mac Worker because all three are affected, SHA-256, and manual acceptance criteria; no extra user-side verifier program.

---

## File Structure

### New Python files

- `src/picotoopet_core/providers/commit_models.py` — bounded commit-candidate enums and API-safe records.
- `src/picotoopet_core/providers/commit_service.py` — prepare/list/get flow plus resource approval creation and approval-to-queue transition.
- `src/picotoopet_core/providers/commit_execution.py` — Worker payload, replay verification, plumbing-only commit builder, namespaced ref CAS, coordinator/handler.
- `src/picotoopet_core/api/routes/provider_commits.py` — bodyless prepare and read-only list/get routes.

### Modified Python files

- `src/picotoopet_core/db/schema.py` — migration 8.
- `src/picotoopet_core/db/database.py` — register migration 8.
- `src/picotoopet_core/handoffs/approvals.py` — extend safe approval summary allowlist with commit-candidate provenance keys.
- `src/picotoopet_core/services.py` — construct/expose `ProviderCommitService`.
- `src/picotoopet_core/api/app.py` — include commit router.
- `src/picotoopet_core/cli.py` — register/enqueue commit coordinator only when provider execution repository is configured.
- `src/picotoopet_core/providers/git_runner.py` — add hook/filter-safe plumbing helpers only if existing argument-vector runner lacks them.
- `src/picotoopet_core/product-version.txt` — `2.3.15.1`.
- `contracts/release/project-goal-invariants.json` — freeze version and Phase 10D-C security invariants.

### New/modified Python tests

- `tests/unit/db/test_provider_commit_migration.py`
- `tests/unit/providers/test_provider_commit_models.py`
- `tests/unit/providers/test_provider_commit_service.py`
- `tests/unit/providers/test_provider_commit_execution.py`
- `tests/integration/api/test_provider_commit_api.py`
- `tests/integration/worker/test_provider_commit_candidate_e2e.py`
- `tests/security/test_provider_commit_security.py`
- existing version/goal-integrity tests updated atomically for `2.3.15.1`.

### Windows files

- `windows/desktop/src/PicotooPet.Desktop.Core/Contracts/ProviderReviewContracts.cs` — add commit-candidate DTOs/statuses or split to `ProviderCommitContracts.cs` if the existing file would become unwieldy.
- `windows/desktop/src/PicotooPet.Desktop.Core/Networking/MacCoreProviderReviewClient.cs` — add bodyless prepare + list/get typed calls or split to `MacCoreProviderCommitClient.cs` with the same auth/idempotency patterns.
- `windows/desktop/src/PicotooPet.Desktop/Services/IProviderReviewGateway.cs` — expose commit candidate operations, or add focused `IProviderCommitGateway.cs` if separation reduces coupling.
- `windows/desktop/src/PicotooPet.Desktop/Services/ProviderReviewGatewayContext.cs` — compose the commit client/gateway context.
- `windows/desktop/src/PicotooPet.Desktop/Services/ControlCenterSession.ProviderReview.cs` — refresh commit candidates with provider review/adoption state.
- `windows/desktop/src/PicotooPet.Desktop/ViewModels/ProviderReviewViewModel.cs` — prepare command, selected commit candidate, immutable preview/status.
- `windows/desktop/src/PicotooPet.Desktop/Views/Pages/ProviderReviewPanel.xaml` — local commit candidate section.
- `windows/desktop/src/PicotooPet.Desktop/Views/Pages/ProviderReviewPanel.xaml.cs` — no free-form inputs; only fixed command binding.
- `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/ProviderReviewSmokeTests.cs`
- `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/ProviderReviewPanelWpfLayoutSmokeTests.cs`
- `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/ProductVersionWpfSmokeTests.cs`
- `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/Program.cs`

---

### Task 1: RED migration 8 and bounded commit-candidate models

**Files:**
- Create: `tests/unit/db/test_provider_commit_migration.py`
- Create: `tests/unit/providers/test_provider_commit_models.py`
- Create: `src/picotoopet_core/providers/commit_models.py`
- Modify: `src/picotoopet_core/db/schema.py`
- Modify: `src/picotoopet_core/db/database.py`

**Interfaces:**
- Produces `ProviderCommitStatus`, `ProviderCommitCandidateRecord`, and migration table `provider_commit_candidates`.

- [ ] **Step 1: Write failing migration tests** asserting migration 8 is additive/idempotent, creates exactly one commit-candidate row per `adoption_candidate_id`, keeps existing migration 1–7 data, and enforces unique `idempotency_key`.
- [ ] **Step 2: Write failing model tests** requiring `commit_sha/tree_sha/base_commit` to be 40–64 lowercase hex, `local_ref` to match `^refs/picotoopet/commit-candidates/[0-9a-f-]{36}$`, status to be a closed enum, and `failure_code` to be bounded uppercase snake case.
- [ ] **Step 3: Run:** `python -m pytest tests/unit/db/test_provider_commit_migration.py tests/unit/providers/test_provider_commit_models.py -q`.
  **Expected:** FAIL because migration 8 and models do not exist.
- [ ] **Step 4: Implement `MIGRATION_008`** with fields from the approved design and indexes on `(status, created_at DESC)` plus unique `adoption_candidate_id`/`idempotency_key`.
- [ ] **Step 5: Register migration 8** in the same ordered migration map/list used by `Database.apply_migrations()`.
- [ ] **Step 6: Implement `commit_models.py`** with no permissive `extra` fields.
- [ ] **Step 7: Re-run the focused tests** and require PASS.
- [ ] **Step 8: Commit:** `test: add commit candidate migration and models`.

### Task 2: RED prepare service and digest-bound resource approval

**Files:**
- Create: `tests/unit/providers/test_provider_commit_service.py`
- Create: `src/picotoopet_core/providers/commit_service.py`
- Modify: `src/picotoopet_core/handoffs/approvals.py`
- Modify: `src/picotoopet_core/services.py`

**Interfaces:**
- Produces `ProviderCommitService.prepare(adoption_candidate_id, *, idempotency_key) -> ProviderCommitCandidateRecord`.
- Produces `ProviderCommitService.list_candidates(limit=100)` and `get_candidate(commit_candidate_id)`.
- Uses existing `HandoffApprovalService.request_resource_in_transaction(...)` with approval type `provider.commit.create-v1`.

- [ ] **Step 1: Write failing service tests** for: only `adoption_ready`; idempotent same key; conflict on key reuse for another candidate; one commit candidate per adoption candidate; fixed local ref; fixed message digest; approval scope binds commit/adoption/session/return/base/change-set/ref/message digest; no Git object/ref created at prepare time.
- [ ] **Step 2: Run:** `python -m pytest tests/unit/providers/test_provider_commit_service.py -q`.
  **Expected:** FAIL because the service does not exist.
- [ ] **Step 3: Extend approval safe-summary keys** only with `commit_candidate_id`, `adoption_candidate_id`, `base_commit`, `change_set_digest`, `local_ref`, and `message_digest`; do not expose message body or file payload.
- [ ] **Step 4: Implement service transaction** creating commit-candidate row + resource approval atomically with fixed `requested_by="provider-commit"` and bounded expiry matching existing Handoff resource-approval policy.
- [ ] **Step 5: Implement read projections** from stored safe facts; never read Git state on normal GET.
- [ ] **Step 6: Re-run focused tests** and require PASS.
- [ ] **Step 7: Commit:** `feat: prepare digest-bound local commit candidates`.

### Task 3: RED bodyless authenticated REST API

**Files:**
- Create: `tests/integration/api/test_provider_commit_api.py`
- Create: `src/picotoopet_core/api/routes/provider_commits.py`
- Modify: `src/picotoopet_core/api/app.py`

**Interfaces:**
- `POST /api/v1/provider-adoption-candidates/{candidate_id}/commit/prepare`
- `GET /api/v1/provider-commit-candidates?limit=100`
- `GET /api/v1/provider-commit-candidates/{commit_candidate_id}`

- [ ] **Step 1: Write failing API tests** requiring auth, `Idempotency-Key`, empty body, 422 on `{}`, 400/409 fixed domain errors, bounded list limit, and no secret/diff/file body/ref override fields in response or OpenAPI request schema.
- [ ] **Step 2: Run:** `python -m pytest tests/integration/api/test_provider_commit_api.py -q`.
  **Expected:** FAIL with 404/missing routes.
- [ ] **Step 3: Implement router** using the existing `require_empty_body` pattern and a focused error mapper with fixed safe messages.
- [ ] **Step 4: Include router** in `create_app()` under the existing `/api/v1` prefix.
- [ ] **Step 5: Re-run API tests** and require PASS.
- [ ] **Step 6: Commit:** `feat: expose bounded commit candidate api`.

### Task 4: RED hook/filter-safe Git plumbing builder

**Files:**
- Create: `tests/unit/providers/test_provider_commit_execution.py`
- Create: `src/picotoopet_core/providers/commit_execution.py`
- Modify: `src/picotoopet_core/providers/git_runner.py` only if required for reusable argument-vector plumbing helpers.

**Interfaces:**
- Produces `CommitTaskPayload` with only server-owned IDs/digests.
- Produces `LocalCommitBuildResult(commit_sha, tree_sha, parent_sha, local_ref, validation_checks)`.
- Produces `ProviderLocalCommitBuilder.create(...)`.

- [ ] **Step 1: Write RED fixture** creating a temporary Git repository with: exact base commit, executable malicious `.git/hooks/pre-commit`, malicious `.git/hooks/commit-msg`, `.gitattributes` clean filter configured to write a sentinel, and an adoption artifact with add/modify/delete.
- [ ] **Step 2: Write failing assertions** that builder output has exactly one parent=base, tree diff equals normalized change set, add mode=100644, modify preserves base 100644/100755 regular mode, delete disappears, sentinel files are absent, and no `refs/heads/*`, `refs/tags/*`, `refs/remotes/*` changes occur.
- [ ] **Step 3: Add RED conflict test** pre-populating `refs/picotoopet/commit-candidates/<id>` with a different commit and requiring `COMMIT_REF_CONFLICT` without overwrite.
- [ ] **Step 4: Run:** `python -m pytest tests/unit/providers/test_provider_commit_execution.py -q`.
  **Expected:** FAIL because builder does not exist.
- [ ] **Step 5: Implement fresh replay validation** by reusing `ProviderReturnArtifactStore`, `CodexWorktreeManager`, and the same result-hash/path/UTF-8/AST rules used in `AdoptionArtifactApplier`.
- [ ] **Step 6: Implement plumbing-only tree construction** with a temp `GIT_INDEX_FILE`: `read-tree`, `hash-object --no-filters -w --stdin`, `update-index --cacheinfo`/remove, `write-tree`; every subprocess call must be an argument vector with `shell=False` semantics through the existing Git runner.
- [ ] **Step 7: Implement commit object creation** with `commit-tree`, fixed identity/env, fixed message/trailers, and exact parent.
- [ ] **Step 8: Implement ref CAS** using `git update-ref <fixed_ref> <commit_sha> <expected_old>` with expected old all-zero/nonexistent semantics; reject any existing different ref.
- [ ] **Step 9: Re-read object/ref** and validate commit tree, parent, identity, trailers, fixed ref, and diff before returning success.
- [ ] **Step 10: Ensure finally cleanup** removes worktree and temp index on all paths.
- [ ] **Step 11: Re-run focused tests** and require PASS.
- [ ] **Step 12: Commit:** `feat: create hook-safe local commit objects`.

### Task 5: RED Worker coordinator and approval-to-queue transition

**Files:**
- Extend: `tests/unit/providers/test_provider_commit_execution.py`
- Create: `tests/integration/worker/test_provider_commit_candidate_e2e.py`
- Modify: `src/picotoopet_core/providers/commit_service.py`
- Modify: `src/picotoopet_core/providers/commit_execution.py`
- Modify: `src/picotoopet_core/cli.py`

**Interfaces:**
- `ProviderCommitExecutionCoordinator.TASK_TYPE = "provider.commit.create-v1"`.
- `enqueue_pending()` transitions approved `waiting_approval` candidates to queued and creates one queue task.
- `handler(task)` owns staging/replaying/validating/committing/terminal state writes.

- [ ] **Step 1: Write RED tests** proving pending/rejected/expired approvals never enqueue; approved exact-scope approval enqueues once; retries do not create a second task/ref; Worker task payload cannot contain path/message/ref/author/command/remote.
- [ ] **Step 2: Write RED E2E test** from seeded `adoption_ready` + accepted artifact -> prepare -> approval resolution -> enqueue -> handler -> `commit_ready` with stored `commit_sha/tree_sha/local_ref` and no remote network invocation.
- [ ] **Step 3: Run:** `python -m pytest tests/unit/providers/test_provider_commit_execution.py tests/integration/worker/test_provider_commit_candidate_e2e.py -q`.
- [ ] **Step 4: Implement approval reconciliation** by reading the approval row and verifying its stored canonical scope matches the commit-candidate facts before queue creation.
- [ ] **Step 5: Implement status transitions and failure-code mapping** from the design; no terminal success before ref/object re-read passes.
- [ ] **Step 6: Register coordinator/handler in `_run_worker()`** only when `provider_execution_configured` is true; use a dedicated `runtime/commit-worktrees` directory.
- [ ] **Step 7: Re-run focused tests** and require PASS.
- [ ] **Step 8: Commit:** `feat: execute approved local commit candidates`.

### Task 6: Security regression and no-network witnesses

**Files:**
- Create: `tests/security/test_provider_commit_security.py`
- Update existing provider security regression files only where shared fixtures are needed.

**Interfaces:**
- No new production API; locks down the Phase 10D-C boundary.

- [ ] **Step 1: Add mutation/negative tests** for absolute paths, traversal, backslashes, NUL, symlink, submodule mode 160000, binary payload, secret pattern, oversized payload, arbitrary body keys, local-ref escape, branch/tag/remote ref attempts, and malicious Git config.
- [ ] **Step 2: Add subprocess/network witness** that fails if `git push`, `git fetch`, `git ls-remote`, `curl`, `ssh`, Provider executable, or shell invocation is attempted in commit execution.
- [ ] **Step 3: Run:** `python -m pytest tests/security/test_provider_commit_security.py -q` and require the RED witness before implementation adjustments, then PASS after minimal fixes.
- [ ] **Step 4: Commit:** `test: lock down local commit candidate security boundary`.

### Task 7: Windows typed client and WPF local commit candidate UI

**Files:**
- Modify/create the Windows files listed in File Structure.
- Update: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/ProviderReviewSmokeTests.cs`
- Update: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/ProviderReviewPanelWpfLayoutSmokeTests.cs`

**Interfaces:**
- Typed prepare/list/get operations with empty POST body and idempotency key.
- ViewModel properties for selected commit candidate, immutable message preview, status, commit/tree/base SHA, fixed local ref, and `PrepareCommitCommand`.

- [ ] **Step 1: Write RED C# smoke tests** for JSON contract parsing, empty-body prepare request, idempotency reuse, no free-form commit/ref/author properties, selected-item persistence across refresh, and `commit_ready` safe projection.
- [ ] **Step 2: Write RED real STA WPF layout test** constructing the production panel, binding a commit-ready ViewModel, then running DataBind, Measure, Arrange, UpdateLayout and asserting visible local-commit section + fixed warning copy.
- [ ] **Step 3: Run the existing Windows smoke-test project** with the repository’s current command from `windows-control-center-ci.yml`; require RED at the new assertions.
- [ ] **Step 4: Implement typed DTO/client/gateway changes** following the existing Provider Review patterns; no generic JSON dictionaries in the UI boundary.
- [ ] **Step 5: Implement ViewModel/UI** with only fixed action buttons and read-only text; no TextBox for commit message/ref/author/branch/remote.
- [ ] **Step 6: Re-run C# smoke tests** and require PASS.
- [ ] **Step 7: Commit:** `feat(windows): review and prepare local commit candidates`.

### Task 8: Atomic version bump, stale-version audit, and hotfix non-regression contract

**Files:**
- Modify: `src/picotoopet_core/product-version.txt`
- Modify all active version fixtures/assertions found by repository-wide search.
- Modify: `contracts/release/project-goal-invariants.json`
- Update version-specific Python/C# tests from the PR #15 changed-file inventory.
- Add/extend Mac Worker delivery contract test for launchd-like Codex resolution only if the behavior is not already represented in source tests.

**Interfaces:**
- Product version everywhere is exactly `2.3.15.1`.

- [ ] **Step 1: Run repository-wide search for `2.3.14.1`** and classify each hit as active version surface vs historical frozen evidence.
- [ ] **Step 2: Write/adjust RED version-goal tests first** so active surfaces must report `2.3.15.1` while historical docs remain unchanged.
- [ ] **Step 3: Audit current source for the already accepted MacCore hotfix1 / MacWorker hotfix2 behavior.** If current source already encodes it, add no duplicate runtime change. If not, add only the smallest non-regression contract and implementation delta needed so the new package cannot restore the pre-hotfix launchd/Codex behavior.
- [ ] **Step 4: Apply one atomic active-version update** to `2.3.15.1`.
- [ ] **Step 5: Run Python version/goal-integrity suites and Windows product-version smoke tests** until PASS.
- [ ] **Step 6: Commit:** `release: bump product version to 2.3.15.1`.

### Task 9: Full regression, exact-head Draft PR, native CI, packages, and independent verification

**Files:**
- Create/update PR metadata only; do not merge `main`.
- No user-side verifier executable.

**Interfaces:**
- Formal deliverables: Windows win-x64 prebuilt ZIP, Mac Core arm64 archive, Mac Worker arm64 archive, SHA-256 and manual acceptance checklist.

- [ ] **Step 1: Run focused Python suites** for migrations, API, provider/adoption/commit execution/security.
- [ ] **Step 2: Run full Python regression + Ruff** using repository-native commands.
- [ ] **Step 3: Run Windows contract/security/smoke locally only where supported; rely on Windows native CI for WPF build/layout/publish evidence.**
- [ ] **Step 4: Create/update stacked Draft PR** with base `feature/phase10d-review-adoption-2.3.14.1`; never target `main`.
- [ ] **Step 5: Let exact-head PR triggers run all affected native workflows:** Windows Control Center CI, Windows Prebuilt Release, Mac Core arm64, Mac Worker arm64.
- [ ] **Step 6: If a gate fails, inspect exact failing job/log, add a failing regression test when the defect is reproducible, make the minimal fix, and continue without non-high-risk approval pauses.**
- [ ] **Step 7: Poll through terminal status; do not classify queued/in-progress lifecycle jobs as blocked.**
- [ ] **Step 8: Download formal successful artifacts for the final exact source head.**
- [ ] **Step 9: Independently verify archive integrity, traversal/link safety, product version, source/build provenance, Manifest exact coverage, per-file size/SHA, Windows PE x64, Mac arm64, and `source_build_on_user_pc/source_build_on_user_mac=false`.
- [ ] **Step 10: Deliver all necessary packages together** with SHA-256 and manual acceptance criteria; explicitly state Draft/Open/Unmerged and no tag/release.

## Plan Self-Review

- Spec coverage: migration/state/API/approval/Worker/plumbing/ref/WPF/version/CI/packages/manual acceptance all have explicit tasks.
- Placeholder scan: no TBD/TODO/fill-later steps.
- Type consistency: `ProviderCommitCandidateRecord`, `ProviderCommitService`, `ProviderCommitExecutionCoordinator`, `provider.commit.create-v1`, `refs/picotoopet/commit-candidates/<id>` are used consistently.
- Scope remains one end-to-end feature boundary: local commit candidate only; remote branch/push/PR remains explicitly excluded.
