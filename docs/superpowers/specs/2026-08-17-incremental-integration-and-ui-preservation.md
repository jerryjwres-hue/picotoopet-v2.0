# PicotooPet AI Incremental Integration and UI Preservation Addendum

## Status

Approved product constraint. This addendum narrows implementation strategy for the autonomous-intelligence work without changing the existing frozen control-plane / execution-plane boundary.

## 1. Product identity

The unified product name is **PicotooPet AI**.

The Windows desktop application may display the secondary product line:

> superpower v1.0

This is a product/UI label only. It does not replace the existing formal executable or release lifecycle until the corresponding release work is explicitly validated.

## 2. Incremental integration is mandatory

Autonomous intelligence must be implemented as an additive extension of the current PicotooPet program. Do not rebuild the application, replace the WPF shell, create a second daily control center, or duplicate existing Mac Core facts.

Reuse the existing components wherever their contracts already fit:

- Windows native WPF application and existing navigation shell;
- Task Center / task detail / result rendering;
- Mac Core SQLite database as the single fact source;
- existing Queue / Outbox / Result Store / Audit;
- existing generic Workflow automation tables and scheduler where suitable;
- Mac Worker lease and supported-task registration model;
- Research Gateway as the fixed research/crawler boundary;
- existing Ollama configuration for `gpt-oss:20b`;
- existing install / verify / rollback lifecycle.

New tables, services, or task types are allowed only where the current contracts cannot represent the required durable fact safely. Do not add a second scheduler or second queue when existing workflow/queue primitives can be extended.

## 3. Windows UI preservation

The current Windows UI remains the product surface. The autonomous work must use small, additive changes only:

- add a simple Goal/目标 entry point to existing navigation or home content;
- add autonomous-Mac status, priority, current-work and storage-health summaries;
- reuse existing task/result/detail pages for execution visibility whenever possible;
- preserve the existing visual language and layouts unless a specific page requires a small extension;
- do not re-create pages that already exist;
- do not replace the current interaction-polish work.

The Windows program is a monitor/control surface. It does not become a crawler, LLM worker, or background automation host.

## 4. Mac remains background-only

Mac autonomous services are background services. No new daily Mac GUI is required.

The Mac side may add background launch/service components that coordinate existing Mac Core / Worker / Research capabilities, but all durable status must flow through Mac Core facts so Windows can observe them.

## 5. Maotai component preservation

The Maotai pet component remains a separately developed UI component and must not be rewritten or coupled to autonomous scheduling.

Integration rules:

- keep the existing Maotai component boundary intact;
- reserve or reuse the existing Windows UI host region for the future component;
- autonomous services may expose simple semantic state such as `idle`, `working`, `waiting`, `attention`, or `offline` for Maotai to visualize later;
- the pet component must never be required for Mac background execution;
- missing Maotai production assets remain a formal release blocker where the existing release contract requires them; autonomous work must not bypass that gate.

## 6. Conflict-avoidance rules

To reduce regressions and runtime conflicts:

1. one canonical Mac Core database only;
2. one canonical durable task queue only;
3. one workflow scheduler family; extend existing automation before adding a parallel scheduler;
4. explicit task-type and capability registration only;
5. resource tags / locks must serialize access to scarce resources such as the large local model, browser sessions, and storage maintenance;
6. autonomous P3/P4 work must yield to explicit P0/P1 user work;
7. storage maintenance operates only inside PicotooPet-managed roots and never scans ordinary user folders for deletion;
8. legacy Maotai OS 4.1 is capability/algorithm migration material, not a second running application/database;
9. provider failure must degrade or defer the affected work rather than crash the manager;
10. all new behavior follows TDD and fresh native verification before being described as complete.

## 7. Implementation consequence

Slice A must first reuse the existing automation workflow layer and queue primitives. It should add only the minimum autonomous-goal metadata and background orchestration necessary to keep useful P3/P4 work flowing when no explicit user task is queued.

The first implementation must not redesign the Windows application. UI changes in Slice A are limited to product identity/status plumbing only if needed for verification; the richer Goal Center can be added later as a small extension of the existing UI.
