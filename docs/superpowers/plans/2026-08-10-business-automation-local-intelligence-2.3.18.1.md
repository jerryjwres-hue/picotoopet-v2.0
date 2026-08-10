# PicotooPet 2.3.18.1 Business Automation Bridge + Local Intelligence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first durable business automation loop from Windows producer Work Package v1 through Mac Core and the Mac-local `gpt-oss:20b` intelligence path to a validated Result Package v1 delivered back to Windows.

**Architecture:** Reuse the existing Windows↔Mac authenticated control connection, queue, workflow scheduler, capability routing, audit and result-store patterns. Add a bounded resumable business artifact protocol, Migration 11 durable business facts, deterministic preprocessing, a closed loopback-only local-intelligence adapter, deterministic quality validation, manual Deep-AI Handoff generation, and a native WPF Business Automation page with fixed Inbox/Outbox integration. Large raw datasets stay in Core-owned immutable disk storage; SQLite stores identity/state/digests only.

**Tech Stack:** Python 3.12, FastAPI/Pydantic, SQLite, httpx, existing Mac Worker queue/runtime, C#/.NET WPF, PowerShell prebuilt delivery, pytest, native Windows STA WPF smoke tests, GitHub Actions native Mac arm64 and Windows x64 gates.

## Global Constraints

- Product version is `2.3.18.1`; implementation base is exact 2.3.17.2 head `1025a8cf2ca1053dec2d6fac533b46f080e7b730` plus the approved design/plan commits.
- Database schema advances from `10` to `11`; no unrelated migrations.
- Primary Windows producer transport is `%LOCALAPPDATA%\\PicotooPet\\BusinessBridge\\Inbox`; completed results go to `%LOCALAPPDATA%\\PicotooPet\\BusinessBridge\\Outbox\\<work_package_id>\\`.
- Work Package v1 is a deterministic ZIP with exactly one top-level directory, strict `work-package.json`, max 256 MiB compressed, 512 MiB uncompressed, 64 inputs, 256 MiB per uncompressed file, and no traversal, duplicate paths, links, devices or executable payloads.
- Allowed producer input formats are JSON, JSONL/NDJSON, UTF-8 CSV and UTF-8 plain text only.
- Pilot profiles are exactly `reviews.voice_of_customer.v1` and `ideas.pattern_analysis.v1`; Work Packages cannot define prompts or new profiles.
- Large uploads use 4 MiB verified chunks and exact offsets/digests; identical retry chunks are idempotent, conflicting chunks fail closed.
- Mac local intelligence is a closed capability `local.intelligence.v1` with queue task type `business.local_intelligence.v1`.
- First adapter uses a trusted Mac-local loopback-only OpenAI-compatible endpoint and the configured local model identity; producer data cannot override endpoint/model/prompt/sampling/path/command/tool values.
- Default configured local model remains `gpt-oss:20b`; 2.3.18.1 does not install or download a model/runtime.
- The local model receives no shell, subprocess, browser, network tool, Git/GitHub, ComfyUI or arbitrary filesystem capability.
- One local intelligence inference executes at a time by default; a synthesis stage has at most two total model attempts (initial + one deterministic correction retry).
- Quality outcomes are `PASS`, `RETRY`, `NEEDS_DEEP_AI`, `NEEDS_HUMAN`, `REJECT`; repeated invalid output never loops indefinitely.
- `NEEDS_DEEP_AI` may generate a sanitized manual Handoff Package only; there is no automatic Web GPT/paid-AI call.
- 2.3.18.1 does not orchestrate ComfyUI and does not change the 2.3.17.x controlled Git publication boundary.
- No user PC/Mac source compilation or SDK installation is required by delivery packages.
- Final delivery requires exact-head Mac Core, Mac Worker, Windows WPF and Windows Prebuilt native gates, formal precompiled packages, SHA-256 sidecars, archive/manifest verification and a Chinese manual acceptance guide.
- PR remains Draft/Open/Unmerged; do not merge `main`, tag or create GitHub Release.

---

## File Structure

### New Python business domain

- `src/picotoopet_core/business/models.py` — strict Work/Result/Run/Handoff contracts and enums.
- `src/picotoopet_core/business/archive.py` — safe Work Package ZIP structure/hash validation.
- `src/picotoopet_core/business/repository.py` — Migration 11 durable business fact CRUD and state transitions.
- `src/picotoopet_core/business/store.py` — Core-owned staging/immutable package/result/handoff disk storage.
- `src/picotoopet_core/business/upload.py` — resumable 4 MiB chunk sessions, offset/digest verification, finalize.
- `src/picotoopet_core/business/preprocess.py` — deterministic JSON/JSONL/CSV/text parsing, dedupe, statistics, evidence selection and chunk context generation.
- `src/picotoopet_core/business/profiles.py` — closed profile registry, source-controlled prompts, result schemas and bounds.
- `src/picotoopet_core/business/local_intelligence.py` — loopback-only HTTP adapter and strict JSON inference response handling.
- `src/picotoopet_core/business/quality.py` — deterministic schema/evidence/leakage/output-bound validation and retry/attention decision.
- `src/picotoopet_core/business/execution.py` — Worker handler/coordinator for preprocessing → local inference → quality → result/handoff state.
- `src/picotoopet_core/business/service.py` — Core orchestration facade for prepare/upload/list/get/cancel/result/handoff actions.
- `src/picotoopet_core/api/routes/business_automation.py` — authenticated bounded business package/result/Handoff API.
- `src/picotoopet_core/db/migration_011.py` — schema 11 business tables/indexes.

### Existing Python files modified

- `src/picotoopet_core/db/database.py` — register Migration 11.
- `src/picotoopet_core/config/paths.py` — Core-owned business staging/artifact/result/handoff roots.
- `src/picotoopet_core/config/models.py` — trusted local-intelligence endpoint/model/time/output bounds and redaction.
- `src/picotoopet_core/services.py` — construct business repository/store/service.
- `src/picotoopet_core/api/app.py` — register business automation routes and bounded body handling.
- `src/picotoopet_core/cli.py` — Worker capability/handler registration only when loopback local-intelligence config is healthy.
- `src/picotoopet_core/worker/handlers.py` and/or Worker assembly path — include closed `business.local_intelligence.v1` handler without dynamic producer-selected handlers.
- `src/picotoopet_core/product-version.txt` and active version/release fixtures — `2.3.18.1`.

### Windows files

- `windows/desktop/src/PicotooPet.Desktop.Core/Contracts/BusinessAutomationContracts.cs` — typed Work Package/upload/run/result/Handoff DTOs.
- `windows/desktop/src/PicotooPet.Desktop.Core/Networking/MacCoreClient.BusinessAutomation.cs` — typed business API client.
- `windows/desktop/src/PicotooPet.Desktop/Services/BusinessBridgeService.cs` — fixed Inbox scan/quarantine/upload/Outbox delivery with atomic local files.
- `windows/desktop/src/PicotooPet.Desktop/Services/ControlCenterSession.BusinessAutomation.cs` — paired-session operations.
- `windows/desktop/src/PicotooPet.Desktop/ViewModels/BusinessAutomationPageViewModel.cs` — fixed actions and status only.
- `windows/desktop/src/PicotooPet.Desktop/Views/Pages/BusinessAutomationPage.xaml` — native WPF page.
- `windows/desktop/src/PicotooPet.Desktop/ViewModels/ShellViewModel.cs`, `App.xaml`, navigation registration — add Business Automation page.

### Tests/fixtures

- `tests/business/` — Python unit/integration coverage for archive, upload, preprocessing, adapter, quality, recovery and service.
- `tests/integration/api/test_business_automation_api.py` — end-to-end API contract.
- `tests/integration/worker/test_business_local_intelligence_worker.py` — queue/Worker fake-model end-to-end.
- `tests/fixtures/business/` — bounded review and inspiration Work Package fixtures plus fake local-model responses.
- `tests/contract/test_business_automation_23181_contract.py` — frozen security/version/surface contract.
- `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/BusinessAutomationWpfSmokeTests.cs` — real STA Measure/Arrange/UpdateLayout + fixed-action smoke.
- Windows client/unit smoke additions in existing smoke project.

---

### Task 1: Migration 11, business models and immutable storage roots

**Files:**
- Create: `src/picotoopet_core/db/migration_011.py`
- Create: `src/picotoopet_core/business/__init__.py`
- Create: `src/picotoopet_core/business/models.py`
- Create: `src/picotoopet_core/business/repository.py`
- Modify: `src/picotoopet_core/db/database.py`
- Modify: `src/picotoopet_core/config/paths.py`
- Test: `tests/business/test_business_repository.py`
- Test: `tests/contract/test_business_automation_23181_contract.py`

**Interfaces:**
- Produces `BusinessWorkPackageStatus`, `BusinessAnalysisProfile`, `BusinessQualityOutcome`, `WorkPackageManifest`, `WorkPackageRecord`, `BusinessResultPackageRecord`, `DeepAiHandoffRecord`.
- Produces `BusinessRepository(database)` with `create_or_get_work_package`, `get_work_package`, `list_work_packages`, `transition_work_package`, run/result/handoff persistence methods.
- Produces `RuntimePaths.business_root`, `business_staging_dir`, `business_packages_dir`, `business_results_dir`, `business_handoffs_dir`.

- [ ] **Step 1: Write RED persistence and strict-model tests**

```python
def test_migration_11_creates_business_tables(database):
    tables = {row["name"] for row in database.fetchall("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {
        "business_work_packages", "business_artifacts", "business_upload_sessions",
        "business_upload_chunks", "local_intelligence_runs", "local_intelligence_chunks",
        "business_result_packages", "deep_ai_handoffs",
    } <= tables


def test_work_package_manifest_rejects_arbitrary_profile():
    with pytest.raises(ValidationError):
        WorkPackageManifest.model_validate({**VALID_MANIFEST, "analysis_profile": "free.prompt.v1"})
```

- [ ] **Step 2: Run RED tests**

Run: `pytest tests/business/test_business_repository.py tests/contract/test_business_automation_23181_contract.py -q`
Expected: FAIL because Migration 11/business models do not exist.

- [ ] **Step 3: Implement schema 11, strict enums/models, repository and managed paths**

Migration 11 must use TEXT IDs/digests, INTEGER sizes/offsets, JSON TEXT for bounded structured facts, UNIQUE constraints for package/idempotency/digest identities, and indexes on state/created time. Raw business data must not be SQLite BLOBs.

- [ ] **Step 4: Run focused tests**

Run: `pytest tests/business/test_business_repository.py tests/contract/test_business_automation_23181_contract.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/picotoopet_core/db src/picotoopet_core/business src/picotoopet_core/config/paths.py tests/business tests/contract/test_business_automation_23181_contract.py
git commit -m "feat: add durable business automation facts"
```

### Task 2: Safe Work Package archive validator and immutable business store

**Files:**
- Create: `src/picotoopet_core/business/archive.py`
- Create: `src/picotoopet_core/business/store.py`
- Test: `tests/business/test_work_package_archive.py`
- Fixtures: `tests/fixtures/business/reviews-valid/`, `tests/fixtures/business/ideas-valid/`

**Interfaces:**
- Produces `validate_work_package_archive(path: Path) -> ValidatedWorkPackage`.
- Produces `BusinessArtifactStore(paths)` with staging/finalize/read-result/write-result/write-handoff methods; all caller-supplied names are treated as logical IDs, not paths.

- [ ] **Step 1: Write RED malicious archive tests**

```python
@pytest.mark.parametrize("member", ["../escape.txt", "/tmp/escape.txt", "root/../../escape.txt"])
def test_archive_rejects_traversal(tmp_path, member):
    archive = make_zip(tmp_path, {member: b"x"})
    with pytest.raises(WorkPackageArchiveError, match="unsafe_path"):
        validate_work_package_archive(archive)


def test_archive_rejects_executable_payload(tmp_path):
    archive = make_valid_work_package(tmp_path, extra={"inputs/tool.exe": b"MZ"})
    with pytest.raises(WorkPackageArchiveError, match="executable"):
        validate_work_package_archive(archive)
```

Also test duplicate archive names, >1 top-level root, >64 inputs, compressed/uncompressed/single-file limits, links/special entries, undeclared files, manifest hash/size mismatch, disallowed media types and invalid UTF-8 for text formats.

- [ ] **Step 2: Run RED archive tests**

Run: `pytest tests/business/test_work_package_archive.py -q`
Expected: FAIL because validator/store do not exist.

- [ ] **Step 3: Implement safe validator/store**

Use `zipfile.ZipFile.infolist()`, normalize POSIX member names without filesystem resolution, reject duplicate normalized paths, reject external attributes representing links/devices, stream hashes/sizes, and extract only after complete validation into a Core-generated staging directory. Final package location derives from package UUID + source SHA, never from archive member names.

- [ ] **Step 4: Run archive tests**

Run: `pytest tests/business/test_work_package_archive.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/picotoopet_core/business/archive.py src/picotoopet_core/business/store.py tests/business/test_work_package_archive.py tests/fixtures/business
git commit -m "feat: validate immutable business work packages"
```

### Task 3: Resumable 4 MiB upload protocol and authenticated API

**Files:**
- Create: `src/picotoopet_core/business/upload.py`
- Create: `src/picotoopet_core/business/service.py`
- Create: `src/picotoopet_core/api/routes/business_automation.py`
- Modify: `src/picotoopet_core/services.py`
- Modify: `src/picotoopet_core/api/app.py`
- Test: `tests/business/test_business_upload.py`
- Test: `tests/integration/api/test_business_automation_api.py`

**Interfaces:**
- Produces `BusinessAutomationService.prepare_upload(manifest, source_digest, size_bytes)`, `write_chunk(session_id, offset, digest, body)`, `finalize_upload(session_id)`, list/get/cancel/result/handoff operations.
- API uses fixed endpoints under `/api/v1/business/...`; chunk body max is `4 MiB` except final short chunk.

- [ ] **Step 1: Write RED idempotency/resume/conflict/API auth tests**

```python
def test_exact_chunk_retry_is_idempotent(service, prepared):
    first = service.write_chunk(prepared.upload_session_id, 0, sha256(CHUNK), CHUNK)
    second = service.write_chunk(prepared.upload_session_id, 0, sha256(CHUNK), CHUNK)
    assert first == second


def test_same_idempotency_key_different_source_digest_conflicts(service):
    service.prepare_upload(MANIFEST, digest("a"), 1)
    with pytest.raises(BusinessConflictError):
        service.prepare_upload(MANIFEST.model_copy(update={"package_id": NEW_ID}), digest("b"), 1)
```

API tests must verify missing/bad bearer token is rejected and producer cannot provide a Core filesystem path/model/endpoint/prompt.

- [ ] **Step 2: Run RED upload/API tests**

Run: `pytest tests/business/test_business_upload.py tests/integration/api/test_business_automation_api.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement durable upload sessions/API**

Prepare creates/reuses identity facts. Chunk writes require exact expected offset or exact previously verified chunk identity. Finalize verifies total size + archive SHA before archive validation and immutable promotion; only then transition `Receiving → Validating → Ready`.

- [ ] **Step 4: Run focused tests**

Run: `pytest tests/business/test_business_upload.py tests/integration/api/test_business_automation_api.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/picotoopet_core/business/upload.py src/picotoopet_core/business/service.py src/picotoopet_core/api/routes/business_automation.py src/picotoopet_core/services.py src/picotoopet_core/api/app.py tests/business/test_business_upload.py tests/integration/api/test_business_automation_api.py
git commit -m "feat: add resumable business package upload"
```

### Task 4: Deterministic preprocessing and closed profile registry

**Files:**
- Create: `src/picotoopet_core/business/preprocess.py`
- Create: `src/picotoopet_core/business/profiles.py`
- Test: `tests/business/test_business_preprocess.py`
- Test: `tests/business/test_business_profiles.py`

**Interfaces:**
- Produces `AnalysisProfileDefinition` registry keyed only by the two pilot profile IDs.
- Produces `preprocess_work_package(validated, profile) -> PreprocessedAnalysis` with immutable digest, aggregate facts, evidence records, chunks and stable source IDs.

- [ ] **Step 1: Write RED determinism/evidence tests**

```python
def test_review_preprocessing_is_deterministic(validated_reviews):
    first = preprocess_work_package(validated_reviews, profile("reviews.voice_of_customer.v1"))
    second = preprocess_work_package(validated_reviews, profile("reviews.voice_of_customer.v1"))
    assert first.digest == second.digest
    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_duplicate_records_preserve_duplicate_count(validated_reviews):
    result = preprocess_work_package(validated_reviews, profile("reviews.voice_of_customer.v1"))
    assert result.aggregate_facts["duplicate_records"] > 0
```

Cover JSON, JSONL, CSV, text, Unicode/newline normalization, stable evidence IDs, missing timestamp behavior, deterministic chunk boundaries and no invented fields.

- [ ] **Step 2: Run RED preprocess/profile tests**

Run: `pytest tests/business/test_business_preprocess.py tests/business/test_business_profiles.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement bounded deterministic profilers**

Do exact duplicate removal/counting and deterministic record selection; do not add embedding/vector dependencies in 2.3.18.1. Chunking must be reproducible from profile constants and normalized record order.

- [ ] **Step 4: Run focused tests**

Run: `pytest tests/business/test_business_preprocess.py tests/business/test_business_profiles.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/picotoopet_core/business/preprocess.py src/picotoopet_core/business/profiles.py tests/business/test_business_preprocess.py tests/business/test_business_profiles.py
git commit -m "feat: add deterministic business preprocessing"
```

### Task 5: Loopback-only OSS 20B Local Intelligence Adapter

**Files:**
- Create: `src/picotoopet_core/business/local_intelligence.py`
- Modify: `src/picotoopet_core/config/models.py`
- Test: `tests/business/test_local_intelligence_adapter.py`

**Interfaces:**
- Produces `LocalIntelligenceConfig` derived only from trusted `AppSettings`.
- Produces `OpenAiCompatibleLocalIntelligenceAdapter.run(profile, context, correction=None) -> dict[str, object]`.
- Uses `/v1/chat/completions` on a validated loopback HTTP endpoint; request model defaults to trusted `gpt-oss:20b` configuration.

- [ ] **Step 1: Write RED loopback/security/request tests**

```python
@pytest.mark.parametrize("url", ["https://example.com/v1", "http://192.168.1.20:11434/v1"])
def test_adapter_rejects_non_loopback_endpoint(url):
    with pytest.raises(ValueError, match="loopback"):
        LocalIntelligenceConfig(base_url=url, model_id="gpt-oss:20b")


def test_adapter_uses_fixed_profile_prompt_and_model(fake_http, profile, context):
    adapter = OpenAiCompatibleLocalIntelligenceAdapter(CONFIG, client=fake_http)
    adapter.run(profile, context)
    request = fake_http.last_json
    assert request["model"] == "gpt-oss:20b"
    assert "tools" not in request
    assert request["response_format"] == {"type": "json_object"}
```

Test response code/timeout/invalid JSON/extra prose/output size failures and config redaction.

- [ ] **Step 2: Run RED adapter tests**

Run: `pytest tests/business/test_local_intelligence_adapter.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement minimal adapter**

Use a dedicated `httpx.Client`; validate hostname/IP resolves only to loopback and reject userinfo/non-http(s) schemes. Do not inherit producer-provided URLs or headers. Send source-controlled system prompt + bounded Analysis Context as user data, fixed temperature/output settings from profile/config, no tools/functions.

- [ ] **Step 4: Run adapter tests**

Run: `pytest tests/business/test_local_intelligence_adapter.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/picotoopet_core/business/local_intelligence.py src/picotoopet_core/config/models.py tests/business/test_local_intelligence_adapter.py
git commit -m "feat: add bounded local intelligence adapter"
```

### Task 6: Deterministic quality gate, one correction retry, Result Package and Deep-AI Handoff

**Files:**
- Create: `src/picotoopet_core/business/quality.py`
- Extend: `src/picotoopet_core/business/store.py`
- Extend: `src/picotoopet_core/business/repository.py`
- Test: `tests/business/test_business_quality.py`
- Test: `tests/business/test_business_result_package.py`

**Interfaces:**
- Produces `BusinessQualityGate.evaluate(profile, preprocessed, model_result) -> BusinessQualityDecision`.
- Produces deterministic Result Package manifest and sanitized Deep-AI Handoff writer.

- [ ] **Step 1: Write RED evidence/schema/leakage/retry tests**

```python
def test_quality_rejects_unknown_evidence_id(gate, preprocessed, valid_result):
    tampered = deepcopy(valid_result)
    tampered["opportunities"][0]["evidence_ids"] = ["missing-record"]
    decision = gate.evaluate(PROFILE, preprocessed, tampered)
    assert decision.outcome == BusinessQualityOutcome.RETRY


def test_second_invalid_attempt_becomes_needs_deep_ai(coordinator_fixture):
    final = coordinator_fixture.run_with_results([INVALID_SCHEMA, INVALID_SCHEMA])
    assert final.quality_outcome == BusinessQualityOutcome.NEEDS_DEEP_AI
    assert final.handoff_id is not None
```

Also verify no prompt/system metadata leakage, counts/confidence bounds, all evidence IDs resolvable, Handoff excludes raw full dataset/absolute paths/secrets and includes exact return schema + digests.

- [ ] **Step 2: Run RED quality/result tests**

Run: `pytest tests/business/test_business_quality.py tests/business/test_business_result_package.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement deterministic quality/result/handoff builders**

Only schema/evidence/format-repairable failures may request one correction retry. Semantic uncertainty/contradiction/insufficient support becomes attention directly. PASS writes immutable Result Package bound to source/preprocess/model/template/quality identities.

- [ ] **Step 4: Run focused tests**

Run: `pytest tests/business/test_business_quality.py tests/business/test_business_result_package.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/picotoopet_core/business/quality.py src/picotoopet_core/business/store.py src/picotoopet_core/business/repository.py tests/business/test_business_quality.py tests/business/test_business_result_package.py
git commit -m "feat: validate business intelligence results"
```

### Task 7: Mac Worker execution and crash-safe business orchestration

**Files:**
- Create: `src/picotoopet_core/business/execution.py`
- Modify: `src/picotoopet_core/cli.py`
- Modify: Worker handler assembly as required without opening dynamic task types
- Test: `tests/integration/worker/test_business_local_intelligence_worker.py`
- Test: `tests/business/test_business_execution_recovery.py`

**Interfaces:**
- Produces closed Worker handler for task type `business.local_intelligence.v1` and capability `local.intelligence.v1`.
- Task payload contains only `work_package_id`, `source_digest`, `analysis_profile` and trusted run identity/digest fields.

- [ ] **Step 1: Write RED end-to-end fake-model Worker tests**

```python
def test_worker_completes_review_package_with_fake_local_model(business_fixture):
    business_fixture.enqueue_ready_package()
    cycle = business_fixture.worker.run_once()
    record = business_fixture.service.get_work_package(business_fixture.package_id)
    assert cycle.succeeded is True
    assert record.status.value == "Completed"
    assert business_fixture.service.get_result(record.work_package_id).quality_outcome.value == "PASS"
```

Cover stale capability, Worker crash/lease recovery, two-attempt inference ceiling, cancel, exact completed-result reuse, local endpoint unavailable → safe attention/failure, and no dynamic task types.

- [ ] **Step 2: Run RED Worker tests**

Run: `pytest tests/integration/worker/test_business_local_intelligence_worker.py tests/business/test_business_execution_recovery.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement coordinator/handler/capability registration**

Core `Ready` packages enqueue exactly one logical business intelligence task with deterministic idempotency key. Worker preprocesses from Core-managed immutable package only, performs bounded chunk/model calls, persists per-chunk/run facts, quality-checks, and writes Result/Handoff. Recovery reads durable facts before any repeated inference and never exceeds configured model-attempt budget.

- [ ] **Step 4: Run Worker integration tests**

Run: `pytest tests/integration/worker/test_business_local_intelligence_worker.py tests/business/test_business_execution_recovery.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/picotoopet_core/business/execution.py src/picotoopet_core/cli.py src/picotoopet_core/worker tests/integration/worker/test_business_local_intelligence_worker.py tests/business/test_business_execution_recovery.py
git commit -m "feat: execute local business intelligence on Mac Worker"
```

### Task 8: Windows Inbox/Outbox bridge and typed client

**Files:**
- Create: `windows/desktop/src/PicotooPet.Desktop.Core/Contracts/BusinessAutomationContracts.cs`
- Create: `windows/desktop/src/PicotooPet.Desktop.Core/Networking/MacCoreClient.BusinessAutomation.cs`
- Create: `windows/desktop/src/PicotooPet.Desktop/Services/ControlCenterSession.BusinessAutomation.cs`
- Create: `windows/desktop/src/PicotooPet.Desktop/Services/BusinessBridgeService.cs`
- Test: existing Windows smoke project files plus `BusinessBridgeSmokeTests.cs`

**Interfaces:**
- `BusinessBridgeService` owns only fixed `%LOCALAPPDATA%\PicotooPet\BusinessBridge` Inbox/Outbox/Quarantine roots.
- Service scans complete ZIPs, validates local bounded metadata, prepares Core upload, sends 4 MiB chunks, finalizes, and delivers exact Result Package to Outbox atomically.

- [ ] **Step 1: Write RED Windows bridge tests**

C# smoke must verify exact chunk offsets, restart resume, same package no duplicate upload, corrupt package quarantined without overwriting a good package, and Outbox temp→atomic rename.

```csharp
SmokeAssert.True(requests.All(r => r.BodyLength <= 4 * 1024 * 1024), "Business upload chunk exceeded 4 MiB");
SmokeAssert.True(!source.Contains("Process.Start"), "Business Bridge must not execute producer content");
```

- [ ] **Step 2: Run native Windows RED smoke workflow**

Run the repository's existing Windows Control Center CI entry targeting the new smoke class; expected RED is compile/test failure because typed contracts/service do not exist.

- [ ] **Step 3: Implement typed client and durable fixed bridge directories**

Do not host a new local HTTP server/service in 2.3.18.1. Producer integration is filesystem-only. ZIP names are untrusted; package identity comes from validated manifest. Quarantine paths use Core/bridge-generated IDs.

- [ ] **Step 4: Run Windows smoke/build locally in CI path**

Expected: new bridge tests PASS, warnings-as-errors build PASS.

- [ ] **Step 5: Commit**

```bash
git add windows/desktop/src/PicotooPet.Desktop.Core windows/desktop/src/PicotooPet.Desktop/Services windows/desktop/tests
git commit -m "feat: add Windows business package bridge"
```

### Task 9: Native WPF Business Automation page

**Files:**
- Create: `windows/desktop/src/PicotooPet.Desktop/ViewModels/BusinessAutomationPageViewModel.cs`
- Create: `windows/desktop/src/PicotooPet.Desktop/Views/Pages/BusinessAutomationPage.xaml`
- Modify: `windows/desktop/src/PicotooPet.Desktop/ViewModels/ShellViewModel.cs`
- Modify: `windows/desktop/src/PicotooPet.Desktop/App.xaml`
- Modify navigation registration files as required
- Create: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/BusinessAutomationWpfSmokeTests.cs`
- Modify: smoke `Program.cs`

**Interfaces:**
- Page shows package producer/project/profile/status/upload/local-model/quality/result/Handoff facts.
- Fixed commands only: Refresh, Submit/Retry local Inbox item, Cancel nonterminal package, Deliver/Redeliver result, Export safe manual Handoff.

- [ ] **Step 1: Write RED real-WPF layout/binding/security smoke**

```csharp
page.Measure(new Size(1100, 800));
page.Arrange(new Rect(0, 0, 1100, 800));
page.UpdateLayout();
SmokeAssert.True(page.ActualWidth > 0 && page.ActualHeight > 0, "Business Automation page did not layout");
```

Source-contract assertions must reject `PromptInput`, `ModelInput`, `EndpointInput`, `PathInput`, `CommandInput`, `WebView`, `localhost` browser UI and arbitrary task-type fields.

- [ ] **Step 2: Run native Windows RED WPF smoke**

Expected: FAIL because page/viewmodel are missing.

- [ ] **Step 3: Implement WPF page/viewmodel/navigation**

All data bindings for record/read-only values must be explicit `Mode=OneWay`; mutable selection uses `TwoWay` only where required. Do not duplicate large raw dataset content into UI.

- [ ] **Step 4: Run real STA WPF Measure/Arrange/UpdateLayout + warnings-as-errors build**

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add windows/desktop/src/PicotooPet.Desktop windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests
git commit -m "feat: add business automation WPF control surface"
```

### Task 10: Version 2.3.18.1, package/install configuration and full contract freeze

**Files:**
- Modify: `src/picotoopet_core/product-version.txt`
- Modify: `contracts/release/project-goal-invariants.json`
- Modify all active product-version fixtures/assertions discovered by repository-wide audit
- Modify Mac Core/Worker installers only as needed to preserve trusted local-intelligence configuration and create new managed business directories
- Extend: `tests/contract/test_business_automation_23181_contract.py`
- Add installer/packaging contract tests as needed

**Interfaces:**
- Canonical product version `2.3.18.1` on Core/Worker/Windows surfaces.
- Mac Worker installer preserves existing provider/Codex/GitHub values and local-intelligence configuration; it does not install Ollama/model/runtime.

- [ ] **Step 1: Write/extend RED release contracts and stale-version audit**

Contract must assert schema 11, Business Automation routes/page, no automatic paid-AI/ComfyUI integration, local model endpoint is configuration-only/loopback-only, and package installers do not install models/runtimes.

- [ ] **Step 2: Run repository-wide product-version search and full Python regression before bump**

Audit active `2.3.17.2` literals. Update active runtime/release fixtures atomically; leave historical docs/evidence unchanged.

- [ ] **Step 3: Bump canonical product version and installer manifests to `2.3.18.1`**

- [ ] **Step 4: Run full Python regression and Windows source contracts**

Run: `pytest -q`
Expected: PASS on current feature head.

- [ ] **Step 5: Commit**

```bash
git add src contracts tests scripts deploy windows
git commit -m "chore: roll business automation into 2.3.18.1"
```

### Task 11: Exact-head native CI, security regression, package generation and independent verification

**Files:**
- Modify only files required by concrete native CI failures.
- Create delivery verification artifacts outside the repository after CI PASS.

**Interfaces:**
- Final exact feature head is immutable after artifact generation.
- Required native workflows: Mac Core Slice B CI, Mac Worker Slice D CI, Windows Control Center Slice D CI, Phase 2.3 Slice D Windows Prebuilt Release.

- [ ] **Step 1: Create/maintain a stacked Draft PR from the 2.3.18.1 feature branch**

Base it on exact accepted 2.3.17.2 branch/head lineage, not `main`. Keep Draft/Open/Unmerged.

- [ ] **Step 2: Trigger/wait for the four exact-head native gates**

Do not accept earlier-head results. On failure, inspect the concrete failed step, add/adjust RED regression where necessary, implement minimal correction, commit and restart exact-head validation.

- [ ] **Step 3: Verify required security regressions**

Must include malicious ZIP traversal/duplicates/executable payload, upload offset/digest conflict, idempotency conflict, non-loopback model endpoint, producer prompt/model/endpoint injection, invalid model JSON, forged evidence IDs, result leakage, retry ceiling, Worker crash recovery, Windows bridge quarantine, and real WPF layout/binding tests.

- [ ] **Step 4: Download formal exact-head artifacts and independently inspect packages**

For each formal package recompute SHA-256; verify safe single top-level root, no traversal/duplicate/link/special-file payloads, manifest file hashes/sizes, correct Windows AMD64/Mac arm64 targets, `product_version=2.3.18.1`, schema 11/business modules in embedded wheel, no user-machine source build, no model/runtime installer payload, and correct INSTALL/VERIFY/ROLLBACK files.

- [ ] **Step 5: Generate final delivery set**

Create:

- Windows 2.3.18.1 prebuilt installer ZIP + SHA sidecar
- Mac Core 2.3.18.1 arm64 package + SHA sidecar
- Mac Worker 2.3.18.1 arm64 package + SHA sidecar
- combined SHA manifest
- independent verification JSON
- Chinese manual acceptance guide
- two sample producer Work Package v1 fixtures (reviews and ideas) that contain no user private data

- [ ] **Step 6: Manual acceptance contract**

Acceptance must verify: upgrade preserves connectivity/config; schema 11; safe diagnostic workflow non-regression; valid sample review/idea package enters Inbox, resumes upload, executes fake/real local `gpt-oss:20b` only when configured, produces Result Package in Outbox; invalid package is quarantined; no raw dataset leaks to logs/UI; Deep-AI case exports sanitized Handoff only; no paid AI, ComfyUI, arbitrary shell/path/prompt/model input, Git publication or `main` write occurs.

---

## Plan Self-Review

- Spec coverage: Work Package, fixed Inbox/Outbox, resumable upload, Migration 11, deterministic preprocessing, two pilot profiles, loopback local model, closed Worker capability, quality/retry, Deep-AI Handoff, Result Package, recovery, WPF, security, versioning, CI and packages are each mapped to a task.
- Scope: ComfyUI, Creative Intelligence, automated paid-AI, embeddings/vector database and new Windows background service remain explicitly outside 2.3.18.1.
- Type consistency: profile IDs, task type `business.local_intelligence.v1`, capability `local.intelligence.v1`, schema `11`, product version `2.3.18.1`, Work Package/Result Package v1 names and fixed state terminology are consistent across tasks.
- Placeholder scan: no implementation `TBD`/`TODO` steps; every task defines concrete files, interfaces, RED command/expectation, GREEN behavior and commit boundary.
