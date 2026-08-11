# PicotooPet 2.3.20.1 ComfyUI Production Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert one immutable 2.3.19.1 `creative_ready` Creative Package v1 into a durable Production Job that a closed Windows ComfyUI executor renders locally into a content-addressed Production Package v1.

**Architecture:** Mac Core remains the fact/control plane and owns production state, deterministic plans, leases and package provenance. Windows claims a bounded plan, binds it only to source-controlled Wan2.2 TI2V 5B API-format workflow templates, talks only to `http://127.0.0.1:8188`, validates output bytes/paths/hashes, and commits bounded results to Core. The local LLM never receives workflow/node/path/command authority.

**Tech Stack:** Python 3.12, FastAPI/Pydantic, SQLite, C#/.NET WPF, HttpClient, PowerShell 5.1 bootstrap contracts, ComfyUI local HTTP API, pytest, native Windows STA WPF smoke tests, GitHub Actions macOS arm64 and Windows x64 gates.

## Global Constraints

- Product version is `2.3.20.1`.
- Database schema is `13`.
- Exact implementation base is `dd9188676815e61ea81093c4281d9e2b76bc02cc`.
- Production profile is exactly `production.comfyui.v1`.
- Terminal success state is exactly `production_ready`.
- ComfyUI transport is fixed to `http://127.0.0.1:8188`.
- Formal workflow IDs are `comfy.wan22.ti2v5b.t2v.v1` and `comfy.wan22.ti2v5b.i2v.v1`.
- Formal model roles are bound to the existing pinned Wan2.2 TI2V 5B diffusion model, Wan2.2 VAE and UMT5 encoder.
- No arbitrary workflow JSON, node classes, model filenames, filesystem paths, endpoints, URLs, commands, custom-node installs, cloud rendering or paid-AI fallback may enter from producer/model/API/UI input.
- Each production task has at most two ComfyUI attempts total.
- No `main` merge, tag or GitHub Release.

---

### Task 1: RED release and production contracts

**Files:**
- Create: `tests/contract/test_comfyui_production_23201_contract.py`
- Modify: `tests/test_package_baseline.py`
- Modify: `tests/contract/test_phase10c_event_stream_recovery_rollup.py`

**Interfaces:**
- Consumes: existing 2.3.19.1 release/version surfaces.
- Produces: failing contracts that require version `2.3.20.1`, schema 13, Migration 13, production module/API, closed profile and Windows production surface.

- [ ] **Step 1: Add the failing contract suite**

Create assertions requiring:

```python
EXPECTED_PRODUCT_VERSION = "2.3.20.1"
EXPECTED_DATABASE_SCHEMA = 13
EXPECTED_PROFILE = "production.comfyui.v1"
EXPECTED_ENDPOINT = "http://127.0.0.1:8188"
EXPECTED_WORKFLOWS = {
    "comfy.wan22.ti2v5b.t2v.v1",
    "comfy.wan22.ti2v5b.i2v.v1",
}
```

The suite must assert that `src/picotoopet_core/production/`, `src/picotoopet_core/db/migration_013.py`, the production API route, Windows production contracts/service/viewmodel/panel, and both workflow templates exist; it must reject non-loopback endpoint literals and arbitrary workflow/model/path/command fields in create/claim result contracts.

- [ ] **Step 2: Advance active package/version assertions to 2.3.20.1**

Update only active version tests so the branch intentionally becomes RED until production version surfaces are implemented.

- [ ] **Step 3: Run exact RED tests**

Run:

```bash
PYTHONPATH=.:src python -m pytest -q \
  tests/test_package_baseline.py \
  tests/contract/test_comfyui_production_23201_contract.py \
  tests/contract/test_phase10c_event_stream_recovery_rollup.py
```

Expected: FAIL because the branch still exposes 2.3.19.1/schema 12 and production files do not exist.

- [ ] **Step 4: Commit RED**

```bash
git add tests/test_package_baseline.py tests/contract/test_comfyui_production_23201_contract.py tests/contract/test_phase10c_event_stream_recovery_rollup.py
git commit -m "test: define 2.3.20.1 ComfyUI production contracts"
```

### Task 2: Migration 13 and durable Core models/repository

**Files:**
- Create: `src/picotoopet_core/db/migration_013.py`
- Modify: `src/picotoopet_core/db/database.py`
- Create: `src/picotoopet_core/production/__init__.py`
- Create: `src/picotoopet_core/production/models.py`
- Create: `src/picotoopet_core/production/repository.py`
- Test: `tests/production/test_production_repository.py`
- Test: `tests/unit/db/test_migrations.py`

**Interfaces:**
- Produces: `ProductionJobCreateRequest`, `ProductionJobRecord`, `ProductionTaskPlan`, `ProductionPlan`, `ProductionClaimRecord`, `ProductionTaskCommitRequest`, `ProductionPackageRecord`, `ProductionRepository`.

- [ ] **Step 1: Write repository and migration RED tests**

Require schema 13 and tables `production_jobs`, `production_tasks`, `production_attempts`, `production_packages`. Test idempotent job creation, immutable plan digest, legal state transitions, one active lease, lease expiry/reclaim, task attempt cap of two, immutable successful task commit and package uniqueness.

- [ ] **Step 2: Verify RED**

```bash
PYTHONPATH=.:src python -m pytest -q tests/production/test_production_repository.py tests/unit/db/test_migrations.py
```

Expected: FAIL because Migration 13 and production repository do not exist.

- [ ] **Step 3: Implement Migration 13 and models**

Use string enums for job/task states and strict Pydantic `extra="forbid"` request models. Lease tokens are opaque UUID-derived secrets stored only as SHA-256 digests in SQLite; raw tokens are returned once by claim.

- [ ] **Step 4: Implement repository invariants**

`ProductionRepository` must expose:

```python
create_job(...)
get_job(production_job_id: str)
list_jobs(limit: int = 100)
save_plan(production_job_id: str, plan: ProductionPlan, plan_digest: str)
claim_job(production_job_id: str, executor_id: str, lease_seconds: int = 120)
heartbeat(production_job_id: str, executor_id: str, lease_token: str, lease_seconds: int = 120)
commit_task_result(production_job_id: str, request: ProductionTaskCommitRequest)
mark_task_attempt(production_job_id: str, production_task_id: str, comfy_prompt_id: str | None)
transition_job(...)
save_package(record: ProductionPackageRecord)
package_for(production_job_id: str)
```

- [ ] **Step 5: Run focused GREEN**

```bash
PYTHONPATH=.:src python -m pytest -q tests/production/test_production_repository.py tests/unit/db/test_migrations.py
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/picotoopet_core/db src/picotoopet_core/production tests/production tests/unit/db/test_migrations.py
git commit -m "feat: add durable production schema and repository"
```

### Task 3: Deterministic Production Plan compiler and quality boundary

**Files:**
- Create: `src/picotoopet_core/production/profile.py`
- Create: `src/picotoopet_core/production/compiler.py`
- Create: `src/picotoopet_core/production/quality.py`
- Test: `tests/production/test_production_compiler.py`
- Test: `tests/production/test_production_quality.py`

**Interfaces:**
- Consumes: 2.3.19.1 Creative Package manifest and `ShotPlanItem` fields.
- Produces: `compile_production_plan(manifest: dict[str, object]) -> ProductionPlan` and `validate_task_commit(...)`.

- [ ] **Step 1: Write compiler RED tests**

Test that `GENERATIVE_VIDEO` maps only to `comfy.wan22.ti2v5b.t2v.v1`, `IMAGE_TO_VIDEO` maps only to `comfy.wan22.ti2v5b.i2v.v1` when a trusted local asset reference exists, and every other render intent becomes `NeedsHuman` without a workflow template.

Verify deterministic positive prompt construction in this exact semantic order:

```text
subject; environment; action; framing; lighting/style; continuity; required facts
```

Verify seed derivation is stable from `production_job_id + shot_id + production profile version` and never accepts an externally supplied seed.

- [ ] **Step 2: Verify RED**

```bash
PYTHONPATH=.:src python -m pytest -q tests/production/test_production_compiler.py tests/production/test_production_quality.py
```

- [ ] **Step 3: Implement closed profile and compiler**

Bounds:

```python
MIN_WIDTH = 256
MAX_WIDTH = 1280
MIN_HEIGHT = 256
MAX_HEIGHT = 1280
DEFAULT_WIDTH = 832
DEFAULT_HEIGHT = 480
DEFAULT_FPS = 24
MAX_FPS = 30
DEFAULT_FRAME_COUNT = 81
MAX_FRAME_COUNT = 121
NEGATIVE_PROMPT_POLICY_ID = "wan22.safe-negative.v1"
```

The compiler uses no network, model call, shell command or arbitrary workflow JSON.

- [ ] **Step 4: Run focused GREEN and commit**

```bash
PYTHONPATH=.:src python -m pytest -q tests/production/test_production_compiler.py tests/production/test_production_quality.py
git add src/picotoopet_core/production tests/production
git commit -m "feat: compile closed ComfyUI production plans"
```

### Task 4: Core Production service and API

**Files:**
- Create: `src/picotoopet_core/production/service.py`
- Create: `src/picotoopet_core/api/routes/production.py`
- Modify: `src/picotoopet_core/api/app.py`
- Modify: `src/picotoopet_core/services.py`
- Modify: `src/picotoopet_core/cli.py`
- Test: `tests/integration/api/test_production_api.py`

**Interfaces:**
- Produces HTTP endpoints:

```text
GET  /api/v1/production/eligible
POST /api/v1/production/jobs
GET  /api/v1/production/jobs
GET  /api/v1/production/jobs/{job_id}
GET  /api/v1/production/jobs/{job_id}/plan
POST /api/v1/production/jobs/{job_id}/claim
POST /api/v1/production/jobs/{job_id}/heartbeat
POST /api/v1/production/jobs/{job_id}/tasks/{task_id}/attempt
POST /api/v1/production/jobs/{job_id}/tasks/{task_id}/result
POST /api/v1/production/jobs/{job_id}/cancel
GET  /api/v1/production/jobs/{job_id}/package
```

- [ ] **Step 1: Write API RED tests**

Assert only Core-stored PASS/`creative_ready` packages are eligible; create request accepts only `creative_package_id`, fixed profile and `idempotency_key`; claim accepts only `executor_id`; task result accepts only bounded execution evidence plus lease token; endpoint/model/workflow/path/command overrides are rejected with 422.

- [ ] **Step 2: Verify RED**

```bash
PYTHONPATH=.:src python -m pytest -q tests/integration/api/test_production_api.py
```

- [ ] **Step 3: Implement service/API and package manifest creation**

When all executable tasks are `Succeeded` and no task is `NeedsHuman`, create immutable Production Package v1 metadata and transition to `production_ready`. Any unsupported intent transitions the job to `NeedsHuman` without calling a renderer.

- [ ] **Step 4: Run focused GREEN and commit**

```bash
PYTHONPATH=.:src python -m pytest -q tests/integration/api/test_production_api.py
git add src/picotoopet_core tests/integration/api/test_production_api.py
git commit -m "feat: expose durable production API"
```

### Task 5: Source-controlled ComfyUI workflow templates and static validator

**Files:**
- Create: `windows/production/workflows/wan22-ti2v5b-t2v-api-v1.json`
- Create: `windows/production/workflows/wan22-ti2v5b-i2v-api-v1.json`
- Create: `windows/desktop/src/PicotooPet.Desktop.Core/Production/ComfyWorkflowTemplateValidator.cs`
- Test: `tests/contract/test_comfyui_workflow_templates.py`
- Test: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/ComfyWorkflowTemplateSmokeTests.cs`

**Interfaces:**
- Produces validated API-format templates using only the allowlisted core classes:

```text
UNETLoader
CLIPLoader
VAELoader
ModelSamplingSD3
CLIPTextEncode
Wan22ImageToVideoLatent
KSampler
VAEDecode
SaveWEBM
LoadImage   # I2V template only
```

- [ ] **Step 1: Write static RED tests**

Require exact loader filenames from `windows/bootstrap/model_manifest.json`, no URL fields, no API/provider/custom node class names, no absolute paths, and fixed output filename-prefix slot.

- [ ] **Step 2: Verify RED**

```bash
PYTHONPATH=.:src python -m pytest -q tests/contract/test_comfyui_workflow_templates.py
```

- [ ] **Step 3: Add minimal API-format Wan2.2 templates**

The T2V template uses `Wan22ImageToVideoLatent` without `start_image`; the I2V template adds `LoadImage` and binds its `IMAGE` output into `start_image`. Runtime-mutable slots are limited to positive prompt, seed, width, height, length, fps, output prefix and the I2V input filename.

- [ ] **Step 4: Implement C# static validator and GREEN tests**

Reject any template whose class set, loader values or mutable slot structure differs from the frozen profile.

- [ ] **Step 5: Commit**

```bash
git add windows/production tests/contract/test_comfyui_workflow_templates.py windows/desktop/src/PicotooPet.Desktop.Core windows/desktop/tests
git commit -m "feat: freeze Wan2.2 ComfyUI workflow templates"
```

### Task 6: Windows loopback Comfy executor

**Files:**
- Create: `windows/desktop/src/PicotooPet.Desktop.Core/Production/ComfyProductionContracts.cs`
- Create: `windows/desktop/src/PicotooPet.Desktop.Core/Production/ComfyProductionClient.cs`
- Create: `windows/desktop/src/PicotooPet.Desktop/Services/ProductionExecutionService.cs`
- Test: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/ComfyProductionClientSmokeTests.cs`
- Test: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/ProductionExecutionServiceSmokeTests.cs`

**Interfaces:**
- `ComfyProductionClient` is constructed with an `HttpClient` whose base address must equal `http://127.0.0.1:8188/`.
- `ProductionExecutionService` consumes a Core Production Plan and active lease and emits bounded task attempt/result requests back to Core.

- [ ] **Step 1: Write RED loopback/fake-server tests**

Reject `localhost`, LAN addresses, HTTPS cloud endpoints and arbitrary ports. Fake-server flow must exercise `/object_info`, `/prompt`, `/history/{prompt_id}` and output evidence parsing.

- [ ] **Step 2: Implement preflight**

Require all allowlisted node classes plus the three pinned model files. Validate trusted roots and reject `resources\ComfyUI` modification paths.

- [ ] **Step 3: Implement execution**

Deep-clone the frozen template, mutate only declared slots, submit JSON, poll bounded history, validate output relative path, recompute SHA-256/byte length, and commit the result to Core. Use at most two attempts per task.

- [ ] **Step 4: Run Windows smoke tests**

```powershell
dotnet run --project windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/PicotooPet.Desktop.Core.SmokeTests.csproj -c Release
```

Expected: PASS without a real GPU because the Comfy transport is exercised against the fake local handler.

- [ ] **Step 5: Commit**

```bash
git add windows/desktop
git commit -m "feat: add closed loopback ComfyUI executor"
```

### Task 7: Windows Production panel and Core client contracts

**Files:**
- Create: `windows/desktop/src/PicotooPet.Desktop.Core/Contracts/ProductionContracts.cs`
- Create: `windows/desktop/src/PicotooPet.Desktop.Core/Networking/MacCoreClient.Production.cs`
- Create: `windows/desktop/src/PicotooPet.Desktop/Services/ControlCenterSession.Production.cs`
- Create: `windows/desktop/src/PicotooPet.Desktop/ViewModels/ProductionPanelViewModel.cs`
- Create: `windows/desktop/src/PicotooPet.Desktop/Views/ProductionPanel.xaml`
- Create: `windows/desktop/src/PicotooPet.Desktop/Views/ProductionPanel.xaml.cs`
- Modify: `windows/desktop/src/PicotooPet.Desktop/Views/Pages/BusinessAutomationPage.xaml`
- Modify: `windows/desktop/src/PicotooPet.Desktop/ViewModels/BusinessAutomationPageViewModel.cs`
- Modify: `windows/desktop/src/PicotooPet.Desktop/Services/AppSelfTest.cs`
- Test: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/ProductionPanelWpfSmokeTests.cs`
- Modify: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/Program.cs`

**Interfaces:**
- UI actions: refresh eligible packages, create fixed-profile job, run preflight, start/claim, cancel, open output folder.
- No editable workflow/model/endpoint/path/command controls.

- [ ] **Step 1: Write real WPF RED smoke test**

Construct `ProductionPanel`, assign a viewmodel, call `Measure`, `Arrange`, `UpdateLayout`, and assert all command buttons/status collections bind without exceptions.

- [ ] **Step 2: Implement contracts/client/session/viewmodel/panel**

Keep all code-behind presentation-only; state/commands live in the viewmodel/service.

- [ ] **Step 3: Add panel to Business Automation page**

Place it after Creative Intelligence without creating a new top-level Shell route, so the current eleven-item navigation contract remains unchanged.

- [ ] **Step 4: Run WPF smoke + warnings-as-errors build**

```powershell
dotnet run --project windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/PicotooPet.Desktop.Core.SmokeTests.csproj -c Release
dotnet build windows/desktop/PicotooPet.Desktop.sln -c Release -warnaserror
```

- [ ] **Step 5: Commit**

```bash
git add windows/desktop
git commit -m "feat: add production control panel"
```

### Task 8: Release/version rollup and cumulative installer contracts

**Files:**
- Modify: `src/picotoopet_core/product-version.txt`
- Modify: `contracts/release/project-goal-invariants.json`
- Modify: active product-version contract tests
- Modify: Windows product version surfaces required by existing release contracts
- Modify: `windows/bootstrap/model_manifest.json` only if metadata needs a production-profile annotation; do not change pinned model binaries/revisions/hashes.

**Interfaces:**
- Produces exact product version `2.3.20.1` and database schema `13` across active release surfaces.

- [ ] **Step 1: Update version/schema goal invariants**

Add a `comfyui_production_v1` invariant block containing fixed profile, loopback endpoint, supported intents, formal workflow IDs, model roles, maximum attempts and no-cloud/no-custom-node/no-auto-download policy.

- [ ] **Step 2: Run full Python regression**

```bash
PYTHONPATH=.:src python -m pytest -q
```

Expected: PASS with no stale active `2.3.19.1` version literal.

- [ ] **Step 3: Run focused Windows contract/security/WPF regression**

Use the same commands and workflow entrypoints as the existing Windows Control Center and prebuilt release gates.

- [ ] **Step 4: Commit**

```bash
git add src contracts tests windows
git commit -m "release: roll product to 2.3.20.1"
```

### Task 9: Exact-head native CI, packaging and independent verification

**Files:**
- Update PR body only after the exact head is frozen.
- Create local handoff verification outputs outside the repository.

**Interfaces:**
- Consumes final exact source head.
- Produces required Mac/Windows formal artifacts and SHA-256 evidence.

- [ ] **Step 1: Run all required native workflows on the exact head**

Require successful Mac Core, Mac Worker if impact detection selects it, Windows Control Center and Windows Prebuilt workflows.

- [ ] **Step 2: Debug any failure from exact job logs**

Never treat an older workflow head as evidence for the final candidate.

- [ ] **Step 3: Download all formal artifacts**

Extract the actual inner installer/archive files and formal sidecar SHA files.

- [ ] **Step 4: Independently verify packages**

Recompute SHA-256; validate archives against traversal/symlink escape; validate manifests; validate Mac arm64 and Windows AMD64; confirm the embedded Core runtime contains migrations through 13 plus retained business/creative/production modules; confirm the Windows package contains the frozen workflow templates and Production panel/executor assemblies.

- [ ] **Step 5: Keep PR Draft/Open/Unmerged and deliver installers**

Do not merge `main`, tag or create a GitHub Release. Real-machine Wan2.2 output quality remains the user's daily acceptance step.
