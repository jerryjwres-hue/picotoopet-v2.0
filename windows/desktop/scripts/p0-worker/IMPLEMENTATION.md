# P0-B Windows background media worker plan / ledger

Spec: Issue #92, frozen base b1977ffc36d9151e1b8ff17d369583d0ed0e0334.
Goal: UI-independent per-user Comfy production, without a second renderer/assembler.
Only Issue #92 owned files may change. No service/task installation, local source builds,
official Release Builder, G006/Core/UI/safety-owner changes, merge/rebase/tag/release.

## Architecture and tasks

1. RED on Windows CI: isolated offline harness asserts existing executor accepts a headless
   gateway rather than requiring ControlCenterSession. New focused workflow uses windows-2025,
   warning-as-error builds, no GPU, and uploads logs plus precompiled diagnostic worker only.
2. Reuse ProductionExecutionService: add gateway composition, durable submission journal before
   POST, exact plan/task/prompt binding, Core snapshot recovery, heartbeat independent of poll,
   cross-process per-user GPU gate. Never repeat a Succeeded task or unknown-submitted prompt.
3. New Core.Production helpers: atomic bounded journal (no lease/token/prompt text), fixed-loopback
   read-only Comfy queue/history reconciler, process gate and headless polling loop. Mac Core stays
   the fact source; journal records only local submission uncertainty, not terminal Production state.
4. New MediaWorker executable reuses paired settings/Credential Manager and existing clients.
   Explicit start/stop only; GUI teardown cancels observation, not worker. Keep existing assembler
   and QA paths untouched. New tests cover uncertain POST, restart, leases, single GPU and reconnect.
5. Draft PR, native Windows focused CI SHA/Run ID, exact ownership review, honest live-GPU status.

## Review focus

- Lost POST response or crash before prompt binding must not produce a second submission.
- Restart while old prompt runs must prevent other jobs entering GPU, even after local lock release.
- Core reservation/commit network loss must preserve current attempt, not consume retry budget.
- GUI close only ends observation; explicit worker stop never fabricates Core cancellation/results.
- Failed/unknown reconciliation and unavailable credentials/API/model/tools must be bounded/readable.

Ruling: verification runs on GitHub native Windows only, per user prohibition on local builds.
Ruling: no autostart installation or silent launcher; operator starts a precompiled per-user host.
Ruling: unknown submitted work stays blocked until exact reconciliation; safety over duplicate GPU work.

## Progress

- Scope and frozen base verified; Issue #92 full body/comments read (no comments).
- Task 1: RED harness + focused CI prepared; awaiting native execution evidence.
