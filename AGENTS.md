# PicotooPet Agent Instructions

These instructions apply to every coding, debugging, packaging, release, and documentation task in this repository.

## Non-negotiable goal integrity

A blocker may change schedule or verification status. It may not change the approved product goal.

Do not substitute, downgrade, reinterpret, or narrow any approved requirement merely because CI quota, platform access, dependencies, connectors, signing, time, or tooling are unavailable.

The following changes require explicit user approval **before implementation**:

- product form or user-visible surface;
- UI technology or host application;
- integration point or navigation location;
- control-plane / execution-plane boundary;
- fact source or persistence model;
- install, update, verification, or rollback workflow;
- acceptance criteria or mandatory native-platform gates;
- security, privacy, approval, or data-preservation boundary.

Words such as “temporary,” “equivalent,” “fallback,” “helper,” “prototype,” “local,” or “diagnostic” do not authorize a substitute to be described as the formal deliverable.

When a required environment is unavailable, use `BLOCKED`, `UNVERIFIED`, or `DIAGNOSTIC`. Preserve the approved architecture and continue only work that does not falsify completion.

## Frozen Windows delivery surface

The formal Windows application is the existing native WPF program:

```text
Picotoo Pet AI.exe
```

Slice D must be implemented inside its existing Task Center. Creation, observation, cancellation, retry, and result rendering belong in that WPF page.

The following are not acceptable substitutes:

- browser or localhost HTTP UI;
- WebView, Electron, or another web shell;
- a separate Slice D Helper executable;
- CLI, CMD, PowerShell, or script UI as the daily product surface;
- a second application that duplicates Task Center behavior;
- a package built or compiled on the user's daily Windows machine.

Formal Windows packages must reuse the existing versioned activation, INSTALL, VERIFY, ROLLBACK, Desktop, Start Menu, and Startup shortcut lifecycle.

## Frozen Mac and queue boundaries

- Mac Core + SQLite Queue/Outbox is the fact source.
- Windows Control Center observes facts and sends controlled commands; it does not invent terminal state or become a Worker.
- Mac Worker executes only explicitly registered task types.
- Historical `analysis` tasks must remain unsupported, unleased, and unmodified.
- No Provider call, upload, paid inference, project scan, log-body capture, token capture, or user-file enumeration may be added to `system.diagnostic_snapshot`.

## Development and release discipline

- Read the current handoff, approved specs, plans, and incident ledger before changing architecture or delivery.
- Use TDD: no production behavior change without a failing test first.
- Diagnose root cause before attempting fixes.
- Do not declare completion without fresh verification evidence.
- Do not merge `main`; use isolated branches and Draft PRs.
- User daily machines may install prebuilt packages and run VERIFY/ROLLBACK, but may not compile source, install development SDKs for the project, act as CI runners, or perform iterative debugging.
- `user_install_allowed=true` requires successful native target-platform verification.
- Any package that violates `contracts/release/project-goal-invariants.json` is not a formal PicotooPet release.