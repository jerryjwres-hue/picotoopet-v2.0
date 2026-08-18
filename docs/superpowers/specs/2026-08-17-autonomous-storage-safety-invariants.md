# Autonomous Storage Safety Invariants

This document is a normative companion to `2026-08-17-autonomous-intelligence-and-storage-design.md` and tightens the storage lifecycle boundary before implementation.

## Managed-root allowlist

The Storage Lifecycle Manager may inspect, compress, move between PicotooPet lifecycle tiers, or delete files **only** inside explicitly configured PicotooPet-owned managed artifact roots under the application's own data directory.

It may not recursively enumerate or manage arbitrary user locations such as the user's Home folders, Desktop, Documents, Downloads, Photos, external project folders, source repositories, cloud-drive folders, or unrelated application data merely to reclaim disk space.

## Protected originals

Existing project policy remains stronger than storage pressure:

> Protected original user data is never written, moved, deleted, overwritten, or compressed in place by autonomous cleanup.

If a protected original is needed for analysis, PicotooPet may create a separately managed derived artifact according to the existing approved data boundary. Cleanup may later operate on that managed derived artifact, never on the protected original.

## Model authority

`gpt-oss:20b`, Claude Code, Codex, or any future model may classify value or recommend cleanup candidates, but no model is granted direct deletion authority.

Only deterministic cleanup code may delete a managed artifact, and only after all required checks pass:

- path belongs to a managed-root allowlist;
- artifact is not pinned;
- artifact is not used by an active task;
- artifact is not the sole retained evidence for a kept claim/result/handoff;
- required derived/canonical replacement has been committed and verified;
- provenance/hash requirements are satisfied;
- retention/grace period is satisfied.

## Pressure-mode invariant

Low disk space may pause acquisition and accelerate cleanup/compression, but it must never weaken protected-data or minimum-evidence rules.

If safe cleanup cannot reclaim enough space, the system must stop low-priority P3/P4 acquisition and report storage pressure instead of deleting protected evidence.

## Audit invariant

Every autonomous deletion/compaction run records:

- lifecycle run ID;
- reason (`scheduled`, `pressure`, `critical_pressure`, or explicit user request);
- candidate count;
- removed count;
- bytes reclaimed;
- compressed count and bytes before/after;
- errors;
- immutable references to the policy version used.

The cleanup operation must be idempotent and recover safely after restart.
