# Frugal Coding Escalation — Final Code Evidence

Date: 2026-08-19

Runtime code source: `423f14ea549a3303137f4ab5ad99d2afb60dbded`

Branch: `feature/autonomous-intelligence-e2e-goal-center-2.3.27.1`

Draft PR: #41

This document records the verified code boundary before the remaining real-machine installation/authentication checks. A later documentation-only commit may advance the branch HEAD; the native artifacts below are intentionally tied to the runtime code source above.

## Final authority boundary

- Mac Core is the only source of truth for Frugal coding decisions.
- Codex and Claude Code are eligible only for coding/repository-maintenance/self-repair/technical-diagnosis work.
- Normal research/content/video goals do not enter coding providers.
- Mac Core owns provider selection, confidence/utility scoring, budgets, persisted decisions, and Provider Session creation.
- Windows cannot choose provider/model/budget/argv, increase caps, or create Provider Sessions.
- Windows may approve Handoffs, manually record Usage availability for a Core-bound approved Codex/Claude Code Handoff, read safe readiness/session projections, and issue emergency cancellation.
- Provider history used by arbitration is scoped to `provider + exact task_class cohort`; historical Wilson 95% lower bound is used conservatively.
- Default external sessions per Goal: 1. Absolute max: 2. Automatic retry: 0. Concurrency: 1.
- A second provider is possible only after a terminal failed/uncertain first local validation plus the remaining risk/budget/utility gates.
- Pending/non-terminal provider output does not count as failed/uncertain and cannot automatically spend the second session.
- No automatic install, upgrade, authentication, plan purchase, top-up, credential scraping, account Usage scraping, commit, push, PR, merge, tag, or release.
- Natural Motion V2 formal Windows asset gate remains independent and is not bypassed.

## RED → GREEN evidence

### Cohort-scoped provider history

RED: `346e307325f181feb78f5c77794637ecf19e002b`

- Mac Core full regression: `1 failed / 1056 passed`.
- Failure proved repository-maintenance history was polluted by a bounded-code-repair outcome.

GREEN: `b8cd30de1d05345eabb79b4241849f5c3b8372d7`

- Arbitration now reads comparable terminal history only from the same exact coding task class.
- Unclassified/malformed historical rows are conservatively excluded from task-scoped automatic decisions.

### Remove direct Windows Session start

RED: `809c0ac2717433ee4cb1ddd272bcd4d6d4c82938`

- Windows contract/security: `1 failed / 358 passed / 2 skipped`.
- Failure proved the old Windows client still exposed `StartSessionAsync` and directly posted the Codex Session-create route.

GREEN: `31ef66b9d66ceb1e957343eb8645ba5950ee03cf`

Removed the complete Windows start chain:

- network client start method;
- `ControlCenterSession` start method;
- Provider gateway start method;
- ViewModel start method/command;
- WPF start button;
- old smoke behavior that expected Windows to create a Session.

Manual Usage confirmation and emergency Cancel remain.

### Dual-provider Usage confirmation

RED: `099ed4b627173f60956ff8bdb73d18f932067f3d`

- Mac Core full regression: `1 failed / 1058 passed`.
- Failure proved the old Windows Usage panel was Codex-only and could leave a Core-selected Claude Code Handoff waiting indefinitely for user confirmation.

GREEN: `55c6a504f6b633a426975e36756fb7f87feb4e84`

- fixed Codex readiness GET;
- fixed Claude Code readiness GET;
- approved Handoff list accepts only Core-bound `codex` or `claude_code`;
- no provider picker was added;
- Windows can confirm Usage for either already-selected provider;
- Windows can observe/cancel Core-created sessions for either provider;
- native smoke explicitly exercises a Claude Code Handoff and Claude Code Session.

### Remove public device-token Session-create REST routes

RED: `afa144b5d2a8ad55d6aef375c8191edb09f36187`

- Full regression: `2 failed / 1059 passed`.
- With a valid paired-device Bearer token, approved Handoff, and confirmed Usage, both old public create routes returned `201 Created`:
  - `/api/v1/handoffs/{handoff_id}/provider-sessions/codex`
  - `/api/v1/handoffs/{handoff_id}/provider-sessions/claude-code`

GREEN runtime source: `423f14ea549a3303137f4ab5ad99d2afb60dbded`

- both public create routes were removed;
- both now resolve as 404;
- both are absent from exported OpenAPI;
- `ProviderSessionService.create_codex_session` and `create_claude_code_session` remain internal for the Core-owned Frugal reconciliation loop;
- public API retains readiness, manual Usage confirmation, Session list/get, and emergency cancel.

## Fresh native CI for runtime source `423f14ea...`

- Mac Core Slice B CI #2491: **SUCCESS**
- Mac Worker Slice D CI #2426: **SUCCESS**
- Windows Control Center Slice D CI #2730: **SUCCESS**
- Formal Windows Release #2723: **blocked only by independent Natural Motion V2 asset gate** `torso_neutral.png`.

Formal Windows evidence before the independent asset gate:

- release contracts: 86 passed;
- native WPF build: 0 warnings, 0 errors;
- the Natural Motion asset gate remains intentionally intact.

## Authoritative artifacts

### Mac Core #2491

Artifact id: `9386216082`

SHA256:

`49a9d67541cdde5dc9674d3323198374e2dc20627212d40ec18f049d7e839a2d`

### Mac Worker #2426

Artifact id: `9386218779`

SHA256:

`91ff8e216f41755a5b801545f5f616a2d2c0925ce5a4d62ab298bab5b123f9fa`

### Authoritative OpenAPI #2491

Artifact id: `9386215523`

SHA256:

`7cd8a2dcd0734f7a93459c2e03c89109b89e088968fe5dab4eca10ac5b6e6964`

Independent inspection confirmed:

- GET `/api/v1/providers/codex/status`;
- GET `/api/v1/providers/claude-code/status`;
- GET `/api/v1/provider-sessions`;
- GET `/api/v1/provider-sessions/{session_id}`;
- POST `/api/v1/provider-sessions/{session_id}/cancel`;
- no public Codex/Claude Session-create paths.

### Windows Control Center evidence #2730

Artifact id: `9386262261`

SHA256:

`4ede01c8b76a467b9a8eb5d212caa3f4bd94814cb6b5137cd2bc002554549a07`

This is validation evidence, not a formal Windows installer. The formal installer remains blocked by the independent Natural Motion V2 real-asset gate.

## Combined delivery

Final combined archive generated from the four authoritative artifacts above:

`PicotooPet-Frugal-Coding-Delivery-2.3.27.1-FinalCoreAuthority.zip`

SHA256:

`d4766fcd0d996105d78e0f885fbed9e4f50fb62f87a7f722b7095cf2ff2deae6`

Independent checks performed:

- outer ZIP CRC: pass;
- all inner `CHECKSUMS.sha256` entries: pass;
- all downloaded GitHub artifact SHA256 values: exact match to GitHub artifact digests;
- authoritative OpenAPI route inspection: pass.

## Remaining real-machine-only work

No further architecture or ordinary code decision requires the user to be at the computer. The remaining checks need the real Mac environment:

1. install Mac Core #2491 candidate;
2. run `VERIFY_MAC_CORE_SLICE_B.command`;
3. install Mac Worker #2426 candidate;
4. run `VERIFY_MAC_WORKER_SLICE_C.command`;
5. run `VERIFY_GOAL_CENTER_E2E.command`;
6. run `VERIFY_CODING_PROVIDERS.command`;
7. if Codex or Claude Code readiness is `not_authenticated`, the user personally completes the corresponding CLI login on the Mac and reruns the readiness verifier.

Do not request or export passwords, API keys, cookies, access tokens, refresh tokens, or browser session material during real-machine acceptance.