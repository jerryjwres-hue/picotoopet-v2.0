# #152 operator-trusted private host pilot — approved B implementation

Authority: owner decision in #152 comment 6614504993 and explicit current user
instruction. Frozen start `6b48f6e49c2895afc57c2546a9c75255d13bc6ac`.

Trust Windows OS/account, exclusive GPU lock, local pinned image/EXE measurements,
Journal and Comfy history on the owner's paired private hosts. DPAPI/Ed25519 prove
key possession, not hardware or independent remote execution attestation.
Same-account malware, admin compromise, journal rollback/deletion and dishonest
Comfy are outside B. No device deployment, live enrollment, approvals, models,
Comfy startup, GPU render, merge or release is authorized this round.

## Frozen minimal interface

- Reuse existing `POST /production/jobs/{id}/worker-challenge` and canonical
  `WorkerWitnessV11`. Existing `/witness/preflight` remains expected-deny.
- Extend existing `/claim` with optional `worker_witness` (same canonical witness).
  Legacy `{executor_id}` is unchanged and still cannot claim v1.1. Reply uses the
  existing ProductionClaimRecord, no separate authorization token service.
- Explicit local Mac-console pairing pins `OPERATOR_TRUSTED_PRIVATE_HOST_V1` on
  the existing key row. Existing/strict keys default to unverified and cannot
  authorize B. Ordinary Bearer or request fields cannot select the policy.
- In ONE SQLite BEGIN IMMEDIATE: audit frozen Plan/task/approval/attempt/lease,
  active B key, real Ed25519 signature and current unspent nonce; redeem nonce,
  bind its witness to the exact new Lease and allocate the Lease. Roll back all
  on failure. Subsequent mutations must validate the admitted Lease, active key
  and approval, and cannot use a manually planted legacy Lease.
- Same-EXE Windows prepares/pins snapshots and signs under the existing GPU lock,
  claims through the existing session, and rechecks references, approval, task,
  journal and graph immediately before durable intent and Comfy POST. Preserve
  the existing HOLD permit before Claim and before each POST.
- First pilot has no unresolved prior POST. Unresolved/unknown prior Journal or
  Core Attempt => STOP/reconcile through existing recovery; never clear Journal,
  invent prompt IDs or automatically repeat an ambiguous POST. Restart tests
  must prove no duplicate submit. v1.0 behavior remains unchanged.

## Implementation plan

1. Core task: add failing focused native tests; implement existing-key policy,
   atomic witness Claim and admitted-Lease mutation guards. Files owned: Python
   production/security/db/routes and new Core tests only.
2. Windows task: add failing focused native tests; integrate the existing signer,
   reference snapshots, Session and ProductionExecutionService. Files owned:
   Windows production/signing/execution and new Windows tests only.
3. Integration: extend existing #177 disposable real FastAPI/Windows HTTP harness
   with B admission/negative cases and zero-render recovery checks. Use focused
   macOS-15 and windows-2025 native CI; all fake fixtures stay on runners. Do not
   compile or run CI on the owner's daily machine.
4. Review the complete delta, resolve issues, read exact-SHA native logs, publish
   a Draft PR and deployment/rollback plus image/budget request. Stop at HOLD.

Implementation uses independent file ownership after this interface freeze.
Record RED/GREEN source SHAs and actual CI runs in the final PR/report. Existing
expected-deny tests are not evidence that B admission works; demonstrate an actual
disposable-fixture Lease and exactly one fake HTTP Comfy submit with recovery.
