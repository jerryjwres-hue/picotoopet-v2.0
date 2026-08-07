# Phase 10C Event-Stream Recovery Rollup Design

## Goal

Deliver product version `2.3.13.1` as the next formal candidate while carrying forward the complete `2.3.12.5` cold-start WebSocket recovery fix. The version must add a formal published-EXE self-test and release contract proving that bounded historical event replay does not cause a false Pong timeout.

## Approved Scope

- Start from commit `a2b4d0c83cbad81dc8b5bf210ef1875bb0c290bd` on `feature/phase10b-mock-dev-broker`.
- Preserve `EventStreamClient.DeferPingWhileEventsPending()` and its cold-start regression test.
- Change the canonical product version to exactly `2.3.13.1` across Mac Core, Windows WPF, Worker verification, goal-integrity policy, API tests and user-visible version smoke tests.
- Add a published desktop self-test that exercises the actual `EventStreamClient` assembly behavior for both states:
  - queued historical events defer Pong expiry and clear stale Ping samples;
  - after the backlog drains, an expired Ping still raises the real timeout.
- Add a release contract test that binds the version rollup, retained fix, published self-test marker and security boundaries.

## Architecture

Mac Core + SQLite Queue/Outbox remains the sole fact source. Windows remains the existing native WPF Control Center and does not become a Worker. The existing `EventStreamClient` bounded channel and heartbeat behavior remain unchanged; the new work only promotes that behavior into a formal published self-test and versioned release contract.

The desktop self-test uses reflection only inside the diagnostic self-test path to exercise the private bounded-channel heartbeat boundary in the published binaries. Normal application runtime, public APIs and UI surfaces do not gain reflection-based behavior.

## Security and Product Boundaries

- No external Provider installation, authentication or invocation.
- No arbitrary path, file, command, environment variable, credential or upload input.
- No real worktree, repository mutation, push, merge, tag or public release capability.
- No new executable, service, browser surface, WebView or localhost UI.
- No source compilation on user machines.
- PRs remain Draft, open and unmerged; `main` remains unchanged.

## Data Flow

1. The canonical version file reports `2.3.13.1`.
2. Mac Core health and package builders consume that version.
3. Windows WPF copies the same file into build and publish output.
4. Native smoke tests verify exact title and subtitle strings.
5. Published EXE self-test creates an isolated `EventStreamClient`, injects one bounded historical event and an expired Ping, and verifies no timeout while backlog exists.
6. The self-test drains the event, inserts another expired Ping and verifies the normal timeout resumes.
7. Release validation requires the self-test marker and the same canonical version across manifests and payloads.

## Error Handling

Any reflection target drift, missing channel capability, false timeout during replay, missing timeout after drain, version mismatch or stale surface string fails the self-test or contract gate with a bounded diagnostic message. No Token, path, event payload or exception body is persisted to product state.

## Testing

- RED contract test first: require `2.3.13.1`, retained recovery code and the new published self-test markers.
- GREEN version updates and published self-test implementation.
- Run focused Python contract/unit/API tests.
- Run native Windows Core SmokeTests and published EXE self-test.
- Run the existing Windows WPF, Windows Release, Mac Core arm64 and Mac Worker impact gates.
- Independently verify generated artifacts before any user installation.

## Acceptance

Source/CI acceptance requires all four native gates on the exact final head and independent artifact verification. User acceptance requires two full Windows exits and restarts without opening Settings or re-entering the Token, with the event-stream badge reaching online automatically and existing approvals, tasks, results, Handoffs and Broker Sessions loading normally.
