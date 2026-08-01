# Picotoo Pet V2 Phase 0/1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a new, testable Phase 0/1 repository containing the Mac Core and a safe Windows ComfyUI/model bootstrap without modifying protected source assets.

**Architecture:** A packaged Python application owns SQLite state, permission enforcement, audit, results, API, WebSocket, MCP, PydanticAI and Ollama residency. Windows bootstrap scripts remain separate, discover ComfyUI Desktop state read-only, configure an external E-drive model root, and install models from a signed manifest with hash verification.

**Tech Stack:** Python 3.12+, uv, Pydantic 2, PydanticAI, FastAPI, httpx, aiosqlite, MCP Python SDK, pytest, PowerShell 5.1+, Windows Script Host, launchd.

## Global Constraints

- V1 is backup-only and must not be modified or imported as a runtime dependency.
- Protected data is never written, moved, deleted, overwritten, or directly uploaded.
- `gpt-oss:20b` is the Mac default model and must be kept resident with `keep_alive=-1`.
- Windows must not install a second `gpt-oss:20b` or a general 8B LLM in the core phase.
- Large models live under `E:\PicotooPet`; active work lives under `D:\PicotooPet`; C contains program files only.
- Every production module has tests, structured logs, installation, verification, and rollback coverage.
- Code comments are Chinese and aligned within the local block.
- Normal operation must not require Terminal, CMD, or PowerShell.

---

### Task 1: Repository and dependency baseline

**Files:**
- Create: `pyproject.toml`, `.python-version`, `README.md`, `src/picotoopet_core/__init__.py`
- Test: `tests/test_package_baseline.py`

**Interfaces:**
- Produces: importable package and console script `picotoopet-core`.

- [ ] Write a failing import/version test.
- [ ] Run the test and confirm the package is missing.
- [ ] Add packaged uv project metadata and minimal package version.
- [ ] Lock dependencies and run the test.
- [ ] Commit `chore: initialize v2 package`.

### Task 2: Configuration and runtime paths

**Files:**
- Create: `src/picotoopet_core/config/models.py`, `loader.py`, `paths.py`
- Test: `tests/unit/config/test_paths.py`, `test_loader.py`

**Interfaces:**
- Produces: `AppSettings`, `RuntimePaths`, `load_settings()`.

- [ ] Test macOS default paths, explicit overrides, secret redaction, and directory creation.
- [ ] Implement immutable settings and path creation without touching protected roots.
- [ ] Run tests and commit `feat: add runtime configuration`.

### Task 3: SQLite schema and migration runner

**Files:**
- Create: `src/picotoopet_core/db/schema.py`, `database.py`, `migrations.py`
- Test: `tests/unit/db/test_migrations.py`

**Interfaces:**
- Produces: `Database.open()`, `Database.close()`, `apply_migrations()`.

- [ ] Test WAL, foreign keys, all required tables, and idempotent migration.
- [ ] Implement aiosqlite database lifecycle and migration transaction.
- [ ] Run tests and commit `feat: add sqlite schema`.

### Task 4: Domain models and task state machine

**Files:**
- Create: `src/picotoopet_core/domain/enums.py`, `models.py`, `queue/state_machine.py`
- Test: `tests/unit/queue/test_state_machine.py`

**Interfaces:**
- Produces: `TaskStatus`, `TaskCreate`, `TaskRecord`, `ensure_transition()`.

- [ ] Test every allowed transition and representative forbidden transitions.
- [ ] Implement enums, Pydantic models, and transition guard.
- [ ] Run tests and commit `feat: add task state machine`.

### Task 5: Permission Gate and path policy

**Files:**
- Create: `src/picotoopet_core/permissions/models.py`, `gate.py`, `path_policy.py`
- Test: `tests/unit/permissions/test_gate.py`, `test_path_policy.py`

**Interfaces:**
- Produces: `PermissionGate.authorize()`, `PathPolicy.resolve_and_check()`.

- [ ] Test default deny, protected write/upload denial, allowed workspace writes, path traversal and symlink escape.
- [ ] Implement permission matrix and canonical path checks.
- [ ] Run tests and commit `feat: enforce protected data policy`.

### Task 6: Audit hash chain

**Files:**
- Create: `src/picotoopet_core/audit/models.py`, `writer.py`, `verifier.py`
- Test: `tests/unit/audit/test_hash_chain.py`

**Interfaces:**
- Produces: `AuditWriter.append()`, `verify_audit_chain()`.

- [ ] Test deterministic chain creation, redaction, and tamper detection.
- [ ] Implement canonical JSON hashing and append-only writes.
- [ ] Run tests and commit `feat: add tamper evident audit log`.

### Task 7: Result Store

**Files:**
- Create: `src/picotoopet_core/results/models.py`, `store.py`, `integrity.py`
- Test: `tests/unit/results/test_store.py`

**Interfaces:**
- Produces: `ResultStore.put_bytes()`, `put_file()`, `verify()`.

- [ ] Test content addressing, atomic writes, duplicate reuse, and protected source preservation.
- [ ] Implement SHA-256 object store and manifests.
- [ ] Run tests and commit `feat: add result store`.

### Task 8: Durable queue repository

**Files:**
- Create: `src/picotoopet_core/queue/repository.py`, `recovery.py`
- Test: `tests/integration/queue/test_repository.py`

**Interfaces:**
- Produces: create/get/list/transition/lease/recover queue operations.

- [ ] Test idempotency, dedupe, priority ordering, leases, attempts, terminal-state protection, and expired-lease recovery.
- [ ] Implement transactional repository methods.
- [ ] Run tests and commit `feat: add durable task queue`.

### Task 9: Approvals and cloud gate

**Files:**
- Create: `src/picotoopet_core/approvals/service.py`
- Test: `tests/integration/approvals/test_service.py`

**Interfaces:**
- Produces: `ApprovalService.request()`, `approve()`, `reject()`.

- [ ] Test cloud tasks wait, scoped approval resumes once, expiry and replay rejection.
- [ ] Implement approval persistence and queue transition.
- [ ] Run tests and commit `feat: add human approval gate`.

### Task 10: Event outbox and WebSocket broker

**Files:**
- Create: `src/picotoopet_core/events/models.py`, `outbox.py`, `broker.py`
- Test: `tests/integration/events/test_outbox.py`

**Interfaces:**
- Produces: durable event append, claim, acknowledge, and subscriber stream.

- [ ] Test durable ordering, redelivery, acknowledge and subscriber fan-out.
- [ ] Implement event outbox and in-memory broker.
- [ ] Run tests and commit `feat: add durable event stream`.

### Task 11: Ollama client and resident manager

**Files:**
- Create: `src/picotoopet_core/ollama/client.py`, `resident_manager.py`
- Test: `tests/unit/ollama/test_resident_manager.py`

**Interfaces:**
- Produces: `OllamaClient.list_models()`, `running_models()`, `preload()`, `ResidentManager.ensure_resident()`.

- [ ] Test installed/not-installed, already-running, preload with `keep_alive=-1`, retry and health result.
- [ ] Implement httpx client and residency policy.
- [ ] Run tests and commit `feat: keep gpt oss resident`.

### Task 12: PydanticAI runtime

**Files:**
- Create: `src/picotoopet_core/agents/models.py`, `runtime.py`
- Test: `tests/unit/agents/test_runtime.py`

**Interfaces:**
- Produces: `AgentRuntime.analyze()` returning validated `AgentResult`.

- [ ] Test model construction and structured result validation with a test model.
- [ ] Implement PydanticAI Ollama provider wiring.
- [ ] Run tests and commit `feat: add pydantic ai runtime`.

### Task 13: Service container and REST API

**Files:**
- Create: `src/picotoopet_core/services.py`, `api/app.py`, `api/routes/*.py`, `api/errors.py`, `security/auth.py`
- Test: `tests/integration/api/test_api.py`, `tests/security/test_auth.py`

**Interfaces:**
- Produces: `create_app(settings)` and `/api/v1` routes.

- [ ] Test health, project/task CRUD, cancel/retry, approvals, results, auth, idempotency and standard errors.
- [ ] Implement service container, bearer authentication and FastAPI routes.
- [ ] Run tests and commit `feat: add mac core api`.

### Task 14: WebSocket API and health supervisor

**Files:**
- Create: `src/picotoopet_core/api/routes/events.py`, `health/checks.py`, `supervisor.py`
- Test: `tests/integration/api/test_websocket.py`, `tests/unit/health/test_supervisor.py`

**Interfaces:**
- Produces: `/api/v1/events`, `HealthSupervisor.run_once()`.

- [ ] Test authenticated event delivery, database/disk/Ollama checks and resident recovery.
- [ ] Implement WebSocket route and health aggregation.
- [ ] Run tests and commit `feat: add websocket and health supervisor`.

### Task 15: MCP Hub

**Files:**
- Create: `src/picotoopet_core/mcp/server.py`, `registry.py`, `tools.py`
- Test: `tests/contract/test_mcp_registry.py`

**Interfaces:**
- Produces: `build_mcp_server(services)` with all frozen tool names.

- [ ] Test exact tool-name contract, input schema and permission checks.
- [ ] Implement FastMCP registry and service adapters.
- [ ] Run tests and commit `feat: add mcp hub`.

### Task 16: Phase 0 inventory

**Files:**
- Create: `src/picotoopet_core/inventory/scanner.py`, `report.py`
- Test: `tests/unit/inventory/test_scanner.py`

**Interfaces:**
- Produces: read-only file manifest, SHA-256 report and environment inventory.

- [ ] Test no source mutation, secret-value suppression and deterministic manifests.
- [ ] Implement scanner and report generator.
- [ ] Run tests and commit `feat: add phase zero inventory`.

### Task 17: Windows ComfyUI detection and model bootstrap

**Files:**
- Create: `windows/bootstrap/model_manifest.json`, `Detect-ComfyEnvironment.ps1`, `Configure-ComfyPaths.ps1`, `Install-VisualModels.ps1`, `WindowsBootstrap.ps1`, `RUN_WINDOWS_SETUP.vbs`
- Test: `tests/contract/test_windows_bootstrap.py`

**Interfaces:**
- Produces: JSON/HTML inventory and idempotent model installation under `E:\PicotooPet`.

- [ ] Test manifest filenames, repositories, destination categories, SHA-256 values, protected-resource exclusion and required script safeguards.
- [ ] Implement discovery of the supplied Desktop path plus AppData and drive candidates.
- [ ] Implement backed-up incremental YAML configuration without modifying `resources\ComfyUI`.
- [ ] Implement `uvx hf download`, temporary download, hash check, quarantine and atomic placement.
- [ ] Implement hidden double-click launcher and reports.
- [ ] Run tests and commit `feat: add windows visual bootstrap`.

### Task 18: Mac launchd, installer, verification and rollback

**Files:**
- Create: `deploy/macos/*.plist`, `scripts/mac/*.command`, `src/picotoopet_core/cli.py`
- Test: `tests/contract/test_macos_deploy.py`, `tests/integration/test_cli.py`

**Interfaces:**
- Produces: double-click install/verify/repair/backup/rollback and launchd services.

- [ ] Test plist labels, KeepAlive, program paths, CLI health and rollback metadata.
- [ ] Implement CLI subcommands and macOS scripts with Keychain token storage.
- [ ] Run tests and commit `feat: add mac deployment`.

### Task 19: Contracts, documentation and full verification

**Files:**
- Create: `contracts/schemas/*.json`, `contracts/openapi/mac_core_v1.openapi.json`, `docs/phase0/*`, `docs/phase1/*`, `VERIFY_RELEASE.command`
- Test: all tests plus schema validation and secret scan.

**Interfaces:**
- Produces: release verification report and distributable ZIP.

- [ ] Export Pydantic JSON schemas and OpenAPI.
- [ ] Write installation, validation, rollback and operator documentation.
- [ ] Run `uv run pytest`, type/format checks and secret scan.
- [ ] Build release ZIP and SHA-256 manifest.
- [ ] Commit `release: phase zero and one handoff`.
