# Phase 10E Controlled Push + Draft PR Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `2.3.17.1` so an exact `commit_ready` local Commit Candidate can, after one new digest-bound human approval, be pushed to a fixed namespaced remote branch, independently verified, converted into an exact Draft PR against its immutable Handoff baseline, and exposed as `pr_ready` without merge/tag/release.

**Architecture:** Mac Core remains the authoritative SQLite fact source. A new `provider_publication_candidates` state machine binds Commit Candidate provenance to Handoff repo/base facts and one publication approval; Mac Worker performs fixed Git and GitHub CLI operations with idempotent remote/PR recovery. Windows WPF only prepares and reads the candidate; Approval Center remains the only decision surface.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLite, fixed `subprocess` Git/GitHub CLI execution, pytest, C#/.NET WPF, GitHub Actions native macOS arm64 and Windows x64 CI.

## Global Constraints

- Product version is exactly `2.3.17.1`.
- Baseline source head is `835656822bd2e1ce199d4a6f4b0d5d568211dfa0` from product `2.3.16.3`.
- Only `commit_ready` with a non-null exact `commit_sha` is eligible.
- Publication approval kind is exactly `provider.publish.pr-create-v1`.
- Approval binds repo/base/commit/fixed remote ref/title digest/body digest and `draft=true`.
- PR base is the Handoff's immutable `base_ref`, and its remote SHA must still equal Handoff `base_commit` before any push.
- Remote ref is `refs/heads/picotoopet/commit-candidates/<publication_candidate_id>`; no free refspec and no force push.
- Publication API accepts no repo/base/head/title/body/ref/command input and `prepare` body is empty.
- Git push bypasses hooks and rejects dangerous URL rewrite/pushurl/vcs config.
- GitHub PR creation uses a fixed configured executable from `PICOTOO_GITHUB_CLI_EXECUTABLE`; token/credentials are never exposed to Windows or persisted in publication facts.
- CI must use a local bare Git remote and deterministic fake GitHub CLI; CI must not write the real GitHub repository.
- `pr_ready` is not CI-green, merge-ready, tag-ready, or release-ready.
- No main merge, tag, GitHub Release, paid provider call, or source compilation on user machines.
- Windows, Mac Core, and Mac Worker formal packages are all required because all three surfaces change.

---

### Task 1: Publication domain model, Migration 10, and prepare service

**Files:**
- Create: `src/picotoopet_core/db/migration_010.py`
- Modify: `src/picotoopet_core/db/database.py`
- Create: `src/picotoopet_core/providers/publication_models.py`
- Create: `src/picotoopet_core/providers/publication_service.py`
- Modify: `src/picotoopet_core/handoffs/approvals.py`
- Test: `tests/unit/providers/test_publication_service.py`
- Test: `tests/unit/db/test_migration_010.py`

**Interfaces:**
- Produces `ProviderPublicationStatus`, `ProviderPublicationCandidateRecord`, `ProviderPublicationService`.
- `ProviderPublicationService.prepare(commit_candidate_id: str, *, idempotency_key: str) -> ProviderPublicationCandidateRecord`.
- Produces deterministic helpers `remote_ref()`, `remote_branch()`, `pr_title()`, `pr_title_digest()`, `pr_body()`, `pr_body_digest()`.

- [ ] **Step 1: Write failing service tests**

Create tests that insert a complete Handoff -> provider session -> adoption candidate -> `commit_ready` commit candidate chain and assert:

```python
candidate = service.prepare(commit_id, idempotency_key="publish-1")
assert candidate.status == ProviderPublicationStatus.WAITING_APPROVAL
assert candidate.commit_sha == exact_commit_sha
assert candidate.repo_url == "https://github.com/jerryjwres-hue/picotoopet-v2.0"
assert candidate.repository_slug == "jerryjwres-hue/picotoopet-v2.0"
assert candidate.base_ref == handoff_base_ref
assert candidate.base_commit == handoff_base_commit
assert candidate.remote_ref == f"refs/heads/picotoopet/commit-candidates/{candidate.publication_candidate_id}"
```

Also assert non-`commit_ready`, null commit SHA, non-GitHub repo URL, duplicate candidate, and conflicting idempotency key fail with fixed publication error codes.

- [ ] **Step 2: Write failing Migration 10 test**

Assert schema version advances to 10 and table/index/unique constraints exist for `provider_publication_candidates`.

- [ ] **Step 3: Run RED tests**

Run:

```bash
pytest -q tests/unit/providers/test_publication_service.py tests/unit/db/test_migration_010.py
```

Expected: FAIL because publication modules/Migration 10 do not exist.

- [ ] **Step 4: Implement Migration 10 and service**

Migration table includes publication candidate identity, commit/session/handoff provenance, status, repo/base/commit facts, fixed remote ref/branch, approval/idempotency keys, title/body digests, PR number/url/head SHA, validation JSON, failure code, timestamps, and preview JSON.

`prepare()` must join backwards from `provider_commit_candidates` through `provider_sessions` to `handoffs`, never accept repo/base facts as input, require exact `commit_ready`, create one `provider.publish.pr-create-v1` resource approval in the same DB transaction, and persist a complete preview projection.

- [ ] **Step 5: Extend approval safe summary keys**

Add only:

```python
"publication_candidate_id",
"repository_slug",
"base_ref",
"remote_ref",
"commit_sha",
"pr_title_digest",
"pr_body_digest",
"draft",
```

Do not add credential/token fields or full PR body.

- [ ] **Step 6: Run tests GREEN**

Run the same focused pytest command and require PASS.

- [ ] **Step 7: Commit**

Commit message:

```text
feat: add publication candidate facts for 2.3.17.1
```

---

### Task 2: Fixed Git publication executor and idempotent remote verification

**Files:**
- Create: `src/picotoopet_core/providers/publication_git.py`
- Test: `tests/unit/providers/test_publication_git.py`
- Test: `tests/integration/providers/test_publication_git_bare_remote.py`

**Interfaces:**
- Produces `PublicationGitError(code: str)`.
- Produces `PublicationGitPublisher(repository: Path)`.
- Methods:

```python
def verify_base(self, repo_url: str, base_ref: str, base_commit: str) -> None: ...
def ensure_remote_ref(self, repo_url: str, remote_ref: str, commit_sha: str) -> list[str]: ...
def read_remote_ref(self, repo_url: str, remote_ref: str) -> str | None: ...
```

- [ ] **Step 1: Write failing security tests**

Use temporary Git repositories and a bare remote. Install a malicious `.git/hooks/pre-push` that creates a sentinel file. Assert publication succeeds but sentinel never appears. Add repository config fixtures containing `remote.origin.pushurl`, `url.*.insteadOf`, `url.*.pushInsteadOf`, and `remote.*.vcs`; assert `PUBLICATION_GIT_CONFIG_POLICY` before network access.

- [ ] **Step 2: Write failing idempotence tests**

Assert:

```python
publisher.ensure_remote_ref(url, fixed_ref, commit_sha)
publisher.ensure_remote_ref(url, fixed_ref, commit_sha)  # exact reuse, no conflict
```

and assert a different pre-existing remote SHA raises `PUBLICATION_REMOTE_REF_CONFLICT` without overwrite.

- [ ] **Step 3: Write failing base-moved test**

Create bare remote with `refs/heads/<base_ref>` at a different SHA and require `PUBLICATION_BASE_MOVED` before candidate push.

- [ ] **Step 4: Run RED tests**

Run:

```bash
pytest -q tests/unit/providers/test_publication_git.py tests/integration/providers/test_publication_git_bare_remote.py
```

Expected: FAIL because executor does not exist.

- [ ] **Step 5: Implement fixed Git runner**

Use `subprocess.run(..., shell=False)` with a minimal environment and `GIT_TERMINAL_PROMPT=0`. The push argv is structurally fixed and includes `--no-verify`; never include `--force` or user-provided args. Parse `ls-remote --refs` output strictly and reject malformed/multiple matches.

- [ ] **Step 6: Run GREEN tests and commit**

Commit message:

```text
feat: add safe idempotent publication git runner
```

---

### Task 3: GitHub CLI readiness and Draft PR executor

**Files:**
- Create: `src/picotoopet_core/providers/github_readiness.py`
- Create: `src/picotoopet_core/providers/publication_github.py`
- Modify: `src/picotoopet_core/config/models.py`
- Modify: `src/picotoopet_core/config/loader.py`
- Test: `tests/unit/providers/test_github_readiness.py`
- Test: `tests/unit/providers/test_publication_github.py`

**Interfaces:**
- `GitHubReadinessProbe(executable: Path | None).ready() -> bool` performs only a fixed non-interactive `gh auth status` check and discards output.
- `PublicationGitHubClient(executable: Path)` exposes:

```python
def ensure_draft_pr(
    *, repository_slug: str, base_ref: str, head_branch: str,
    commit_sha: str, title: str, body: str
) -> DraftPrResult: ...
```

- [ ] **Step 1: Write fake-gh RED tests**

Generate a deterministic executable fixture that records argv and emits bounded JSON. Assert only fixed subcommands/flags are used, stdout is strictly bounded/parsed, and stderr is never persisted.

- [ ] **Step 2: Cover PR recovery/conflict cases**

Test: no PR -> create Draft -> verify; exact existing Draft -> adopt; existing non-Draft/wrong base/wrong `headRefOid`/multiple matching PRs -> `PUBLICATION_PR_CONFLICT`.

- [ ] **Step 3: Add configuration**

Add `github_cli_executable: Path | None` and environment loader `PICOTOO_GITHUB_CLI_EXECUTABLE`. Add `provider_publication_configured` property requiring provider repository and executable, separate from Codex execution readiness.

- [ ] **Step 4: Implement readiness/client and run GREEN**

Run:

```bash
pytest -q tests/unit/providers/test_github_readiness.py tests/unit/providers/test_publication_github.py
```

Commit message:

```text
feat: add fixed GitHub draft PR adapter
```

---

### Task 4: Publication Worker coordinator and crash recovery state machine

**Files:**
- Create: `src/picotoopet_core/providers/publication_execution.py`
- Modify: `src/picotoopet_core/cli.py`
- Test: `tests/integration/worker/test_publication_execution.py`
- Test: `tests/security/test_publication_execution_boundary.py`

**Interfaces:**
- Task type exactly `provider.publish.pr-create-v1`.
- Payload is a strict Pydantic model containing only publication ID and the immutable approved publication facts required by the handler.
- Coordinator exposes `enqueue_pending()` and `handler(task: TaskRecord) -> HandlerResult`.

- [ ] **Step 1: Write RED approval/state tests**

Assert pending/rejected/expired approvals never cause external executor calls. Approved candidates queue exactly one task with `max_attempts=1`.

- [ ] **Step 2: Write RED end-to-end fake publication test**

Use bare Git remote + fake `gh`. Drive:

```text
waiting_approval -> queued -> preflight -> pushing -> verifying_remote
-> remote_ready -> creating_pr -> verifying_pr -> pr_ready
```

Assert final DB stores exact remote branch, PR number/url/head SHA and validation checks.

- [ ] **Step 3: Write crash-window recovery tests**

Seed DB before state update while remote branch already exists at exact SHA; rerun handler and require recovery without duplicate push. Seed fake GitHub with exact Draft PR but DB missing PR facts; require adoption without duplicate create.

- [ ] **Step 4: Write no-merge/tag/release test**

Inspect fake Git/gh argv and assert no merge, tag, release, ready-for-review, force, delete-ref, or main mutation actions.

- [ ] **Step 5: Implement coordinator and register Worker handler**

Register only when publication configuration is complete. Add publication `enqueue_pending()` beside Provider/Adoption/Commit coordinators. Include task type in Worker capability output only when handler is actually registered.

- [ ] **Step 6: Run GREEN and commit**

Commit message:

```text
feat: execute approved publication candidates safely
```

---

### Task 5: Mac Core REST/API/service wiring

**Files:**
- Create: `src/picotoopet_core/api/routes/provider_publications.py`
- Modify: `src/picotoopet_core/api/app.py`
- Modify: `src/picotoopet_core/services.py`
- Modify: `src/picotoopet_core/providers/__init__.py`
- Test: `tests/integration/api/test_provider_publications_api.py`
- Test: `tests/contract/test_phase10e_publication_contract.py`

**Interfaces:**
- POST empty-body prepare endpoint.
- GET bounded list and exact-id endpoint.

- [ ] **Step 1: Write RED API tests**

Assert auth required, empty body required, `Idempotency-Key` required, only `commit_ready` accepted, no arbitrary publication parameters in OpenAPI, and list/read projections expose no credentials.

- [ ] **Step 2: Wire services/routes**

`Services` gains `provider_publications`. `create_app()` includes the route. Error mapping uses fixed safe messages/codes and never returns Git/gh stderr.

- [ ] **Step 3: Run API/contract GREEN and commit**

Commit message:

```text
feat: expose controlled publication API
```

---

### Task 6: Windows WPF publication candidate surface

**Files:**
- Modify: `windows/desktop/src/PicotooPet.Desktop.Core/Contracts/ProviderReviewContracts.cs`
- Modify: `windows/desktop/src/PicotooPet.Desktop.Core/Networking/MacCoreProviderReviewClient.cs`
- Modify: `windows/desktop/src/PicotooPet.Desktop/Services/ControlCenterSession.ProviderReview.cs`
- Modify gateway implementation/interface files used by `ProviderReviewViewModel`
- Modify: `windows/desktop/src/PicotooPet.Desktop/ViewModels/ProviderReviewViewModel.cs`
- Modify: `windows/desktop/src/PicotooPet.Desktop/Views/Pages/ProviderReviewPanel.xaml`
- Test: `windows/desktop/tests/PicotooPet.Desktop.Core.Tests/...ProviderPublication...`
- Test: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/...ProviderPublicationWpfSmokeTests.cs`
- Contract test: `tests/contract/test_windows_provider_publication_contract.py`

**Interfaces:**
- Add `ProviderPublicationCandidateRecord` matching Mac Core JSON.
- Add gateway operations `PreparePublicationAsync`, `GetPublicationCandidatesAsync`.
- ViewModel properties: `PublicationCandidates`, `SelectedPublicationCandidate`, `PublicationCandidateSummary`, `CanPreparePublication`, `PreparePublicationCommand`, `RefreshPublicationCommand`.

- [ ] **Step 1: Write RED source and behavior tests**

Assert publication prepare is enabled only for selected `commit_ready` with no existing Publication Candidate. Assert no TextBox/ComboBox binds repo/base/head/title/body/ref input. Assert button text is `准备 Push + Draft PR` and status copy contains `pr_ready != CI-green != merge-ready`.

- [ ] **Step 2: Add real WPF layout smoke**

Instantiate the real panel/ViewModel, call `Measure`, `Arrange`, `UpdateLayout`, pump Dispatcher DataBind, and fail on binding exceptions. Ensure publication block remains visible within existing layout/scroll behavior.

- [ ] **Step 3: Implement DTO/client/session/gateway/ViewModel/XAML**

Prepare call sends an empty body and only the path ID + idempotency header. PR URL is read-only text; do not auto-launch external browser in this version.

- [ ] **Step 4: Run Windows tests GREEN and commit**

Commit message:

```text
feat: add controlled publication WPF surface
```

---

### Task 7: Version, release contracts, and retained 2.3.16.3 regressions

**Files:**
- Modify: `src/picotoopet_core/product-version.txt`
- Modify: `contracts/release/project-goal-invariants.json`
- Modify exact current-version contract fixtures that assert `2.3.16.3`
- Modify current schema-version expectations from `9` to `10`
- Keep historical docs/evidence unchanged where values describe old releases.

- [ ] **Step 1: Set canonical product version to `2.3.17.1`**

Update source and release goal contract.

- [ ] **Step 2: Update only active current-version tests**

Do not globally replace historical evidence. Update exact product-version/UI/package fixtures and schema-health assertions that represent current runtime.

- [ ] **Step 3: Run full Python regression and lint**

Run:

```bash
pytest -q
ruff check src tests
```

Expected: all PASS.

- [ ] **Step 4: Commit**

Commit message:

```text
chore: align 2.3.17.1 release contracts
```

---

### Task 8: Draft PR, exact-head native CI, formal packages, and independent verification

**Files:**
- No new product feature files unless CI exposes a regression.
- Create delivery reports outside repo after formal artifacts exist.

- [ ] **Step 1: Open Draft PR**

Head: `feature/phase10e-controlled-publish-draft-pr-2.3.17.1`
Base: `fix/workflow-diagnostic-contract-2.3.16.3`

Keep Draft/Open/Unmerged. Do not target main.

- [ ] **Step 2: Run exact-head native gates**

Require:

- Mac Core Slice B CI
- Mac Worker Slice D CI
- Windows Control Center Slice D CI
- Phase 2.3 Slice D Windows Prebuilt Release

Any failure is diagnosed from root cause, fixed on the feature branch, then all impacted exact-head gates are rerun.

- [ ] **Step 3: Require deterministic network tests**

CI publication tests must use a local bare Git remote and fake GitHub CLI. Confirm no real GitHub branch/PR is produced by test execution.

- [ ] **Step 4: Download exact-head formal artifacts**

Collect Windows installer ZIP, Mac Core arm64 tar.gz, Mac Worker arm64 tar.gz, WPF evidence, OpenAPI evidence and SHA sidecars.

- [ ] **Step 5: Independently verify archives**

Check single safe root, no traversal/duplicates, manifest sizes/SHA, no unexpected Mac symlink/hardlink/special files, Windows PE AMD64, Mac arm64 contract, embedded wheel product version `2.3.17.1`, Migration 10, publication modules, and source/build tree equality.

- [ ] **Step 6: Produce manual acceptance document**

Acceptance must explicitly state that real Push/Draft PR is an external write and must not be performed merely to prove installer correctness. Safe local acceptance covers installation, readiness projection, prepare/approval UI boundaries, and the deterministic CI evidence. If the owner later chooses to publish a real `commit_ready` candidate, approval must show exact repo/base/commit/remote ref and resulting PR must be Draft with matching SHA.

- [ ] **Step 7: Final status check**

Confirm Draft PR remains unmerged, `main` unchanged, no tag/release created, and no real paid Codex/provider execution was used for CI acceptance.
