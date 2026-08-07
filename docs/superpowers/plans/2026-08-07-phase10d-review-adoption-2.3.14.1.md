# Phase 10D-B Review Adoption Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend `2.3.13.2` so a `ready_for_review` Codex Return can be human-reviewed, accepted/rejected, deterministically replayed in a fresh Mac worktree, and promoted only to an `adoption_ready` local candidate.

**Architecture:** Mac Core remains the fact source. Mac Worker persists a bounded immutable normalized change set before the Provider worktree is deleted, then a separate adoption worker replays that exact artifact from the immutable base commit. Windows exposes read-only review facts plus fixed accept/reject controls. No commit, push, PR, merge, tag, release, arbitrary patch, path, command, model, or environment input is introduced.

**Tech Stack:** Python 3.12, SQLite, FastAPI/Pydantic, Git worktrees, WPF/.NET 10, GitHub Actions macOS arm64 and Windows 2025.

## Global Constraints

- Product version: `2.3.14.1`.
- Base commit: `0caeb2ef6031a6a004d6e80584783d9c5598e78d`.
- Mac Core + SQLite is the only review/adoption fact source.
- Maximum 5 text files, 64 KiB/file, 256 KiB payload, 128 KiB review diff.
- Review accept/reject is bodyless and idempotent.
- Adoption worker replays only server-owned immutable artifacts from exact base commit.
- No automatic Codex retry or second Codex call.
- No automatic commit/push/PR/merge/tag/release.
- No user-side build; no extra user-side verifier program.
- Mac Worker is affected in this version and therefore must receive native CI and a new package.

---

### Task 1: Migration 7 and review/adoption models RED/GREEN

**Files:**
- Modify: `src/picotoopet_core/db/schema.py`
- Modify: `src/picotoopet_core/db/database.py`
- Create: `src/picotoopet_core/providers/review_models.py`
- Test: `tests/unit/db/test_provider_review_migration.py`
- Test: `tests/unit/providers/test_provider_review_models.py`

**Interfaces:**
- Produces `ProviderReturnArtifactRecord`, `ProviderReviewDecisionRecord`, `ProviderAdoptionCandidateRecord`, `ProviderAdoptionStatus`.
- Migration 7 creates `provider_return_artifacts`, `provider_review_decisions`, `provider_adoption_candidates` without changing prior rows.

- [ ] Write failing migration/model tests asserting exact tables, columns, unique session constraints, strict Pydantic `extra="forbid"`, fixed status enums and no content fields in DB models.
- [ ] Run focused tests and confirm RED because migration 7/models do not exist.
- [ ] Add `MIGRATION_007` and database migration application.
- [ ] Add strict review/adoption models with bounded path metadata and digest fields.
- [ ] Run focused tests and full migration regression.
- [ ] Commit.

### Task 2: Immutable Provider Return Artifact Store RED/GREEN

**Files:**
- Modify: `src/picotoopet_core/config/paths.py`
- Create: `src/picotoopet_core/providers/artifact_store.py`
- Create: `src/picotoopet_core/providers/change_set.py`
- Test: `tests/unit/providers/test_provider_artifact_store.py`
- Test: `tests/security/test_provider_change_set_security.py`

**Interfaces:**
- `ProviderReturnArtifactStore.write(...) -> StoredProviderArtifact`
- `ProviderReturnArtifactStore.load(return_id, expected_digest) -> StoredProviderArtifact`
- `NormalizedChange(operation, path, base_sha256, result_sha256, size_bytes, payload_name)`.

- [ ] Write RED tests for add/modify/delete artifact persistence, atomic temp-to-final write, manifest SHA, reload verification, 5-file/64-KiB/256-KiB/128-KiB bounds, UTF-8, traversal/link/binary/secret rejection.
- [ ] Confirm RED.
- [ ] Add server-derived `provider_returns_dir` to runtime paths.
- [ ] Implement canonical change-set serialization and bounded artifact store.
- [ ] Implement secret scan using existing project redaction/security patterns; store payload outside SQLite.
- [ ] Run focused tests and security suite.
- [ ] Commit.

### Task 3: Capture normalized changes before 13.2 Provider cleanup

**Files:**
- Modify: `src/picotoopet_core/providers/git_runner.py`
- Modify: `src/picotoopet_core/worker/codex_worktree.py`
- Modify: `src/picotoopet_core/providers/execution.py`
- Modify: `src/picotoopet_core/services.py`
- Test: `tests/unit/providers/test_provider_change_capture.py`
- Test: `tests/integration/worker/test_provider_artifact_capture_e2e.py`

**Interfaces:**
- Git layer returns structured `A/M/D` change entries.
- Execution coordinator stores artifact and `provider_return_artifacts` row before setting `ready_for_review`.

- [ ] Write RED fixture repo tests covering tracked modify/delete and untracked add.
- [ ] Prove `ready_for_review` currently lacks adoptable artifact.
- [ ] Extend fixed Git runner with safe status/base-content/diff operations; no shell strings.
- [ ] Build normalized change set and bounded review diff before cleanup.
- [ ] Persist artifact metadata in Core transaction and only then transition Session to `ready_for_review`.
- [ ] Mark existing 13.2 rows without artifact as legacy/no-adoption-artifact.
- [ ] Run Provider, Return and Worker regression.
- [ ] Commit.

### Task 4: Review service and strict API RED/GREEN

**Files:**
- Create: `src/picotoopet_core/providers/review_service.py`
- Create: `src/picotoopet_core/api/routes/provider_reviews.py`
- Modify: `src/picotoopet_core/api/app.py`
- Modify: `src/picotoopet_core/services.py`
- Test: `tests/unit/providers/test_provider_review_service.py`
- Test: `tests/integration/api/test_provider_review_api.py`

**Interfaces:**
- `get_review(session_id)` returns safe artifact/diff projection.
- `accept(session_id, idempotency_key)` creates one accepted decision and one queued candidate.
- `reject(session_id, idempotency_key)` creates one rejected decision and no candidate.

- [ ] Write RED tests: only ready_for_review+artifact is reviewable; legacy unavailable; accept/reject bodyless; idempotent replay; decision immutable; no patch/path/reason/free JSON accepted.
- [ ] Confirm RED.
- [ ] Implement review service and API routes.
- [ ] Add fixed error mapping without content/path leakage.
- [ ] Run API/security regression and exported OpenAPI checks.
- [ ] Commit.

### Task 5: Adoption worktree replay and local static validation RED/GREEN

**Files:**
- Create: `src/picotoopet_core/providers/adoption_execution.py`
- Modify: `src/picotoopet_core/providers/git_runner.py`
- Modify: `src/picotoopet_core/cli.py`
- Test: `tests/unit/providers/test_adoption_replay.py`
- Test: `tests/integration/worker/test_adoption_worker_e2e.py`
- Test: `tests/security/test_adoption_worker_security.py`

**Interfaces:**
- Task type: `provider.adoption.apply-v1`.
- Candidate status: `queued -> staging -> applying -> validating -> adoption_ready` or fixed terminal failure.

- [ ] Write RED tests for exact base commit replay of add/modify/delete, base SHA mismatch, artifact tamper, traversal/symlink/binary/secret rejection, deterministic result SHA, and cleanup on every exit.
- [ ] Confirm RED.
- [ ] Implement candidate queueing and fixed Worker handler.
- [ ] Reuse isolated worktree manager with distinct candidate IDs.
- [ ] Apply file operations via Python file APIs; do not invoke shell patch.
- [ ] Run fixed local checks: `git diff --check`, UTF-8 decode, `ast.parse` for changed `.py`; never execute Provider-owned scripts.
- [ ] Store validation summary and candidate digest; cleanup worktree before terminal return.
- [ ] Run focused and full Worker regression.
- [ ] Commit.

### Task 6: Windows typed review client and WPF RED/GREEN

**Files:**
- Create: `windows/desktop/src/PicotooPet.Desktop.Core/Contracts/ProviderReviewContracts.cs`
- Modify: `windows/desktop/src/PicotooPet.Desktop.Core/Networking/MacCoreProviderClient.cs`
- Modify: `windows/desktop/src/PicotooPet.Desktop/Services/IProviderSessionGateway.cs`
- Modify: `windows/desktop/src/PicotooPet.Desktop/Services/ControlCenterSession.Provider.cs`
- Create: `windows/desktop/src/PicotooPet.Desktop/ViewModels/ProviderReviewViewModel.cs`
- Create: `windows/desktop/src/PicotooPet.Desktop/Views/Pages/ProviderReviewPanel.xaml`
- Create: `windows/desktop/src/PicotooPet.Desktop/Views/Pages/ProviderReviewPanel.xaml.cs`
- Modify: `windows/desktop/src/PicotooPet.Desktop/Views/Pages/CloudDevelopmentPage.xaml.cs`
- Test: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/ProviderReviewSmokeTests.cs`
- Test: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/CloudDevelopmentPageWpfLayoutSmokeTests.cs`

**Interfaces:**
- Typed client methods: `GetProviderReviewAsync`, `AcceptProviderReviewAsync`, `RejectProviderReviewAsync`, `GetAdoptionCandidatesAsync`.
- WPF presents read-only diff and fixed buttons only.

- [ ] Write RED C# smoke tests for review selection persistence, read-only diff, accept/reject idempotency, candidate refresh, bounded network failure preservation and no editable patch/path/command/model/token fields.
- [ ] Add real STA layout assertion with DataBind/Measure/Arrange/UpdateLayout.
- [ ] Confirm Windows RED on native CI.
- [ ] Implement contracts/client/gateway/viewmodel/panel.
- [ ] Run warnings-as-errors build and smoke tests.
- [ ] Commit.

### Task 7: Version 2.3.14.1 and release-contract atomic bump

**Files:**
- Modify all active canonical version surfaces found by repository stale-version audit.
- Modify release goal contract and packaging fixtures.
- Add/modify `tests/contract/test_phase10d_review_adoption_contract.py`.

**Interfaces:**
- Canonical user version becomes `2.3.14.1` everywhere active.

- [ ] Search active source/test/release surfaces for stale `2.3.13.2` literals before changing any version.
- [ ] Update all active product-version literals atomically.
- [ ] Add contract assertions for review artifact bounds, no auto publish, no user-side build, and impact-aware Worker packaging rule.
- [ ] Run full Python regression and native Windows tests.
- [ ] Commit.

### Task 8: Exact-head CI, package, independent verification

**Files:**
- CI/workflow changes only if tests prove required; otherwise reuse existing impact-aware workflows.

- [ ] Confirm exact final head SHA.
- [ ] Require Windows Control Center CI success.
- [ ] Require Windows Prebuilt Release success.
- [ ] Require Mac Core arm64 success.
- [ ] Require Mac Worker arm64 success because this version changes Worker runtime.
- [ ] Download formal Windows/Mac Core/Mac Worker artifacts.
- [ ] Independently recompute outer/inner SHA-256, Manifest payload hashes/sizes, product version, architecture and source provenance.
- [ ] Confirm no user-side build and no extra verifier executable/program was added.
- [ ] Deliver packages plus human acceptance checklist.

### Task 9: Human acceptance definition

- [ ] Windows title/subtitle show `2.3.14.1`, control chain is online and Cloud Development opens without crash.
- [ ] Complete or use a new Codex Session that reaches `ready_for_review` under 14.1 so an immutable artifact exists.
- [ ] Review pane shows <=5 paths, operations, sizes, digests and read-only bounded diff.
- [ ] Reject path creates no candidate; on a separate Handoff/Session, accept creates exactly one candidate.
- [ ] Accepted candidate advances to `adoption_ready` or a truthful fixed failure state.
- [ ] GitHub and source repo show no automatic commit/push/PR/merge/tag/release.
- [ ] Original source workspace remains clean after Provider and adoption worktree cleanup.
