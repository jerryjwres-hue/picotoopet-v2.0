# P0-Q2 Core–Windows v1.1 authorization: integration handoff (Issue #152)

Scope: one Mac Core, one existing Windows same-EXE Worker; no new scheduler,
external cloud, GPU access or automatic user-device operation. Frozen composite
baseline: `e61015f829ab8676d89af9f3192c13b2be4a6bdf`.

## Evidence already implemented

- Mac Core v1.1 persists an immutable, digest-bound plan, scoped reference approval,
  task states and attempts. `ProductionService._audit_v11_core_before_lease` validates
  Core-owned state inside SQLite; it does **not** prove Windows bytes.
- Windows `CoreReferenceApprovalSource` queries live Core approval and compares the
  frozen plan, task, shot, asset identity, rights scope, SHA256 and size.
- `ProductionReferenceSnapshotStore` verifies actual Windows bytes and writes an
  ACL-protected, crash-persistent private LoadImage snapshot and receipt binding
  job ID, task ID, plan digest, graph digest and the reference identity.
- The existing Comfy journal owns uncertain POST recovery and single-GPU exclusion.
  Existing `ProductionExecutionService.Create` does **not** compose a store.
- Mac Core `claim`, `claim_job`, reserve/bind, heartbeat, failure and commit
  must remain closed to v1.1 while trustworthy Worker proof is absent.

## Minimal admission protocol to resolve BEFORE enabling I2V

1. **Authority:** identify the genuine paired Windows same-EXE Worker, not just any
   caller who knows the normal UI bearer. Specify key provisioning, replay
   resistance, source of the binding secret and revocation. A local SHA or an
   `approved=true` field is not a cryptographic or independently verified proof.
   If no separately enforceable Worker identity exists, STOP and keep v1.1 CLOSED.
2. **Per-job proof:** under the existing journal GPU lock, verify all immutable
   plan/tasks and fresh approvals, source bytes, snapshot/receipt SHA and stable
   namespace policy. Bind exact Job, executor, immutable Plan Digest, each shot/task,
   asset and approval IDs, source SHA/size, snapshot relative path, graph digest,
   and existing journal/prompt uncertainty state. Never re-create a snapshot after
   an unknown prior POST.
3. **Atomic Core admission:** validate fresh, one-use, authentic Worker evidence
   within the SAME SQLite transaction as claim and approval/attempt audit.
   Prevent concurrent claimant, stale attestation, expired/revoked approval,
   replay/cross-job/cross-task substitution, mixed v1.0/v1.1 interpretation and
   mismatched graph/plan identities. Core never claims it personally hashed
   inaccessible Windows-local bytes.
4. **POST and recovery:** recheck authority/lease/approval immediately before
   EACH new Comfy POST and keep a durable journal intent. If any API timeout,
   unknown queue outcome or missing history occurs, retain bound attempts and
   deny a second POST until the previous identity is reconciled. No generic
   "proof verified once" grant survives arbitrary reboot/lease expiry.
5. **User gate:** explicit real image/rights consent, only the accepted single
   trial 4-second shot after source CI, then manual visual review before the
   remaining two shots. The suggested `keyframe_kit.v1` is only an
   `UNTRUSTED_PROPOSAL`; no images/hashes/approval exist by default.

## Negative acceptance (required native Mac + Windows on one SHA)

Denied by default: ordinary bearer plus claimed SHA; missing or forged Worker
identity; stale nonce; replayed/cross-task proof; invalid ACL, reparse/symlink,
source-byte or snapshot tamper; missing/revoked/expired Core approval; bad Plan
Digest or user rights scope; unknown old Comfy POST; unbound attempt; expired
lease; competing Worker. None may increment attempt counts or POST to Comfy.

Always preserve legacy v1.0 T2V and C011/QA receipts. Do not advertise shipping
I2V or request local GPU until explicit original Windows and Mac native evidence.
This handoff is a contract/checklist, **not** a proof issuer or an unlocked claim.
