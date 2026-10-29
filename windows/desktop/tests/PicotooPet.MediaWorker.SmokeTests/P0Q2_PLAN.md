# P0-Q2 durable reference snapshot implementation plan

Issue: https://github.com/jerryjwres-hue/picotoopet-v2.0/issues/142
Base: `1698fee9e843c3be2de1a5185c49a5db4020af72` (Preview156).

Goal: add crash-retained private LoadImage copies to the existing same-EXE executor,
without enabling real I2V or changing v1.0 T2V, Core, UI, final mux or workflows.

Use the frozen `reference_asset.v1`, `CoreReferenceApprovalSource`, existing
`TrustedReferenceAssetVerifier` and local file policy. A snapshot is not approval.
An internal dependency-injection seam permits the frozen authenticated fake-Core
contract to reach fake Comfy. All shipping constructors remain disarmed until the
controller validates Core v1.1 claim and the operator explicitly authorizes use.

- [x] Tests first: exact approved v1.1 reference, wrong identity/rights/hash/bytes,
  missing or changed original, unsafe paths and reparse points.
- [x] Implement private deterministic content-addressed copies, flushed bytes,
  create-only immutable identity receipt and persistent Windows write/delete denial.
  Never overwrite UI staging; retain copies indefinitely (no unsafe garbage collector).
- [x] Integrate before claim/POST under the existing GPU lock. Bind the private
  LoadImage path in the existing graph digest/journal. Reopen and reauthorize on
  restart; never recreate a missing/tampered snapshot after any submission intent.
- [ ] Native execution of restart tests before/after snapshot publication, attempt reservation,
  POST/ack, pending queue and unknown history. Assert no duplicate POST and the
  existing HOLD/ALLOW/attempt ceiling. Keep real constructors' failsafes intact.
- [ ] Build with exact SDK 10.0.302, run existing Windows native Actions (unchanged),
  record SHA/run ID and create Draft PR. No release/install/GPU or local machine.

Review focus: revoked approval between admission and POST; unknown prior prompt;
receipt/graph substitution; same-user GUI/Worker staging race; mutable ancestor
or reparse-point replacement while the process is down. File-system durability
assumes NTFS and stable namespace ownership for the configured Comfy input root
AND every ancestor above it throughout queued Comfy work. The worker does not
change ACLs on arbitrary user-profile/drive ancestors. This deployment trust
condition must be verified by the controller before enabling real I2V. Ordinary producer/consumer
access is denied write/delete on retained snapshot paths. Administrator/owner
deliberate ACL takeover is outside an application-local snapshot's threat boundary.

Native tests, including ACL and process-death probes, are mandatory. Linux cross
compilation is diagnostic evidence only. No native success is claimed without an
actual Windows Actions run on the exact PR head.

## Current validation evidence

- New private-snapshot API and executor admission test were executed red before
  implementation (`I2V_V11_CRASH_DURABLE_SNAPSHOT_REQUIRED`, exit 134) in a Linux
  diagnostic runtime; this was not Windows native verification.
- SDK 10.0.302 Windows-target cross-build: success, zero warnings/errors.
- Existing three-shot/T2V regression entry: passed with Linux diagnostic runtime.
- Full Python suite: **1473 passed, 1 failed**. The unchanged baseline test
  `tests/unit/providers/test_provider_commit_execution.py::test_local_commit_builder_avoids_hooks_filters_and_writes_only_namespaced_ref`
  reproduces alone on Git 2.52.0. Instrumentation identified the first filter
  witness at the existing `git write-tree` in `ProviderLocalCommitBuilder`'s
  repository validation. Both Python implementation and test match base HEAD;
  neither is changed by this Windows-owned issue.
- Windows ACL/process-death/positive-I2V runtime checks: **UNVERIFIED** until the
  unchanged `P0 Same EXE Worker Native` Actions workflow runs on the PR head.
- GitHub API egress (`api.github.com`) is blocked by the current environment
  policy. A required-domain configuration draft has been saved; saving the draft
  does not apply it. Draft PR creation/Actions query need that runtime access.
- No GPU/model, installation, release, UI/Core/final-mux/workflow changes.
