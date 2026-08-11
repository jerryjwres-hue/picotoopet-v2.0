# PicotooPet 2.3.19.1 Creative Intelligence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform one to eight validated 2.3.18.1 PASS Result Packages from one project into an immutable, evidence-traceable Creative Package v1 containing ranked ideas, a creative brief, structured script, and renderer-neutral Shot Plan, primarily using the Mac-local `gpt-oss:20b` path.

**Architecture:** Reuse the 2.3.18.1 business Result Package store and loopback local-intelligence adapter. Add Migration 12 creative facts, stable source-finding normalization, four independently checkpointed creative stages with strict schemas/quality gates, a closed Mac Worker creative capability, bounded Core APIs/package storage, and a separated Creative Intelligence panel inside the existing Windows Business Automation surface. ComfyUI and automatic paid AI remain out of scope.

**Tech Stack:** Python 3.12, FastAPI/Pydantic, SQLite, existing httpx loopback OpenAI-compatible adapter, existing Mac Worker queue/runtime, C#/.NET WPF, pytest, native Windows STA WPF smoke tests, GitHub Actions native macOS arm64 and Windows x64 gates.

## Global Constraints

- Product version is `2.3.19.1`; database schema is `12`.
- Implementation lineage is the approved 2.3.19.1 design branch stacked on exact 2.3.18.1 feature head `524c6e38a56ca489d6fbef25e42dca9c81bf8525`.
- Creative profile is exactly `creative.content_plan.v1` with stages `idea_ranking.v1`, `creative_brief.v1`, `script.v1`, `shot_plan.v1`.
- A job consumes 1–8 immutable 2.3.18.1 Result Packages, all `quality_outcome=PASS`, source Work Package `Completed`, and all from the same `project_key`.
- 2.3.18.1 findings have no standalone finding ID. Core derives `source_finding_ref = <result_package_id>:finding:<rank>` and binds canonical finding digest + source evidence IDs.
- Duplicate/invalid finding ranks or unresolvable evidence make a source result ineligible.
- Optional `creative_objective` is untrusted business intent, max 2000 UTF-8 chars; it cannot alter model/endpoint/system prompt/template/tool/path/command/retry/safety policy.
- Mac Worker closed capability is `creative.intelligence.v1`; task type is `creative.content_plan.v1`.
- Local model transport remains trusted Mac-loopback-only OpenAI-compatible HTTP; default model identity remains `gpt-oss:20b` unless trusted Mac-side configuration changes it.
- Model receives no shell, subprocess, browser/network tools, Git/GitHub, arbitrary filesystem-write, paid-AI, or ComfyUI authority.
- Each creative stage permits at most two total model attempts: initial + one deterministic correction retry for schema/provenance/format-repairable failures.
- Persisted valid stages are reused after restart; no unbounded regeneration.
- Success state is `creative_ready`, explicitly not rendered or publish-ready.
- No ComfyUI execution/workflow JSON, automatic paid AI, Git publication, `main` merge, tag, or GitHub Release.
- Final delivery requires exact-head Mac Core, Mac Worker, Windows WPF, Windows Prebuilt gates plus precompiled packages/SHA/independent verification/Chinese manual acceptance.
- User machines do not compile source or install SDKs.

---

## File Structure

### New Python creative domain

- `src/picotoopet_core/creative/__init__.py` — package marker.
- `src/picotoopet_core/creative/models.py` — creative enums, source normalization models, stage result schemas, job/package/handoff records.
- `src/picotoopet_core/creative/profiles.py` — closed creative profile/stage template registry and fixed bounds.
- `src/picotoopet_core/creative/repository.py` — Migration 12 creative CRUD/idempotency/stage persistence.
- `src/picotoopet_core/creative/source.py` — normalize eligible 18.1 Result Packages into stable source findings/evidence sets.
- `src/picotoopet_core/creative/quality.py` — deterministic stage/provenance/claim/shot coverage gates.
- `src/picotoopet_core/creative/store.py` — immutable Creative Package / manual Handoff ZIPs under Core-managed roots.
- `src/picotoopet_core/creative/execution.py` — Mac Worker four-stage coordinator/recovery/attempt ceilings.
- `src/picotoopet_core/creative/service.py` — Mac Core create/list/get/cancel/package/handoff facade and queue creation.
- `src/picotoopet_core/api/routes/creative_intelligence.py` — authenticated bounded creative APIs.
- `src/picotoopet_core/db/migration_012.py` — schema 12 creative tables/indexes.

### Existing Python files modified

- `src/picotoopet_core/db/database.py` — register Migration 12.
- `src/picotoopet_core/config/paths.py` — managed creative package/handoff roots.
- `src/picotoopet_core/services.py` — construct creative repository/store/service.
- `src/picotoopet_core/api/app.py` — register creative router.
- `src/picotoopet_core/cli.py` — register creative Worker capability only when 18.1 local model health is true.
- `src/picotoopet_core/product-version.txt` — `2.3.19.1`.
- `contracts/release/project-goal-invariants.json` and active version/schema fixtures — creative boundary/version 19.1/schema 12.

### Windows files

- `windows/desktop/src/PicotooPet.Desktop.Core/Contracts/CreativeIntelligenceContracts.cs` — typed creative DTOs.
- `windows/desktop/src/PicotooPet.Desktop.Core/Networking/MacCoreClient.CreativeIntelligence.cs` — bounded creative API client/downloads.
- `windows/desktop/src/PicotooPet.Desktop/Services/ControlCenterSession.CreativeIntelligence.cs` — paired-session facade.
- `windows/desktop/src/PicotooPet.Desktop/ViewModels/CreativeIntelligencePanelViewModel.cs` — source selection/fixed actions/status.
- `windows/desktop/src/PicotooPet.Desktop/Views/CreativeIntelligencePanel.xaml` + `.xaml.cs` — embedded panel.
- `windows/desktop/src/PicotooPet.Desktop/Views/Pages/BusinessAutomationPage.xaml` — embed panel without duplicating bridge behavior.
- `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/CreativeIntelligenceWpfSmokeTests.cs` — real STA layout/binding/security smoke.

### Tests

- `tests/creative/test_creative_repository.py`
- `tests/creative/test_creative_source.py`
- `tests/creative/test_creative_profiles.py`
- `tests/creative/test_creative_quality.py`
- `tests/creative/test_creative_store.py`
- `tests/creative/test_creative_execution.py`
- `tests/integration/api/test_creative_intelligence_api.py`
- `tests/integration/worker/test_creative_intelligence_worker.py`
- `tests/contract/test_creative_intelligence_23191_contract.py`
- relevant existing migration/version/release tests updated from schema 11 / 2.3.18.1 to schema 12 / 2.3.19.1.

---

### Task 1: Migration 12, creative job models, repository, and managed roots

**Files:**
- Create: `src/picotoopet_core/db/migration_012.py`
- Create: `src/picotoopet_core/creative/__init__.py`
- Create: `src/picotoopet_core/creative/models.py`
- Create: `src/picotoopet_core/creative/repository.py`
- Modify: `src/picotoopet_core/db/database.py`
- Modify: `src/picotoopet_core/config/paths.py`
- Test: `tests/creative/test_creative_repository.py`
- Test: `tests/contract/test_creative_intelligence_23191_contract.py`

**Interfaces:**
- Produces enums `CreativeJobStatus`, `CreativeStageKind`, `CreativeQualityOutcome`, `CreativeRenderIntent`, `ClaimRisk`.
- Produces strict records `CreativeJobRecord`, `CreativeJobSourceRecord`, `CreativeSourceFinding`, `CreativeStageRunRecord`, `CreativePackageRecord`, `CreativeDeepAiHandoffRecord`.
- Produces `CreativeRepository(database)` with create/get/list/transition/source/finding/stage/package/handoff persistence methods.
- Produces `RuntimePaths.creative_root`, `creative_packages_dir`, `creative_handoffs_dir`.

- [ ] **Step 1: Write RED schema/model tests**

```python
def test_migration_12_creates_creative_tables(database):
    tables = {row["name"] for row in database.fetchall("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {
        "creative_jobs", "creative_job_sources", "creative_source_findings",
        "creative_stage_runs", "creative_packages", "creative_deep_ai_handoffs",
    } <= tables
    assert database.scalar("SELECT MAX(version) FROM schema_migrations") == 12


def test_creative_objective_is_bounded():
    with pytest.raises(ValidationError):
        CreativeJobCreateRequest(
            source_result_package_ids=[str(uuid4())],
            creative_profile="creative.content_plan.v1",
            creative_objective="x" * 2001,
            idempotency_key="creative-too-large",
        )
```

- [ ] **Step 2: Run RED tests**

Run: `pytest tests/creative/test_creative_repository.py tests/contract/test_creative_intelligence_23191_contract.py -q`

Expected: FAIL because Migration 12 and `picotoopet_core.creative` do not exist.

- [ ] **Step 3: Implement schema 12 and strict creative records**

Migration must use immutable source rows, unique idempotency/source-set identities, per-stage unique `(creative_job_id, stage_kind)`, and no raw-media BLOBs. Job status values must include `Ready`, `IdeaRanking`, `BriefGeneration`, `ScriptGeneration`, `ShotPlanning`, `QualityCheck`, `creative_ready`, `NeedsDeepAI`, `NeedsHuman`, `Rejected`, `Failed`, `Cancelled`.

- [ ] **Step 4: Run focused tests**

Run: `pytest tests/creative/test_creative_repository.py tests/contract/test_creative_intelligence_23191_contract.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/picotoopet_core/db src/picotoopet_core/creative src/picotoopet_core/config/paths.py tests/creative tests/contract/test_creative_intelligence_23191_contract.py
git commit -m "feat: add durable creative intelligence facts"
```

### Task 2: Normalize eligible 18.1 Result Packages into stable creative sources

**Files:**
- Create: `src/picotoopet_core/creative/source.py`
- Extend: `src/picotoopet_core/creative/repository.py`
- Test: `tests/creative/test_creative_source.py`

**Interfaces:**
- Produces `CreativeSourceNormalizer(business_repository)`.
- Produces `normalize_source_set(result_package_ids: list[str]) -> NormalizedCreativeSourceSet` containing one project key, sorted source package IDs/digests, deterministic `CreativeSourceFinding` rows and evidence set.
- Stable ref format is exactly `f"{result_package_id}:finding:{rank}"`.

- [ ] **Step 1: Write RED source eligibility/provenance tests**

```python
def test_source_normalizer_derives_stable_finding_ref(source_fixture):
    normalized = source_fixture.normalize([source_fixture.result_id])
    finding = normalized.findings[0]
    assert finding.source_finding_ref == f"{source_fixture.result_id}:finding:1"
    assert finding.finding_digest == source_fixture.expected_finding_digest
    assert finding.evidence_ids == source_fixture.expected_evidence_ids


def test_source_normalizer_rejects_cross_project_results(source_fixture):
    with pytest.raises(CreativeSourceError, match="SOURCE_PROJECT_MISMATCH"):
        source_fixture.normalize([source_fixture.project_a_result, source_fixture.project_b_result])
```

Also cover non-PASS result, source Work Package not `Completed`, 0 or >8 sources, duplicate Result Package ID, duplicate/missing/non-consecutive source finding rank, forged/unresolvable evidence ID, and deterministic order/digest.

- [ ] **Step 2: Run RED source tests**

Run: `pytest tests/creative/test_creative_source.py -q`

Expected: FAIL because source normalizer does not exist.

- [ ] **Step 3: Implement deterministic normalization**

Join each business result to its Work Package for project/status eligibility. Canonicalize each existing 18.1 finding JSON with sorted keys/separators, derive SHA-256, preserve its original `evidence_ids`, and reject malformed ranks/evidence. Do not mutate historical 18.1 Result Packages.

- [ ] **Step 4: Run source tests**

Run: `pytest tests/creative/test_creative_source.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/picotoopet_core/creative/source.py src/picotoopet_core/creative/repository.py tests/creative/test_creative_source.py
git commit -m "feat: normalize creative source evidence"
```

### Task 3: Closed creative profiles and strict four-stage result schemas

**Files:**
- Create: `src/picotoopet_core/creative/profiles.py`
- Extend: `src/picotoopet_core/creative/models.py`
- Test: `tests/creative/test_creative_profiles.py`

**Interfaces:**
- Produces `CreativeProfileDefinition` for exactly `creative.content_plan.v1`.
- Produces `IdeaRankingResult`, `CreativeBriefResult`, `CreativeScriptResult`, `ScriptBeat`, `ShotPlanResult`, `ShotPlanItem`.
- Produces `creative_profile_definition("creative.content_plan.v1")` and stage-specific source-controlled system prompts/schema/bounds.

- [ ] **Step 1: Write RED strict schema tests**

```python
def test_profile_registry_rejects_arbitrary_profile():
    with pytest.raises(ValueError):
        creative_profile_definition("creative.free_prompt.v1")


def test_shot_plan_rejects_comfy_or_arbitrary_render_intent():
    with pytest.raises(ValidationError):
        ShotPlanItem.model_validate({**VALID_SHOT, "render_intent": "COMFY_WORKFLOW"})
```

Cover idea count 3–10, consecutive ranks, confidence, claim risk enum, brief duration bounds, script beat IDs/order/duration, shot ID/order/duration, allowed six renderer-neutral intents, text/list limits, and `extra="forbid"`.

- [ ] **Step 2: Run RED profile tests**

Run: `pytest tests/creative/test_creative_profiles.py -q`

Expected: FAIL.

- [ ] **Step 3: Implement closed profile/stage schemas**

Every stage prompt explicitly frames source/creative objective as untrusted data and requests exactly one JSON object. No tools/functions are added; temperature/output settings are fixed in source control.

- [ ] **Step 4: Run profile tests**

Run: `pytest tests/creative/test_creative_profiles.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/picotoopet_core/creative/models.py src/picotoopet_core/creative/profiles.py tests/creative/test_creative_profiles.py
git commit -m "feat: define closed creative stage schemas"
```

### Task 4: Deterministic creative quality gate

**Files:**
- Create: `src/picotoopet_core/creative/quality.py`
- Test: `tests/creative/test_creative_quality.py`

**Interfaces:**
- Produces `CreativeQualityGate.evaluate(stage_kind, profile, source_set, previous_stages, raw_result) -> (CreativeQualityDecision, parsed_model | None)`.
- Repairable schema/reference/order errors return `RETRY`; secret/tool/workflow leakage returns `REJECT`; declared/semantic uncertainty maps to attention.

- [ ] **Step 1: Write RED provenance/coverage/leakage tests**

```python
def test_idea_quality_retries_unknown_source_finding_ref(quality_fixture):
    raw = quality_fixture.valid_idea_result()
    raw["ideas"][0]["source_finding_refs"] = ["missing:finding:1"]
    decision, parsed = quality_fixture.gate.evaluate_idea(raw)
    assert decision.outcome is CreativeQualityOutcome.RETRY
    assert "UNKNOWN_SOURCE_FINDING_REF" in decision.reasons
    assert parsed is None


def test_shot_plan_must_cover_all_required_script_beats(quality_fixture):
    raw = quality_fixture.valid_shot_plan_without_last_beat()
    decision, _ = quality_fixture.gate.evaluate_shot_plan(raw)
    assert decision.outcome is CreativeQualityOutcome.RETRY
    assert "SCRIPT_BEAT_NOT_COVERED" in decision.reasons
```

Also verify unknown evidence, selected idea mismatch, duplicate ranks/beats/shots, duration overflow, factual claim without evidence/unsupported marker, system prompt/token leakage, Comfy/workflow/path/shell/download URL leakage, and `NeedsHuman`/`NeedsDeepAI` declarations.

- [ ] **Step 2: Run RED quality tests**

Run: `pytest tests/creative/test_creative_quality.py -q`

Expected: FAIL.

- [ ] **Step 3: Implement deterministic quality gate**

Do not use another model to score beauty/humor. Only deterministic structure/provenance/safety is PASS/RETRY/REJECT. Semantic uncertainty is attention.

- [ ] **Step 4: Run quality tests**

Run: `pytest tests/creative/test_creative_quality.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/picotoopet_core/creative/quality.py tests/creative/test_creative_quality.py
git commit -m "feat: validate creative provenance and structure"
```

### Task 5: Immutable Creative Package and manual Deep-AI Handoff store

**Files:**
- Create: `src/picotoopet_core/creative/store.py`
- Extend: `src/picotoopet_core/creative/repository.py`
- Test: `tests/creative/test_creative_store.py`

**Interfaces:**
- Produces `CreativeArtifactStore(paths)` with `write_creative_package`, `write_handoff_package`, `resolve_managed_relative`.
- Creative ZIP contains exactly one UUID top-level root and `creative-package.json`; Handoff ZIP contains exactly one root and `creative-deep-ai-handoff.json`.

- [ ] **Step 1: Write RED immutability/sanitization tests**

```python
def test_creative_package_write_is_idempotent(store_fixture):
    first = store_fixture.write_valid_package()
    second = store_fixture.write_valid_package()
    assert first == second


def test_handoff_sanitizer_excludes_secrets_paths_and_full_raw_dataset(store_fixture):
    payload = store_fixture.write_handoff_with_sensitive_input()
    text = store_fixture.read_handoff_text(payload)
    assert "Authorization" not in text
    assert "/Users/" not in text
    assert "C:\\Users\\" not in text
    assert store_fixture.full_raw_dataset_marker not in text
```

- [ ] **Step 2: Run RED store tests**

Run: `pytest tests/creative/test_creative_store.py -q`

Expected: FAIL.

- [ ] **Step 3: Implement managed immutable output store**

All disk paths derive from Core-generated UUIDs, never producer text. Existing identical digest is reused; conflicting existing bytes fail closed. Handoff receives bounded prior stages/source excerpts and redacts secret-bearing keys.

- [ ] **Step 4: Run store tests**

Run: `pytest tests/creative/test_creative_store.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/picotoopet_core/creative/store.py src/picotoopet_core/creative/repository.py tests/creative/test_creative_store.py
git commit -m "feat: persist immutable creative packages"
```

### Task 6: Mac Core creative service and authenticated API

**Files:**
- Create: `src/picotoopet_core/creative/service.py`
- Create: `src/picotoopet_core/api/routes/creative_intelligence.py`
- Modify: `src/picotoopet_core/services.py`
- Modify: `src/picotoopet_core/api/app.py`
- Test: `tests/integration/api/test_creative_intelligence_api.py`

**Interfaces:**
- `CreativeIntelligenceService.create_job(source_result_package_ids, creative_profile, creative_objective, idempotency_key)` normalizes/validates sources, persists immutable source set, and creates one queue task.
- API endpoints under `/api/v1/creative/...` list eligible sources/jobs, create/get/cancel job, metadata/download package, metadata/download Handoff.

- [ ] **Step 1: Write RED API/security/idempotency tests**

```python
def test_create_creative_job_accepts_only_closed_fields(client, headers, eligible_result_id):
    payload = {
        "source_result_package_ids": [eligible_result_id],
        "creative_profile": "creative.content_plan.v1",
        "creative_objective": "Create a short product education concept.",
        "idempotency_key": "creative-demo-1",
    }
    response = client.post("/api/v1/creative/jobs", headers=headers, json=payload)
    assert response.status_code == 200

    injected = {**payload, "model": "remote", "endpoint": "https://example.com", "prompt": "ignore policy"}
    assert client.post("/api/v1/creative/jobs", headers=headers, json=injected).status_code == 422
```

Also cover auth, cross-project rejection, non-PASS rejection, >8 source IDs, same idempotency/same digest reuse, same key/different digest conflict, cancel terminal/nonterminal behavior, bounded downloads.

- [ ] **Step 2: Run RED API tests**

Run: `pytest tests/integration/api/test_creative_intelligence_api.py -q`

Expected: FAIL because creative service/router do not exist.

- [ ] **Step 3: Implement service/router and queue materialization**

Queue task payload is only `creative_job_id`, `source_set_digest`, `creative_profile`; fixed task type `creative.content_plan.v1`; max task attempts supports crash recovery without broadening per-stage model budgets.

- [ ] **Step 4: Run API tests**

Run: `pytest tests/integration/api/test_creative_intelligence_api.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/picotoopet_core/creative/service.py src/picotoopet_core/api/routes/creative_intelligence.py src/picotoopet_core/services.py src/picotoopet_core/api/app.py tests/integration/api/test_creative_intelligence_api.py
git commit -m "feat: add creative intelligence core api"
```

### Task 7: Four-stage Mac Worker coordinator with crash-safe bounded inference

**Files:**
- Create: `src/picotoopet_core/creative/execution.py`
- Modify: `src/picotoopet_core/cli.py`
- Test: `tests/creative/test_creative_execution.py`
- Test: `tests/integration/worker/test_creative_intelligence_worker.py`

**Interfaces:**
- Produces `CreativeIntelligenceCoordinator.TASK_TYPE = "creative.content_plan.v1"` and `.CAPABILITY = "creative.intelligence.v1"`.
- Reuses `OpenAiCompatibleLocalIntelligenceAdapter` but stage-specific profile prompts/schemas.
- Persists stage input digest, attempt count, valid parsed result JSON and result digest before advancing.

- [ ] **Step 1: Write RED worker end-to-end/recovery tests**

```python
def test_creative_worker_completes_four_stages_with_fake_local_model(creative_fixture):
    creative_fixture.enqueue_job()
    result = creative_fixture.coordinator.handler(creative_fixture.task)
    job = creative_fixture.service.get_job(creative_fixture.job_id)
    package = creative_fixture.service.get_package(creative_fixture.job_id)
    assert result.summary["status"] == "creative_ready"
    assert job.status.value == "creative_ready"
    assert package is not None
    assert creative_fixture.fake_adapter.calls == 4


def test_second_repairable_failure_stops_at_needs_deep_ai(creative_fixture):
    creative_fixture.fake_adapter.responses = [INVALID_IDEA, INVALID_IDEA]
    creative_fixture.coordinator.handler(creative_fixture.task)
    assert creative_fixture.service.get_job(creative_fixture.job_id).status.value == "NeedsDeepAI"
    assert creative_fixture.fake_adapter.calls == 2
```

Also cover one repair then PASS, persisted completed stage reused after simulated Worker restart, stage attempt budget not reset, local endpoint unavailable → `NeedsHuman`, cancellation, source digest mismatch, completed package exact reuse, and no dynamic task types.

- [ ] **Step 2: Run RED Worker tests**

Run: `pytest tests/creative/test_creative_execution.py tests/integration/worker/test_creative_intelligence_worker.py -q`

Expected: FAIL.

- [ ] **Step 3: Implement stage coordinator and capability registration**

Each stage context uses only normalized source facts plus validated prior stage outputs. Rank-1 idea flows automatically into brief. After final Shot Plan PASS, coordinator performs final cross-stage QualityCheck and writes Creative Package; attention creates sanitized Handoff only.

Creative capability is registered only while the same loopback local model health probe used by 18.1 is healthy. No model/runtime start/download side effect.

- [ ] **Step 4: Run Worker tests**

Run: `pytest tests/creative/test_creative_execution.py tests/integration/worker/test_creative_intelligence_worker.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/picotoopet_core/creative/execution.py src/picotoopet_core/cli.py tests/creative/test_creative_execution.py tests/integration/worker/test_creative_intelligence_worker.py
git commit -m "feat: execute bounded creative intelligence stages"
```

### Task 8: Windows typed creative client/session and fixed package delivery

**Files:**
- Create: `windows/desktop/src/PicotooPet.Desktop.Core/Contracts/CreativeIntelligenceContracts.cs`
- Create: `windows/desktop/src/PicotooPet.Desktop.Core/Networking/MacCoreClient.CreativeIntelligence.cs`
- Create: `windows/desktop/src/PicotooPet.Desktop/Services/ControlCenterSession.CreativeIntelligence.cs`
- Test: extend Windows smoke project with creative client/source-contract tests.

**Interfaces:**
- Typed DTOs mirror Core job/source/package/handoff facts.
- Client never accepts arbitrary model/prompt/endpoint/path/tool/command fields.
- Creative Package/Handoff downloads are bounded (8 MiB initial ceiling) and written atomically into fixed BusinessBridge Outbox subdirectories by job/package identity.

- [ ] **Step 1: Write RED Windows compile/source-contract tests**

Smoke/source tests assert exact route names, `creative.content_plan.v1`, bounded source count 8, bounded objective 2000, and absence of model/endpoint/system-prompt/tool/command/workflow request members.

- [ ] **Step 2: Run native Windows RED workflow**

Run repository Windows Control Center CI on the RED head.

Expected: compile/source-contract failure because creative DTO/client/session files are missing.

- [ ] **Step 3: Implement typed client/session and atomic bounded download**

Reuse existing token/BaseUri and response-size patterns. Do not add another Windows service or local HTTP server.

- [ ] **Step 4: Run Windows smoke/build path**

Expected: typed client/source tests and warnings-as-errors build PASS.

- [ ] **Step 5: Commit**

```bash
git add windows/desktop/src/PicotooPet.Desktop.Core windows/desktop/src/PicotooPet.Desktop/Services windows/desktop/tests
git commit -m "feat: add Windows creative intelligence client"
```

### Task 9: Embedded Creative Intelligence WPF panel

**Files:**
- Create: `windows/desktop/src/PicotooPet.Desktop/ViewModels/CreativeIntelligencePanelViewModel.cs`
- Create: `windows/desktop/src/PicotooPet.Desktop/Views/CreativeIntelligencePanel.xaml`
- Create: `windows/desktop/src/PicotooPet.Desktop/Views/CreativeIntelligencePanel.xaml.cs`
- Modify: `windows/desktop/src/PicotooPet.Desktop/Views/Pages/BusinessAutomationPage.xaml`
- Modify: `windows/desktop/src/PicotooPet.Desktop/ViewModels/BusinessAutomationPageViewModel.cs` only for composition/refresh handoff if needed; keep creative logic in panel VM.
- Create: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/CreativeIntelligenceWpfSmokeTests.cs`
- Modify: smoke `Program.cs`.

**Interfaces:**
- UI supports eligible-source selection (1–8 same project), optional bounded objective, fixed create/refresh/cancel/export actions, creative capability health and job/stage facts.
- Explicit display: `creative_ready != rendered != publish-ready`.

- [ ] **Step 1: Write RED real-WPF/security smoke**

```csharp
panel.Measure(new Size(1100, 700));
panel.Arrange(new Rect(0, 0, 1100, 700));
panel.UpdateLayout();
SmokeAssert.True(panel.ActualWidth > 0 && panel.ActualHeight > 0, "Creative Intelligence panel did not layout");
```

Source assertions forbid `ModelInput`, `EndpointInput`, `SystemPromptInput`, `CommandInput`, `ToolInput`, `ComfyWorkflow`, `WebView`, and arbitrary filesystem path input. Read-only record bindings must be explicit `Mode=OneWay`.

- [ ] **Step 2: Run native Windows RED WPF workflow**

Expected: FAIL because creative panel is missing.

- [ ] **Step 3: Implement panel/viewmodel/composition**

Selection is user-facing business fact selection, not execution customization. Filter/disable sources so cross-project selection cannot be submitted; Core remains authoritative and rejects it regardless.

- [ ] **Step 4: Run real STA WPF + warnings-as-errors build**

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add windows/desktop/src/PicotooPet.Desktop windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests
git commit -m "feat: add creative intelligence WPF panel"
```

### Task 10: Roll product to 2.3.19.1 and freeze release/security contracts

**Files:**
- Modify: `src/picotoopet_core/product-version.txt`
- Modify: `contracts/release/project-goal-invariants.json`
- Modify active version/schema tests across `tests/` and Windows smoke fixtures.
- Extend: `tests/contract/test_creative_intelligence_23191_contract.py`
- Modify Mac package/install contracts only if needed to include new creative modules/directories; do not install models/runtime.

**Interfaces:**
- Canonical product version `2.3.19.1` on Core/Worker/Windows.
- Database schema 12.
- Release invariant explicitly says `automatic_comfyui=false`, `automatic_paid_ai=false`, `creative_ready_not_rendered=true`, max stage model attempts 2.

- [ ] **Step 1: Extend RED release contracts before version bump**

Contract asserts creative modules/API/WPF/capability/task/profile/Migration 12, forbidden input surfaces, no automatic ComfyUI/paid AI, and user-machine no source build.

- [ ] **Step 2: Audit active `2.3.18.1` and schema-11 assertions**

Use repository-wide search. Update active runtime/release/test literals only; leave historical design/evidence documents unchanged.

- [ ] **Step 3: Bump canonical version/release contract to `2.3.19.1` and schema 12**

- [ ] **Step 4: Run full Python regression and Windows source contracts**

Run: `pytest -q`

Expected: PASS on the current feature head; if failures are stale active version/schema fixtures, fix only those active fixtures.

- [ ] **Step 5: Commit**

```bash
git add src contracts tests scripts deploy windows
git commit -m "chore: roll creative intelligence into 2.3.19.1"
```

### Task 11: Exact-head native CI, Draft PR, packages, and independent verification

**Files:**
- Modify only files required by concrete native CI failures.
- Create final delivery artifacts outside repository after exact-head PASS.

**Interfaces:**
- Feature branch: `feature/creative-intelligence-2.3.19.1` stacked on the approved 19.1 design/plan lineage.
- Draft PR base remains the exact 2.3.18.1 feature lineage, not `main`.

- [ ] **Step 1: Create/maintain Draft PR and freeze candidate exact head**

PR title: `feat: creative intelligence for 2.3.19.1`.

Body summarizes Result Package → Creative Package pipeline, evidence chain, stage retry ceiling, no ComfyUI/paid AI, schema 12, and package gates. Keep Draft/Open/Unmerged.

- [ ] **Step 2: Run/wait for exact-head native gates**

Required:

- Mac Core Slice B CI
- Mac Worker Slice D CI
- Windows Control Center Slice D CI
- Phase 2.3 Slice D Windows Prebuilt Release

Never accept earlier-head results. On failure, inspect exact failed step, add/adjust a regression test where appropriate, implement the minimum fix, commit, and rerun all required exact-head gates.

- [ ] **Step 3: Verify security/recovery regressions**

Must include ineligible/cross-project source rejection, stable finding refs/digests, forged finding/evidence refs, objective injection, schema repair ceiling, stage crash reuse, non-loopback model rejection inherited from 18.1, no tools, renderer-intent allowlist, Comfy/workflow/path/command leakage rejection, bounded downloads, WPF real layout/OneWay bindings.

- [ ] **Step 4: Download exact-head formal packages and independently inspect**

For Windows/Mac Core/Mac Worker recompute SHA-256; verify single safe archive root, no traversal/duplicates/link/special payloads, manifest sizes/hashes, AMD64/arm64 targets, product version `2.3.19.1`, Migration 12 + creative modules in embedded wheel, no source build/model runtime installer, INSTALL/VERIFY/ROLLBACK presence, source/build tree equality.

- [ ] **Step 5: Generate delivery set**

Create:

- Windows 2.3.19.1 prebuilt ZIP + SHA sidecar
- Mac Core 2.3.19.1 arm64 package + SHA sidecar
- Mac Worker 2.3.19.1 arm64 package + SHA sidecar
- combined SHA manifest
- delivery manifest
- independent verification JSON
- Chinese manual acceptance guide
- bounded non-sensitive Creative Intelligence fixture/sample package if useful for real-machine validation

- [ ] **Step 6: Manual acceptance contract**

Acceptance verifies install order Core → Worker → Windows; version 19.1/schema 12; 18.1 diagnostics/business non-regression; local creative capability healthy; one PASS Result Package or same-project review+idea pair creates a job; stages reach `creative_ready`; Creative Package exports; restart reuses identities/stages; no ComfyUI/paid AI/shell/Git publication/main/tag/release occurs.

---

## Plan Self-Review

- Spec coverage: Migration 12, source eligibility, stable finding refs/digests, four schemas, quality/provenance, immutable package/handoff, API, Worker recovery/attempt ceiling, Windows typed client, embedded WPF panel, version/release contract, native CI/packages/manual acceptance all have explicit tasks.
- Placeholder scan: no `TBD`, `TODO`, “implement later”, or undefined “similar to Task N” steps.
- Type consistency: `creative.content_plan.v1`, `creative.intelligence.v1`, `source_finding_ref`, `creative_ready`, schema 12, product version 2.3.19.1, source max 8, objective max 2000, and stage max attempts 2 are consistent across tasks.
- Scope: ComfyUI execution, automatic paid AI, publishing, arbitrary prompts/tools, and new Windows background service remain explicitly out of scope.
