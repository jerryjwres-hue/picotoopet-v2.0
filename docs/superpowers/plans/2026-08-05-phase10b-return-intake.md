# Phase 10B-A Return Intake Implementation Plan

> **Execution rule:** TDD in small commits. Every product change must be preceded by a failing regression test, and every exact-head release claim requires native CI evidence.

**Goal:** Deliver product version `2.3.11.1` with a Mac Core-owned, deterministic local Return contract self-test, strict quarantine validation, bounded REST projections, and native WPF observation. No Provider, credential, arbitrary file, command, diff application, worktree mutation, Git write, PR, merge or release action is permitted.

**Architecture:** Add a dedicated `returns` domain and migration 4 beside Phase 10A `handoffs`. The service creates a server-owned no-op Return package for an approved Handoff, validates it through the same strict validator used by attack fixtures, persists only safe facts, and exposes bounded records. Windows extends the existing Cloud Development page through a typed gateway and native WPF controls.

**Tech stack:** Python 3.12, FastAPI, Pydantic v2, SQLite, pytest, JSON Schema, .NET 8, WPF, GitHub Actions native macOS arm64 and Windows runners.

---

## Task 1: RED — Return contract, migration and security fixtures

**Create:**
- `tests/unit/returns/test_return_validation_service.py`
- `tests/unit/db/test_return_migration.py`
- `tests/integration/api/test_return_validation_api.py`
- `tests/security/test_return_validation_security.py`
- `tests/contract/test_phase10b_return_contract.py`
- `contracts/handoff/v1/schemas/return_preview.schema.json`

**Required RED assertions:**
- migration 4 and `returns` table do not yet exist;
- approved Handoff is required;
- idempotency and deterministic digest behavior are absent;
- path traversal, symlink, duplicate path, executable, digest mismatch, event gap, secret and false test-pass fixtures are rejected;
- API routes and bounded response model do not exist.

**Verification:** run the focused pytest set and record failures caused only by missing Phase 10B-A implementation.

## Task 2: GREEN — Mac Core Return domain

**Create:**
- `src/picotoopet_core/returns/__init__.py`
- `src/picotoopet_core/returns/models.py`
- `src/picotoopet_core/returns/package.py`
- `src/picotoopet_core/returns/service.py`

**Modify:**
- `src/picotoopet_core/db/schema.py`
- `src/picotoopet_core/db/database.py`
- `src/picotoopet_core/services.py`

**Implementation:**
- add migration 4 and durable safe facts;
- build the fixed no-op package in memory;
- verify canonical paths, allowlist, SHA coverage, digests, Handoff binding, event order and secret redaction;
- persist `contract_validated` or `quarantined` only;
- never write package bytes or arbitrary paths into SQLite.

**Verification:** focused unit, migration, contract and security tests pass; existing Handoff tests remain green.

## Task 3: GREEN — Bounded REST API

**Create:**
- `src/picotoopet_core/api/routes/returns.py`

**Modify:**
- `src/picotoopet_core/api/app.py`
- `src/picotoopet_core/api/errors.py`

**Implementation:**
- add list, get and approved-Handoff self-test endpoints;
- require `Idempotency-Key` for the write;
- return only `ReturnRecord` safe projection;
- reject multipart, file bytes, arbitrary manifest JSON, path and command fields by schema.

**Verification:** integration API tests, OpenAPI generation and full Python regression pass.

## Task 4: RED — Windows typed client and view-model behavior

**Create:**
- `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/ReturnValidationSmokeTests.cs`
- `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/CloudDevelopmentPhase10BLayoutSmokeTests.cs`

**Required RED assertions:**
- Return contracts, gateway methods and bounded client do not exist;
- only approved Handoff can run self-test;
- same `return_id` refresh must retain preview;
- native page must contain Return action, list and safe projection;
- file picker, drag/drop, path input, password box, WebView, Process and shell execution are absent.

**Verification:** native Windows smoke fails only on missing Phase 10B-A types and controls.

## Task 5: GREEN — Windows typed client, session and WPF

**Create:**
- `windows/desktop/src/PicotooPet.Desktop.Core/Networking/MacCoreReturnClient.cs`
- `windows/desktop/src/PicotooPet.Desktop/Services/IReturnGateway.cs`
- `windows/desktop/src/PicotooPet.Desktop/Services/ControlCenterSession.Returns.cs`

**Modify:**
- `windows/desktop/src/PicotooPet.Desktop.Core/Contracts/ApiContracts.cs`
- `windows/desktop/src/PicotooPet.Desktop/ViewModels/CloudDevelopmentPageViewModel.cs`
- `windows/desktop/src/PicotooPet.Desktop/Views/Pages/CloudDevelopmentPage.xaml`
- `windows/desktop/src/PicotooPet.Desktop/Services/AppSelfTest.cs`
- smoke test registration.

**Implementation:**
- bounded JSON reads and one retry with the same idempotency key;
- load Handoffs and Returns together;
- enable self-test only for approved Handoff;
- preserve Handoff and Return previews independently across refresh;
- render native WPF safe projection and explicit non-execution notice.

**Verification:** real STA DataBind, Measure, Arrange and UpdateLayout pass; warnings-as-errors and published EXE self-test pass.

## Task 6: Version freeze and native release gates

**Modify only current-version surfaces:**
- `src/picotoopet_core/product-version.txt`
- current product-version tests, Windows fixtures and release contracts.

**Keep unchanged:**
- historical 2.3.9.1 and 2.3.10.1 evidence;
- Handoff / Return contract version `1.0.0`;
- Mac Worker runtime when impact detection reports no change.

**Native gates:**
- Windows Control Center WPF CI;
- Windows formal prebuilt release and PowerShell 5.1 lifecycle;
- Mac Core arm64 full regression, Ruff, OpenAPI, offline install, verify and rollback;
- Mac Worker impact detection.

## Task 7: Artifact verification and Draft PR evidence

- download exact-head Windows, Mac Core and OpenAPI artifacts;
- independently recompute archive and payload SHA-256;
- reject traversal, duplicate, link and manifest coverage defects;
- verify product version, source head, executable allowlist and Return API paths;
- update Draft PR with exact run IDs, test counts, filenames and hashes;
- keep PR open, Draft and unmerged.
