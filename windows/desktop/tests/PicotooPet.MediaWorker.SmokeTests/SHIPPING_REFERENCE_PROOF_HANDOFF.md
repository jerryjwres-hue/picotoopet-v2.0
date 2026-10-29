# Issue #153 — gated shipping composition, not I2V admission

Frozen base: `e61015f829ab8676d89af9f3192c13b2be4a6bdf`.
Controller contract read from PR #154, commit
`6572a892d22fa1ccf5ffc99c9a052ae000f57f49`,
`docs/p0_video_quality/i2v/V11_CROSS_ENDPOINT_PROOF_HANDOFF.md`.

## Plan

- [x] Add tests of the actual `ProductionExecutionService.Create(session)` composition
  against isolated loopback Core HTTP and disposable CI-only credential targets.
  Approved references and a public bearer must still produce zero claim/attempt/
  Comfy requests when a separately authenticated Worker proof is unavailable.
- [x] Compose the existing snapshot store with the real paired
  `CoreReferenceApprovalSource`, deferring the Comfy input root until preflight.
  Keep an explicit, non-configurable missing-protocol gate before preflight/lease.
  Existing unknown journal entries must take priority over new proof work.
- [x] Expose immutable local measurements of actual pinned source/snapshot/receipt
  bytes and SHA256, bound to plan/task/shot/asset/approval and graph identity.
  Measurements are NOT proof, not a new approval, and are never sent as admission.
- [ ] Run native same-EXE tests on the Draft PR head. Preserve existing v1.0 T2V,
  sole Worker, journal, ACLs and uncertain-POST reconciliation. No Core/Creative/
  Maotai/C011/workflow/release changes or user-device/GPU access.

## BLOCKED: no independently verifiable proof protocol yet

PR #154 explicitly provides a negative contract/checklist, not a proof issuer or
an unlocked claim. Do not invent a signed wire format or treat local DI, a machine
name, a random local device ID, an approval ID or a hash as paired Worker identity.

Before shipping admission can be enabled, the controller must freeze and verify:

1. Paired Worker/device identity and trusted key provisioning/storage/rotation/
   revocation, enforceable independently of the ordinary UI bearer.
2. Core-issued nonce, lifetime, single-use/replay scope and crash/reboot rules.
3. Canonical signed encoding/domain separation binding device/Worker/executor,
   job/plan, every task/shot/asset/approval, measured source/snapshot/receipt SHA256
   and bytes, LoadImage relative path, graph digest and journal/prompt uncertainty.
4. Native Core verification within the same SQLite claim/approval/attempt
   transaction, with independently checked freshness/revocation and competing
   claims. Existing claim API has no such evidence parameter in this baseline.
5. Per-POST lease/authority revalidation and same-SHA native cross-end negatives.

There is deliberately no `proof_verified=true`, environment flag, new signer,
second secret/registry, API endpoint or proof-accepting interface here. Local
measurements are inputs for future protocol design; they cannot arm the factory.
Shipping I2V remains **BLOCKED**, even when byte measurements are correct.

## Current checks

- SDK 10.0.302 Windows-target cross-build: zero warnings/errors (Linux diagnostic).
- Existing T2V/multishot fake-service regression entry: PASS (Linux diagnostic).
- Full Python suite: 1539 PASS, one unchanged baseline FAIL:
  `test_local_commit_builder_avoids_hooks_filters_and_writes_only_namespaced_ref`
  in `tests/unit/providers/test_provider_commit_execution.py`. This is the previously
  isolated Git 2.52.0 filter witness at existing `git write-tree`; no Mac implementation
  or Python test is changed here.
- Native same-EXE factory/credential/HTTP/ACL checks require the new Draft PR head.
  Cross-compilation or the old #148 native PASS cannot substitute for that run.
