# Autonomous Intelligence Slice C Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate the safe, reusable Maotai OS 4.1 acquisition algorithms and Browser Bridge packet contract into PicotooPet's existing autonomous Mac Worker, then produce a native arm64 installable Worker update without introducing a second source of truth or browser-account automation.

**Architecture:** PicotooPet Mac Core remains the only canonical task/result/audit owner. The Worker gains deterministic legacy-derived query planning, source policy, adaptive scheduling helpers, and a browser-capture broker that accepts only sanitized public-page packets. Content Discovery consumes the new query planner but continues to call only the existing Research Gateway and local `gpt-oss:20b`; browser-dependent evidence remains an optional capability and never bypasses the Research Gateway/Core boundaries.

**Tech Stack:** Python 3.12, Pydantic v2, pytest, Ruff, existing Mac Worker queue/runtime, existing Research Gateway, GitHub Actions macOS arm64 delivery scripts.

**Spec:** `docs/superpowers/specs/2026-08-17-autonomous-intelligence-and-storage-design.md`

## Global Constraints

- Windows remains the human-facing control center and must not crawl or execute arbitrary shell work.
- Mac Core remains the source of truth; legacy Maotai OS 4.1 SQLite must never run as a second live fact store.
- Mac Worker executes only explicitly registered task types.
- Browser capability is read-only public-page collection; no passwords, cookies, tokens, account writes, CAPTCHA bypass, or login bypass.
- Existing `autonomous.discovery.v1` remains bounded to Research Gateway evidence plus one local Scout pass.
- Missing metrics remain missing; models may not invent engagement, velocity, review counts, product claims, or source facts.
- Native arm64 verification and install/verify/rollback evidence are required before `user_install_allowed=true`.
- The Maotai Natural Motion V2 asset gate is unrelated and must not be weakened or bypassed.

---

### Task 1: Legacy acquisition policy primitives

**Files:**
- Create: `src/picotoopet_core/autonomous/legacy_acquisition.py`
- Create: `tests/unit/autonomous/test_legacy_acquisition.py`

**Interfaces:**
- Produces: `adaptive_interval_minutes(base_minutes: int, change_rate: float, failure_count: int) -> int`
- Produces: `information_gain_score(products: int, signals: int, opportunities: int) -> float`
- Produces: `build_discovery_queries(objective: str, max_queries: int = 4) -> tuple[str, ...]`

- [ ] **Step 1: Write failing tests** covering 4.1-compatible backoff, low/high-change intervals, logarithmic gain, deterministic objective-specific query generation, uniqueness, and 240-character query bounds.
- [ ] **Step 2: Run** `PYTHONPATH=.:src python -m pytest -q tests/unit/autonomous/test_legacy_acquisition.py` and confirm import/behavior failures.
- [ ] **Step 3: Implement** dependency-light deterministic helpers ported from 4.1. Query generation must use only the supplied objective plus fixed safe research intents (`consumer pain points reviews`, `creator content trends high engagement`, `comparison purchase intent`, `recent discussions`) and must not invoke a model or network.
- [ ] **Step 4: Re-run** the Task 1 test file and confirm PASS.
- [ ] **Step 5: Commit** with `feat: migrate legacy acquisition policy primitives`.

### Task 2: Browser Broker public-capture contract

**Files:**
- Create: `src/picotoopet_core/autonomous/browser_broker.py`
- Create: `tests/unit/autonomous/test_browser_broker.py`

**Interfaces:**
- Produces: `BrowserCaptureEvidence` Pydantic model.
- Produces: `validate_browser_capture(packet: dict[str, object], *, allowed_extension_id: str | None = None) -> BrowserCaptureEvidence`.

- [ ] **Step 1: Write failing tests** for accepted public `http/https` capture packets, old protocol message names, 480 KiB payload limit, invalid/private URLs, credential-bearing URLs, recursive forbidden secret/session keys, unsupported message types, bounded visible-signal text, and stable evidence IDs.
- [ ] **Step 2: Run** `PYTHONPATH=.:src python -m pytest -q tests/unit/autonomous/test_browser_broker.py` and confirm RED.
- [ ] **Step 3: Implement** a transport-independent broker derived from the 4.1 Native Messaging safety contract. It may parse public metadata/signals but must not read browser cookies, local/session storage, auth headers, passwords, payment data, or tokens. It must not persist anything itself.
- [ ] **Step 4: Re-run** the Task 2 tests and confirm PASS.
- [ ] **Step 5: Commit** with `feat: add read-only browser capture broker`.

### Task 3: Source policy classification

**Files:**
- Modify: `src/picotoopet_core/autonomous/legacy_acquisition.py`
- Modify: `tests/unit/autonomous/test_legacy_acquisition.py`

**Interfaces:**
- Produces: `SourcePolicyMode` enum (`GREEN`, `YELLOW`, `RED`).
- Produces: `SourcePolicyDecision` model with `domain`, `mode`, `browser_session_required`, `autonomous_fetch_allowed`, and `reason`.
- Produces: `classify_source_url(url: str, *, robots_allowed: bool | None = None) -> SourcePolicyDecision`.

- [ ] **Step 1: Add failing tests** showing private/non-http/credential URLs become RED, Amazon/TikTok/TikTok Shop become YELLOW + browser-session-required, ordinary unverified public URLs remain YELLOW, and explicitly robots-allowed ordinary public URLs may become GREEN.
- [ ] **Step 2: Run** the focused test module and confirm RED.
- [ ] **Step 3: Implement** the deterministic source policy without a database registry and without making legal/compliance claims. Unknown sources default to YELLOW, never silent GREEN.
- [ ] **Step 4: Re-run** focused tests and confirm PASS.
- [ ] **Step 5: Commit** with `feat: add deterministic source policy`.

### Task 4: Content Discovery uses migrated objective-specific query planning

**Files:**
- Modify: `src/picotoopet_core/autonomous/discovery.py`
- Modify: `tests/unit/autonomous/test_content_discovery.py`
- Modify: `tests/unit/autonomous/test_content_discovery_radar_integration.py`

**Interfaces:**
- Consumes: `build_discovery_queries()` from Task 1.
- Preserves: `ContentDiscoveryCoordinator.TASK_TYPE == "autonomous.discovery.v1"` and capability `content.discovery`.

- [ ] **Step 1: Add failing tests** requiring the default coordinator to derive four deterministic searches from each task objective while preserving explicit constructor-provided `seed_queries` for fixtures/overrides.
- [ ] **Step 2: Run** the two Content Discovery test modules and confirm RED.
- [ ] **Step 3: Implement** request-time query planning. Explicit `seed_queries` remain frozen; otherwise build the plan from `request.objective`. Search limits, timeouts, tool-first ordering, Radar normalization/clustering, stop policy, and one Scout pass stay unchanged.
- [ ] **Step 4: Re-run** the focused tests and confirm PASS.
- [ ] **Step 5: Commit** with `feat: adapt discovery queries from legacy strategy`.

### Task 5: Packaging contract includes autonomous Slice C runtime

**Files:**
- Modify: `tests/contract/test_phase23_worker_delivery.py`
- Modify: `scripts/mac/phase23-worker/Build-MacWorkerSliceC.sh`
- Modify: `scripts/mac/phase23-worker/Test-MacWorkerSliceC.sh`
- Modify: `deploy/macos/phase23-worker/README_INSTALL_CN.txt`

**Interfaces:**
- Produces: native arm64 Worker update archive containing the installed Python package, verifier, rollback script, build report, and SHA-256 file.

- [ ] **Step 1: Add a failing delivery contract** that requires `legacy_acquisition.py`, `browser_broker.py`, the versioned Web GPT master prompt, and the existing autonomous discovery modules to be present in the built Worker payload or installed wheel/site-packages manifest.
- [ ] **Step 2: Run** `PYTHONPATH=.:src python -m pytest -q tests/contract/test_phase23_worker_delivery.py` and confirm RED if the package manifest omits the new Slice C files.
- [ ] **Step 3: Update** the existing Worker builder/verifier minimally so the new autonomous modules are included and verified. Do not change Mac Core ownership, task registry rules, installation roots, rollback semantics, or release safety flags.
- [ ] **Step 4: Update Chinese install instructions** to state that Slice C adds automatic objective-specific research planning and a read-only Browser Broker contract; the user does not run the old 4.1 UI.
- [ ] **Step 5: Run** shell syntax checks and the delivery contract locally/in CI.
- [ ] **Step 6: Commit** with `build: package autonomous slice c capabilities`.

### Task 6: Full regression, native arm64 CI, and installable artifact

**Files:**
- Modify only if verification reveals a real defect.

**Interfaces:**
- Produces: a GitHub Actions artifact named from the existing `PicotooPet-MacWorker-SliceD-arm64-*` workflow convention, containing the verified `.tar.gz`, SHA-256, build report, and fixture evidence.

- [ ] **Step 1: Run** the complete Python regression and Ruff on the touched autonomous/worker files.
- [ ] **Step 2: Run** `bash -n` on all touched Mac Worker install/build/verify/rollback scripts.
- [ ] **Step 3: Open a Draft PR** from `feature/autonomous-intelligence-slice-c-2.3.27.1` to `feature/autonomous-intelligence-foundation` so native Mac Worker CI runs on the isolated branch.
- [ ] **Step 4: Inspect every native CI job**. If a test/build/package/install/rollback gate fails, diagnose the exact failing step before changing code.
- [ ] **Step 5: Require** full Python regression PASS, native arm64 environment PASS, offline Worker package build PASS, archive/manifest verifier PASS, fixture install/recovery/rollback PASS, and artifact upload PASS.
- [ ] **Step 6: Download** the verified workflow artifact and retain its SHA-256/build report as delivery evidence.
- [ ] **Step 7: Do not use the unrelated Windows formal release as a blocker for this Worker feature package; do not bypass the existing Maotai V2 missing-asset gate.
