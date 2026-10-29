# Issue #162 — internal same-EXE Ed25519 signer

Frozen Core/source base: `22cda5f12487b0ecd09e87b248350e436760e51f`.
Controller authorization: [comment 6506447520](https://github.com/jerryjwres-hue/picotoopet-v2.0/issues/162#issuecomment-6506447520).
This supersedes d7843b63's dependency STOP report: the controller explicitly
permits the exact Desktop dependency and minimal native smoke registration.

**Production I2V remains BLOCKED.** A local signature is not Core admission,
trusted challenge transport, Mac operator enrollment or executable/Comfy
attestation. The formal factory's unconditional proof-required guard is unchanged.
No HTTP enrollment/signing route, second executor, GPU invocation or external
signing process exists. New code is internal to the existing WPF assembly.

## Implementation and checks

- [x] Exact managed `BouncyCastle.Cryptography [2.7.0]` dependency in the shipping
  Desktop project. No fallback curve, native unknown DLL or runtime download.
- [x] Closed-schema canonical payload codec and real Ed25519 signatures matching
  both fixed Core vectors, including UTF-8/astral characters, escaped strings,
  UTC date normalization and integers above JavaScript's exact-number range.
- [x] Explicit key creation only: CurrentUser DPAPI, UI forbidden; owner-only ACLs
  at creation, no reparse traversal, namespace ancestor pins and exclusive key
  read handles. Durable create-only encrypted key publication; partial/corrupt/
  missing files never regenerate. Clear seed buffers, plaintext key records and
  unmanaged DPAPI input/output are zeroed after use. Public export is only raw
  public hex, SHA256 fingerprint and Core `wk-<first 40 hex>` key ID.
- [x] Open requires expected fingerprint and executor. Rotation means a separately
  created key root/new public identity, followed by independent Mac operator
  confirmation/revocation; there is no automatic rotation or enrollment.
- [x] Internal measured signing reuses the sole existing GPU lock; denies pending
  or prior task journal records, stale/invalid nonce/window, wrong key/executor/
  job/plan/reference/path/hash/size/approval/graph. Retained snapshot leases
  reauthorize and rehash actual source/snapshot/receipt bytes. It measures the
  loaded shipping assembly, not a caller-selected executable path.
- [x] Before signing, a create-only, flushed nonce-use marker burns that nonce.
  Restart/crash cannot retry the same local marker. There is no marker pruning;
  loss/rollback by a privileged or same-user attacker is not protected by DPAPI.
  Core's authoritative transaction/revocation/one-use ledger remains necessary.
- [x] Native tests registered in the existing default Same-EXE suite: real protected
  key signature, process reopen and nonce reuse rejection, DPAPI tamper, missing/
  partial key state, expanded ACL, wrong executor/fingerprint/rotation, stale
  digest, revoked fake approval, unknown POST preservation. The same test invokes
  a local `dotnet publish --no-build --no-restore` of the real WPF project into a
  disposable directory and checks exact managed dependency and existing EXE.
- [ ] Genuine native Windows execution for the final source HEAD. Linux vector
  execution/cross-build is diagnostic; it does not prove DPAPI, NTFS or publish.

Supported journal evidence is deliberately restricted to `NO_PRIOR_POST`, generation
zero and SHA256 of UTF-8 `[]` for the empty pending set, with no record for any
covered task. This is an internal local snapshot convention, not a new frozen Core
attestation issuer. `BOUND_RECOVERY` and `UNCERTAIN` do not sign. The GPU lock is
held throughout checks/signing. Existing prior submission reconciliation is not
changed, deleted or used to manufacture a new attempt.

## Key-store boundaries

Private keys are software keys bound to the Windows user by DPAPI; they are not
TPM/nonexportable keys. No public/private export function or plaintext key file is
provided. Same-user malware, administrators, namespace owners above the controlled
root, process memory compromise and full-directory rollback are not solved by
these keys. Native file pins prevent accidental/concurrent path replacement during
operations; ACLs protect other accounts at rest. A directory left by interrupted
creation requires explicit operator recovery, never automatic key replacement.

The expected fingerprint must eventually originate from an independently verified
Mac operator enrollment/challenge channel. A string supplied by ordinary UI Bearer
is not such provenance. Since that channel is not present, **no shipping caller is
wired to this signer**; tests invoke the internal measured path with fake authority.
This keeps diagnostic signatures separate from unavailable production authority.

## Exact frozen Core oracle

Read-only references: `versioned_plan.py::WorkerWitnessV11.signed_payload` and
`security/worker_pairing.py` at the frozen commit. `generate.py` uses the public
RFC8032 section 7.1 TEST 1 seed in the existing Python cryptography 50.0.2 test
environment. These fake keys/timestamps must never be production credentials.

```sh
.venv/bin/python windows/desktop/tests/PicotooPet.MediaWorker.SmokeTests/WorkerWitnessV11Vectors/generate.py
```

`vectors.json` retains complete witnesses, public fingerprint, exact payload hex
and payload SHA256. Whole-second and six-digit fractional UTC cases sign:

1. ASCII `picotoopet.production.worker_witness.v1` + exactly LF.
2. Core `model_dump(mode="json", exclude={"signature"})`, recursively sorted ASCII
   schema keys, compact separators, UTF-8 without BOM, `ensure_ascii=False`.
   Preserve array order and schema defaults; append no newline.
3. Pydantic UTC JSON dates: `...00Z` or `...00.123456Z`, not incoming `+00:00`,
   .NET's seven-digit `O` format, HTML escapes or a floating-point generation.

`WorkerSignerTests.Vectors` compares complete bytes and deterministic signatures
against both stored vectors, verifies with the raw public key, and rejects tampered
bytes, stale dates, placeholder nonces and uncertain journal state. Native default
suite also executes existing real-factory fake-Core tests, preserving zero
claim/attempt/Comfy requests for ordinary Bearer with no independent proof.

## Dependency provenance and licensing

Official [NuGet 2.7.0](https://www.nuget.org/packages/BouncyCastle.Cryptography/2.7.0)
package author: Legion of the Bouncy Castle Inc.; source repository
`bcgit/bc-csharp`, release/v2.7 commit
`4007498b13582d90ee1eda5d9920c324428b98b3`. NuGet license expression is MIT;
package `LICENSE.md` was read and its full notice is retained in shipping assembly
metadata by `WorkerCryptoNotices.cs`, including portable output. Upstream's
additional source/component notices remain applicable; this is not a security audit.

Restored NuGet archive exactly matches the separately downloaded official archive:

- nupkg SHA256: `f091ffccab4d03993e660bace277659a79dee0972f54d7f1f4bd46d680966241`.
- nupkg SHA512 base64: `Lys+dJthpD8quONaAkRV9ke8DgET0CwBW91NeJjMVHZGvRRNO8DkdReYFfCBOCcvMpzJeC3DuLrpRuntYnq9Iw==`.
- selected net6.0 DLL SHA256: `ef92fc661e8d7ba8ec4d39a7cdfcdba41f14cb327f0d24fe79d0b5bb428899b5`.

`dotnet nuget verify --all` validated author/repository signature structures and
reported the Legion author certificate and NuGet repository certificate, but also
reported NU3018/NU3028 revocation-server reachability warnings. Online revocation
checking therefore remains UNVERIFIED in this Linux environment.

NuGet vulnerability index checked 2026-10-29: base updated 2026-10-28T05:41:06Z,
patch updated 2026-10-29T11:41:14Z. The three published BouncyCastle.Cryptography
advisories (`GHSA-v435-xc8x-wvr9`, `GHSA-m44j-cfrm-g8qc`, `GHSA-8xfc-gm6g-vgpv`)
cover versions below 2.3.1; none cover 2.7.0 in that snapshot. The SDK package-list
command itself errored (`Sequence contains no matching element`), so the official
NuGet base+update feeds were inspected directly; no SDK audit PASS is claimed.

## Remaining production blockers

Mac local-console enrollment/revocation, independently authenticated fresh challenge
transport, real process/ACL/Comfy/Journal attestation and Core's atomic claim/approval/
attempt/nonce transaction are still required. There is no public Bearer enrollment
or challenge endpoint. A future independent Worker channel needs Core-approved
key ID/full fingerprint, executor/job/plan binding, nonce and Core issue/deadline
(maximum 30 seconds). Response bytes must use the existing frozen witness schema.
This field checklist is not approval to add an endpoint or enable a claim.

A valid local signature never opens the formal factory guard. I2V remains BLOCKED
until genuine cross-end proof and native joint acceptance exist. This PR is Draft;
no release, install, user-device access, GPU run or model download is authorized.

## Current source verification

SDK 10.0.302 Windows-target cross-build: PASS, zero warnings/errors. Compiled C#
vector/signature tests and existing T2V/multishot regression: PASS on Linux as
DIAGNOSTIC only. Snapshot disposal during signing retains the native file pins
until the signer exits; native coverage includes an approval callback attempting
concurrent disposal/write and expecting denial.

Full Python regression: **1601 PASS, 2 FAIL**:

- `tests/contract/test_phase23_windows_source.py::test_tray_uses_builtin_notify_icon_and_has_required_commands`
  forbids every Desktop `PackageReference`. That old assertion conflicts with
  the explicit #162 dependency exception; the test is outside Windows ownership
  and was not modified or bypassed.
- `tests/unit/providers/test_provider_commit_execution.py::test_local_commit_builder_avoids_hooks_filters_and_writes_only_namespaced_ref`
  is the previously observed unchanged baseline Git filter-sentinel failure.

Native Same-EXE DPAPI/ACL/restart/publish results still require an actual Windows
Actions run of the new source HEAD. No native PASS or Run ID is inferred here.
