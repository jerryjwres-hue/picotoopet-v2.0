# PicotooPet 2.3.26.1 — Operator Simple Mode Design

## Goal

Turn the existing Windows Control Center into a daily-use operator console centered on **new task, review, monitor, result**, while preserving the full 2.3.25.1 architecture and governance model underneath.

## Baseline

- Base branch/head: `hotfix/task-center-diagnostic-stability-2.3.25.1` / `11734a1aa58c1409c7cd2b59579a3cdf5a882930`.
- Product target: `2.3.26.1`.
- Mac Core and Mac Worker remain unchanged.
- Database schema remains **18**.
- Existing 2.3.25.1 Business Automation scrolling hotfix and Task Center diagnostic stability hotfix are retained.
- Development PR remains Draft / Open / Unmerged through CI, packaging, and real-machine acceptance.

## Product Positioning

26.1 is an **operation-layer simplification**, not a new AI architecture. The existing Core durable facts, tasks, approvals, results, Work Packages, Quality facts, Shadow and Promotion governance remain authoritative.

Windows adds a projection layer that turns those existing facts into a simpler operator experience. It must not create a second task/approval/result database or duplicate durable state.

## Default Simple Navigation

The default left navigation contains only:

1. `首页`
2. `待我审核`
3. `进行中`
4. `已完成`
5. `高级`

The current engineering routes are not deleted. `高级` opens an Advanced Home page that groups and links to the existing routes.

### Advanced Home groups

**业务与执行**
- 项目
- 任务中心
- 结果
- 业务自动化
- 自动化

**人工治理**
- 审批
- Quality Evaluation / Shadow / Promotion / Rollback through the existing Business Automation controls

**系统与运维**
- 健康
- 诊断

**开发与配置**
- 云端开发
- 设置

## Simple Home

The home page follows the approved second mockup direction but removes nonessential engineering detail.

The page contains:

- one primary `+ 新建任务` action;
- `待我审核` summary;
- `进行中` summary;
- `已完成` summary;
- compact system status for Windows / Mac Core / Mac Worker;
- recent activity derived from real task facts.

Normal system state should remain quiet. Engineering details such as task IDs, schema versions, heartbeat timestamps and trace IDs are hidden behind technical detail views.

No fake progress percentages are permitted. Progress is expressed using real workflow/task stages and durable status only.

## New Task Wizard

`+ 新建任务` opens a bounded multi-step wizard.

### Step 1 — What do you want to do?

Only task families backed by currently implemented capabilities may be enabled. The initial set is based on existing 18.1–25.1 capabilities, such as existing-data analysis, content planning, and bounded business automation.

Future crawler/search integrations can add additional task families without changing the Simple Home architecture.

### Step 2 — What data should be used?

Only actually connected/supported sources may be selectable. A future source may be shown as `尚未接入`, but must not pretend to execute.

### Step 3 — Business goal

The user may enter a natural-language business goal, but the goal is only input to a closed task family / Work Package. 26.1 does not introduce a universal autonomous agent or arbitrary tool authority.

### Submission

The wizard must map to existing safe task/work-package operations. It must not add arbitrary command, shell, SQL, provider, endpoint, prompt, model or workflow execution authority.

## Pending Review

`待我审核` is the unified human-gate inbox. It may contain different approval classes but must display their semantics distinctly.

Classes include:

- ordinary business review;
- Paid-AI approval;
- Shadow / Promotion / Rollback governance decisions;
- future explicitly bounded external actions.

Each review card explains:

- what is being requested;
- why human input is required;
- risk/action type;
- what approval causes;
- whether money/external execution is involved.

Existing exact approval digests and Core authority remain unchanged. Simple Mode may invoke existing bounded approve/reject operations but may not bypass them.

## In Progress

`进行中` answers “what is the system doing now?” using real states only.

Operator statuses include:

- 正常运行
- 等待输入
- 等待审核
- 失败
- 已暂停/已取消 where the underlying state supports it

Cards show task name/type, current stage, executor plane, last update and safe error summary. Technical identifiers remain available only in details.

## Completed

`已完成` is a unified result-facing projection over existing Results / Return Packages / Creative Packages / Production Packages / diagnostic outputs where appropriate.

The operator sees the business result first; provenance and technical package details remain accessible as details. No durable result facts are copied into a second persistence model.

## Advanced Mode

`高级` is a landing page, not an expansion of all old routes into the default sidebar. It preserves access to the existing engineering pages and their current behavior.

Advanced pages remain the source for deep troubleshooting and governance inspection. Simple Mode does not remove capabilities or hide errors permanently.

## System Status

Simple Home shows three compact status rows:

- Windows
- Mac Core
- Mac Worker

When healthy, display concise healthy/online/idle state. When unhealthy, show the actionable problem and a route to Diagnostics/Health.

## Architecture

### Operator Projection Layer

26.1 adopts a Windows-only projection architecture:

`Existing Core facts / tasks / approvals / results`
→ `OperatorProjection`
→ `Simple Mode ViewModels`
→ `WPF Simple Mode pages`

No `simple_tasks`, `simple_approvals`, `simple_results`, or other parallel durable stores are introduced.

### Existing pages

Existing routes and page ViewModels remain available. The Shell gains Simple Mode routes and an Advanced Home route that can navigate into the existing route set.

### Snapshot stability

The 2.3.25.1 selection/snapshot stability lessons apply to all Simple Mode pages: background snapshot refresh must preserve logical selection by durable identity and must not rebuild pages in ways that clear active user context.

## Error Handling

- Unknown page-level WPF faults remain isolated by the existing navigation fault boundary where possible.
- Process-level unhandled WPF faults remain fail-fast and synchronously persist redacted fatal evidence through the 2.3.25.1 emergency logger.
- Simple cards use safe summaries; full secrets, Bearer tokens, provider keys and arbitrary payloads are never rendered.
- Unsupported actions render an explicit unavailable reason instead of pretending success.

## Security Boundaries

26.1 does not change these frozen boundaries:

- Paid-AI stays disabled by default.
- Paid execution requires exact approval and existing budget/profile controls.
- Windows does not hold provider API keys.
- Promotion remains governance-only and is not consumed by runtime to mutate production behavior.
- No arbitrary Provider / Endpoint / Model / Prompt / Workflow / Command / SQL authority is added.
- No automatic Git/GitHub merge, tag, release or publication.
- No automatic ComfyUI node/model/workflow installation.
- No weakening of Core durable authority or approval digests.

## Explicit Non-Goals

26.1 does not:

- integrate the new crawler/search tools;
- build a universal autonomous agent;
- enable real Paid-AI by default;
- change Core or Worker product behavior;
- change database schema 18;
- change Promotion runtime semantics;
- create a web/mobile console;
- remove existing advanced pages.

## Testing Strategy

### Contract tests

Require:

- product version `2.3.26.1`;
- schema target still 18;
- default Simple navigation contains exactly the five approved entries;
- existing advanced routes remain reachable;
- no parallel simple-mode durable tables/contracts are introduced;
- no forbidden authority fields appear in the new-task wizard.

### ViewModel tests

Verify deterministic projection into pending/in-progress/completed buckets, correct risk labels, no fabricated progress, and identity-preserving refresh.

### Real STA WPF tests

On native Windows:

- launch Shell at supported minimum size;
- confirm Simple Home is default;
- navigate through all five Simple routes;
- open Advanced Home and each existing route link;
- open New Task wizard and traverse enabled/disabled task options;
- render representative pending/in-progress/completed cards;
- execute `Measure / Arrange / UpdateLayout` after background snapshot replacement;
- verify no binding/layout exception and logical selection remains stable.

### Native CI and packaging

Windows Control Center CI must pass contract/security tests, real STA WPF smoke, warnings-as-errors build and published self-test. Formal Windows Prebuilt must pass analyzer/build/publish/self-test, delivery invariants, project-goal validation, and PowerShell 5.1 install/upgrade/activation-failure recovery/rollback lifecycle.

Mac Core/Worker may run as regression gates if repository path impact triggers them; no Mac reinstall is required unless Mac product code unexpectedly changes.

## Real-Machine Acceptance

26.1 passes when the user can:

1. open PicotooPet and land on Simple Home;
2. immediately see whether Windows/Core/Worker are healthy;
3. see whether anything requires review;
4. see what is currently running;
5. find completed results;
6. start a supported task through a bounded New Task wizard;
7. enter Advanced Home only when technical/engineering controls are needed;
8. complete these operations without source compilation on the user PC.
