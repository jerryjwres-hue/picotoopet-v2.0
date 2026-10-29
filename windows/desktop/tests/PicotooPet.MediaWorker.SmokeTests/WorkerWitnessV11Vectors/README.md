# Issue #162: Windows signer STOP report and Core compatibility oracle

Status: **BLOCKED — no Windows key holder or signer implemented.** These offline
fixtures are not a completed #162 deliverable, native verification, enrollment,
an executable attestation, a claim credential or permission to run I2V.

Frozen base: `22cda5f12487b0ecd09e87b248350e436760e51f`.
Read the full #162 body and these frozen, unmodified Core implementations:

- `src/picotoopet_core/production/versioned_plan.py`: both witness models,
  `signed_payload`, `require_fresh`.
- `src/picotoopet_core/security/worker_pairing.py`: local-console enrollment,
  fingerprint/key ID, revocation, challenge issuance and transactional verification.

## Concrete dependency blocker

Issue #162 explicitly confines implementation to `Services/ProductionReference/**`,
NEW smoke-test files, and, only if necessary, `ProductionExecutionService.cs`.
It also explicitly requires STOP if a suitable signing primitive cannot be
established within the existing release constraints. That condition currently
applies; it is not permission to substitute another curve or ship a helper.

The existing application project has only Desktop.Core and ReferencePreview.Codecs
references. Its restored assets contain SkiaSharp 3.119.4 and native Win32 preview
assets; no Ed25519 library is present. The SDK is pinned to 10.0.302. The installed
net10.0 reference API (`Microsoft.NETCore.App.Ref/10.0.10`,
`System.Security.Cryptography.xml`) exposes ECDsa, ECDH and ML-DSA, but no Ed25519
sign/verify primitive. A string passed to `CngAlgorithm` is not evidence of a
supported Ed25519 provider on the application's Windows 10 target. There was no
native provider support test, and this report does not claim exhaustive absence
of every third-party Windows provider.

DPAPI can protect stored secret bytes but supplies no Ed25519 signing primitive.
Do not use OpenSSL/Python executables, unprovisioned native DLLs, reflection-loaded
downloads, runtime package installs, hand-written Ed25519 or an ECDSA fallback.
Adding a proven managed Ed25519 package is a plausible next step, but requires
changing `PicotooPet.Desktop.csproj` (outside the stated ownership). No package,
project reference, release script or dependency declaration was changed here.
Candidate packages still need version/license/provenance and actual native
Windows publish/restore verification; this report does not assert that a candidate
has already been vetted or installed.

Unblocking requires explicitly allowing the minimal Windows project dependency
declaration and selecting/verifying that dependency. No user-device operation or
real operator key enrollment is needed to implement/test a disposable CI key.
Real Mac operator confirmation is required later for an actual paired identity.

## Exact signed bytes from the frozen Core

`generate.py` calls the actual frozen `WorkerWitnessV11.signed_payload`, then uses
the existing Python `cryptography==50.0.2` test environment to sign/verify. The key
is the publicly known RFC 8032 section 7.1 TEST 1 seed, strictly fake and offline.
`vectors.json` records complete witness objects, public key/fingerprint, payload
hex and SHA256. It is not loaded by the Windows application or native harness.

Reproduce from the repository root:

```sh
.venv/bin/python windows/desktop/tests/PicotooPet.MediaWorker.SmokeTests/WorkerWitnessV11Vectors/generate.py
git diff -- windows/desktop/tests/PicotooPet.MediaWorker.SmokeTests/WorkerWitnessV11Vectors/vectors.json
```

The two vectors exercise whole-second and six-digit fractional UTC dates,
non-ASCII/astral characters, quote/backslash/newline escaping and an integer above
JavaScript's exact-number range. The generator verifies each signature and rejects
an appended newline. Their fixed historical timestamps must fail live freshness.

- Prefix: ASCII `picotoopet.production.worker_witness.v1` followed by exactly LF.
- Body: Core `model_dump(mode="json", exclude={"signature"})`, recursively sorted
  JSON keys, compact separators, UTF-8 without BOM, `ensure_ascii=False`.
  Include schema defaults; preserve reference-array order; no trailing newline.
- Canonical UTC dates are Pydantic JSON output: `...00Z` or `...00.123456Z`.
  Do not sign the original incoming `+00:00` representation, .NET's seven-digit
  `O` representation, HTML-escaped Unicode, CRLF or a floating-point generation.
- Algorithm is exactly `ed25519`, signature 64 bytes/lowercase 128 hex digits.
  Fingerprint is lowercase SHA256 of the raw 32-byte public key, not PEM/SPKI;
  Core key ID is `wk-` plus the first 40 fingerprint hex digits.
- Every reference binds task/shot/asset/approval and approval request digest,
  source hash/size/path, snapshot hash/size/path, receipt hash and graph digest.
  Outer fields bind executor/job/plan, executable hash and journal state/generation.

These artifacts establish only the Core oracle. **Windows byte compatibility and
native sign/verify remain UNVERIFIED**, until a real Windows implementation is
compared with the stored payload bytes and signatures.

## Resume plan after the dependency boundary is resolved

1. Write native tests first for actual Ed25519 vector signing/verification,
   payload mismatch, wrong key and prohibited placeholder fields. Add only a
   minimal test-harness invocation with explicit ownership authorization if
   existing `Program.cs` must change; NEW files alone are not executed today.
2. Implement an internal key holder using the selected proven primitive and
   Windows CurrentUser DPAPI with UI forbidden, restricted owner-only ACLs,
   reparse denial, exclusive/create-only atomic persistence and a versioned,
   executor-bound record. Zero temporary plaintext private buffers. Export only
   raw public key/fingerprint. Never regenerate silently after corruption,
   inaccessible state, key mismatch, or partial/crashed creation. Account-bound
   DPAPI does not prove which same-user EXE used the key.
3. Require the expected Core-approved fingerprint/key ID, authenticated fresh
   challenge and exact frozen scope; before signing recheck pinned measurements,
   approval and existing GPU-lock/journal uncertainty. Reject all unknown POST
   states. Do not expose a generic arbitrary-payload signing endpoint. A
   durable local nonce-use record must fail closed across restart/rotation;
   Core remains the final replay/revocation authority.
4. Test real child-process reopen, persisted public identity, DPAPI blob tamper,
   corrupt/partial key state, fingerprint rotation mismatch, stale/invalid nonce,
   stale scope, concurrent sign/restart and zero Comfy requests using disposable
   CI credentials/directories only. Do not claim same-user malware isolation.
5. Preserve the real factory's unconditional proof-required gate until the
   authenticated challenge transport, Core transactional admission, native
   cross-end evidence and executable attestation are separately approved.

## Proposed transport boundary (not an implemented/frozen API)

No challenge/enrollment HTTP route exists in the frozen Core. Do not invent one
authenticated only by the UI bearer. A future independently authenticated paired
Worker channel must return `worker_key_id`, full expected public-key fingerprint,
executor/job/plan scope, nonce and Core UTC `issued_at`/`expires_at` (maximum 30s).
Core must check active key, exact job/plan, nonce scope, issue/deadline ordering,
revocation and one-use consumption in the same SQLite transaction as any future
claim/approval/attempt operation. The Windows response would be exactly the frozen
`WorkerWitnessV11`, with no payload-supplied trusted key or admission boolean.
Transport authentication, authority provenance and crash semantics still require
controller approval; this is a field checklist, not a new endpoint contract.

The ordinary Bearer never enrolls, approves or rotates a Worker key. Mac's
interactive local-console confirmation/revocation remains the sole key authority.
Even a valid signature cannot prove the actual executable/Comfy state or authorize
production claim. `ShippingReferenceComposition.RequireVerifiedWorkerProof`
remains unchanged and production I2V remains **BLOCKED**.

## Validation boundary

Only offline vector generation and existing Core negative tests can validate this
STOP report. Existing native Same-EXE tests can guard the retained shipping gate,
but cannot certify an absent Windows signer, OS-protected key persistence or
restart/tamper behavior. A prior issue's native PASS is not evidence for this HEAD.
The PR must remain Draft and #162 must not be marked complete on this evidence.

Checks performed for these artifacts:

- Generator and deterministic regeneration: PASS; both valid signatures verified,
  appended-byte tampering rejected. Ruff on the new generator: PASS.
- Existing Core witness/key-nonce/HTTP negative tests: 42 PASS.
- SDK 10.0.302 Windows-target cross-build: PASS, zero warnings/errors; Linux
  diagnostic only, no native key-store or signer verification.
- Full existing Python suite: 1602 PASS, 1 FAIL:
  `tests/unit/providers/test_provider_commit_execution.py::test_local_commit_builder_avoids_hooks_filters_and_writes_only_namespaced_ref`.
  The filter sentinel assertion is the previously observed unchanged baseline
  failure; no provider/Git builder implementation or test was modified here.
- Native Same-EXE CI: NOT RUN when preparing this report. No Run ID is claimed.
