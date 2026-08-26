# Autonomous Intelligence E2E Goal Center — Implementation Plan

**Date:** 2026-08-18
**Base:** `feature/autonomous-intelligence-slice-c-2.3.27.1` @ `fb9b9c03cbb5f769e4443220c5b025c6072eca12`
**Delivery:** `2.3.27.1`

## Frozen boundaries

- PicotooPet Windows remains the sole daily control-center UI.
- Mac Core remains the canonical task/result/audit/evidence source of truth.
- Mac Worker executes only explicitly registered task types.
- Research Gateway remains the fixed read-only research executor; Windows never crawls or shells.
- Browser intake accepts public-page capture only and never accepts passwords, cookies, tokens, session secrets, or account-write actions.
- Maotai OS 4.1 SQLite/UI are compatibility sources only and never become a second live fact source.
- Web ChatGPT upload remains an explicit human action. The program may generate/download/open the handoff package and copy its prompt; it must not log in to or automate ChatGPT web.
- Maotai Natural Motion V2 release gates remain untouched.

## Task 1 — User goal + handoff Core API

**TDD RED:** add authenticated API contracts proving Mac Core can create/list/get a human Goal, return suggested goal templates, and generate/get the deterministic Web GPT handoff package for a Goal. Existing provider handoff routes remain unchanged.

**GREEN:** add a dedicated autonomous API service/router backed by `AutonomousGoalRepository`, `WorkflowService`, `ResultStore`, and the existing `WebGptHandoffBuilder`. No inline provider execution.

## Task 2 — Goal-to-workflow orchestration

**TDD RED:** prove a human product-research/video goal creates a bounded workflow using existing capabilities in order: discovery/research evidence → local analysis → creative synthesis → handoff-ready. Missing capability must move the goal to a truthful waiting/deferred state rather than fabricate success.

**GREEN:** add a deterministic human-goal planner/orchestrator. Core owns plan/stop conditions; the local model only performs semantic analysis. Reuse existing `autonomous.discovery.v1`, `autonomous.local_analysis.v1`, business/creative capabilities and result records.

## Task 3 — Maotai 4.1 one-time compatibility import

**TDD RED:** prove import is read-only, idempotent, bounded, and maps legacy product/signal material into canonical Mac Core evidence. The importer must reject writes to the legacy database, reject secrets, and never promote machine predictions to ground truth.

**GREEN:** add an explicit compatibility importer invoked through a Core-controlled endpoint/service. Imported rows receive provenance, checksum, external-id/dedupe keys, source timestamp, and import manifest. Old DB stays archive/read-only.

## Task 4 — Browser Bridge public capture intake

**TDD RED:** prove authenticated intake accepts only the existing `BrowserBrokerPacket` public-page contract, rejects forbidden session/credential fields and oversized payloads, and persists only through the canonical Core evidence ingestor.

**GREEN:** add a dedicated Browser Bridge intake route/service. The browser extension/bridge remains an acquisition executor; it never writes SQLite directly.

## Task 5 — Windows Goal Center

**TDD RED:** add native WPF smoke/contracts for a high-level goal input, suggested goal actions, current goal status, human-attention state, completed result summary, `查看结论`, `打开交接包`, and `复制 GPT 提示词`. The UI must use authenticated Mac Core APIs and must not invent terminal states.

**GREEN:** reshape the existing simple-mode home hero into Goal Center while preserving task/history surfaces. Extend `MacCoreClient` and `ControlCenterSession` with bounded autonomous-goal/handoff operations. Keep token handling unchanged.

## Task 6 — Integrated native delivery

**TDD RED:** extend delivery contracts so the Mac package verifies autonomous goal API/orchestration/import/browser intake/handoff prompt inside the wheel, and the Windows package verifies Goal Center client/UI contracts.

**GREEN:** build native Mac arm64 and Windows candidates through existing CI gates, run install/verify/rollback fixtures, then assemble a user-facing combined handoff ZIP containing verified platform installers, checksums, and Chinese install order.

## Completion gate

Do not call the end state complete until all applicable Core/Worker Python regression, Ruff/shell checks, native macOS arm64 package verification + install/rollback fixture, Windows release/UI contracts + native WPF build/smoke, artifact SHA checks, and the final combined-package manifest pass. A pre-existing Natural Motion V2 asset-gate failure may remain documented but must not be bypassed.