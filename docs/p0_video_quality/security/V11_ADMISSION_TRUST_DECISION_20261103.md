# #152 v1.1 admission trust decision — STOP, GPU HOLD

Frozen input: `dedcfc96a08686c0f8de9287af7b8b3130ceb6e8`.
Authority: #152 controller comment 6613851548, #164 comment 6532376199,
#177 comment 6533420793. This document proposes policy; it does not select it.

## Decision and deployment evidence

Retain every shipping deny gate. Existing Ed25519 + DPAPI + nonce proves key
possession/freshness, not independent Windows process, ACL/snapshot or Comfy
Journal provenance. No verified platform attestation verifier, measurement
policy or isolated execution/journal trust anchor is established. Therefore
atomic v1.1 Claim/nonce redemption and a shipping consumer are NOT implemented.
Adding them now would change the approved security acceptance criteria.

Read-only owner-device observation on 2026-11-03:

- Mac `192.168.68.70:8766/api/v1/health`: status/database ok, version 2.3.27.1.
- Live OpenAPI exposes v1.1 Job/reference registration, but neither
  worker-challenge nor witness/preflight. Frozen source already has both routes.
- Health/OpenAPI do not disclose a build SHA. Exact running Mac source SHA,
  launch configuration and database path are UNVERIFIED; no SSH/console access
  has been established. Missing routes prove surface skew, not its exact cause.
- Running Windows activation is `2.3.27.1-ui-preview-156-1698fee9e843`;
  manifest source_head `1698fee9e843c3be2de1a5185c49a5db4020af72`, build_commit
  `dc92480424937c9e626b51cc6af74d505e417bb5`. Actual EXE hash matches activation
  `bb500cdf7e389fcccce5c70b63726f6d12079fe109d6faef2931bda2d9188fc7`.
- Windows gate remains `mode=hold`; Comfy 8188 is stopped. No services restarted,
  operator key enrolled, live Job/approval/Journal/database changed or GPU used.

Deploying the frozen source alone restores transport, NOT production admission.
Before any deployment, read the existing Mac service's executable/source root,
git SHA or package manifest, effective environment and API prefix from its
existing operator console. Preserve the existing SQLite/artifact root; establish
backup/rollback and an approved restart window. Compare the exact release
manifest against the Windows package. Do not infer alignment from version alone.
No automatic update, schema migration, restart or database replacement is authorized.

## Options for controller/owner review

**A — retain strict independent execution attestation (current policy).** Require
fresh, independently verifiable platform measurements tied to the actual apphost,
protected snapshot and Journal/Comfy execution boundary, plus revocation and
post-crash anti-rollback. Merely moving the software key to TPM does not prove
application identity or Journal truth. Hardware presence is not attestation.
No qualified implementation/prerequisite evidence currently exists. Remain BLOCKED.

**B — explicit operator-trusted paired Windows host (minimum practical proposal).**
Trust the owner-controlled Windows account/OS, local exclusive GPU lock, pinned
snapshot byte checks, durable Journal and Comfy history as honest measurements.
Same-account malware, administrator compromise, Journal rollback/deletion and a
lying Comfy server are OUTSIDE this model; signed declarations do not detect
them. This is a deliberate reduction of the strict threat model, not equivalent
cryptographic attestation. Controller AND owner must explicitly accept it before
implementation. Nothing in this PR activates B or labels its evidence attested.

If B is accepted, reuse ONLY existing mechanisms:

1. Owner compares the complete public-key fingerprint out of band on Windows and
   Mac, then uses existing Mac local-console enrollment/revocation. Bearer never
   enrolls or elevates trust. Pin the approved release manifest/source/EXE locally;
   binary hash is an operator inspection aid, not remote process proof.
2. Core retains exact current image rights/approval digest, frozen Plan/graph and
   revocable key. Windows retains/pins snapshots, checks executable, input root,
   local Journal and Comfy history under the existing exclusive GPU lock. Unknown
   POST, changed bytes, prior unresolved intent or failed recovery => STOP.
3. Future Core admission checks the explicit accepted policy, exact scope, live
   approvals/key/nonce/attempts in ONE existing SQLite BEGIN IMMEDIATE transaction;
   redeem the nonce and allocate the sole lease together. Roll back both on any
   failure. No separate acceptance database, executor, approval service or toggle.
4. Existing same-EXE Worker alone consumes it, durably records intent BEFORE POST,
   rechecks approval/snapshot/lease immediately before POST, binds prompt_id and
   recovers through the existing Journal/history path. Ambiguous crash => STOP,
   never retry a possibly sent POST. Reconcile before requesting a new nonce.
5. GPU HOLD remains separately authoritative. First shot requires exact image
   approval, one POST, zero automatic retries, explicit budget/deadline and STOP
   rollback. Existing unresolved intents survive rollback; never clear Journal.

Do not implement a policy selector or authorization mutation before this decision.

## Narrow implementation and verification plan

- [x] Read #152/#164/#177; use the user's dedicated branch at frozen input.
- [x] Compare live route/version/activation observations read-only; record unknowns.
- [ ] Extend the existing #177 disposable FastAPI/Windows DPAPI HTTP harness with
  actual signed-wire replay/bit-flip and Journal uncertainty probes. Reuse its
  server/fixtures; no second runtime. Check 0 lease/attempt/result/Comfy connections.
- [ ] Add focused native Mac TCP HTTP negatives with the existing paired fixture;
  exercise real-clock expiry, approval revocation and concurrent replay.
- [ ] Run only affected native CI on disposable macOS/Windows runners, review
  exact-SHA logs, open Draft PR to the existing integration branch. Retain denies.

Tests are evidence of rejection and protocol interoperability ONLY. They cannot
establish owner-device execution provenance, production readiness or GPU authority.
The next owner action is a trust-model decision (A or explicit B), not a GPU request.
