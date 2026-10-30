# P0-Q2 #177 — Actual Core↔Worker HTTP interoperability, CPU only

Scope: disposable GitHub **Windows** runner; Draft PR from frozen `b7a00ebbe00c59e32b3c304b874d9b5283de5ee5`. This test does not enroll a real user device or authorize a production GPU job.

The dedicated workflow starts **real Python FastAPI production routes** from `picotoopet_core.api.routes.production`, wired to the existing `ProductionService`, real `Database` (SQLite WAL), existing production error handlers and shared HTTP bearer middleware. It listens only on `127.0.0.1` and is stopped in `finally`. It does **not** use the prior Windows fake `.NET HttpListener` Core. The runner fixture creates one immutable, Core-validated reference-bound v1.1 Plan and a Core approval, with synthetic fixture consent on throwaway SQLite; this **is not human approval** or a real operator public-key enrollment.

The Windows process is the existing `PicotooPet.MediaWorker.SmokeTests.exe`, with a **single-line, explicitly documented test-only exception** in existing `SmokeTests/Program.cs` selecting `--real-core-interop <phase>`, authorized by Issue #177's narrow test-entry exception. The new smoke requires `CI=true` and `P0_REAL_CORE_LOCALHOST_CI_ONLY=1`; there is no module initializer, and no shipping Worker, DPAPI/signature or Core implementation change. It generates a real ephemeral **Windows DPAPI Ed25519** identity with `ProtectedWorkerSigningKey`; only **its public key** is written to the temporary fixture and inserted into that SQLite. The existing `ControlCenterSession`, real `CoreWorkerChallengeClient`, `ProductionReferenceSnapshotStore`, `CoreReferenceApprovalSource`, `WorkerWitnessEncoding` and signed `WorkerWitnessV11` are exercised across real loopback HTTP. The 409 response **must come from Python Core** and have the exact `PRODUCTION_V11_WINDOWS_ATTESTATION_UNVERIFIED` code; a 2xx success fails the test.

Checks: real SQLite nonce digest (not plaintext), exact key/executor/job/Plan binding, 30-second expiry, unconsumed preflight challenge, Core current approval/plan reads, wrong bearer=401, key/executor/digest errors=409, no public enrollment=404, frozen-plan Claim=409, challenge expiry/reissue, approval revocation after issue, **no active lease, zero new Core attempts, zero Comfy POST**, and no production package. Any old Comfy/Windows journal that cannot be attested remains *UNVERIFIED*. The Windows local port 8188 sentinel and journal absence checks are limited evidence of this CI test only, not proof about a user machine.

## STOP conditions

- If the actual Python Core router cannot run unmodified on Windows: report the native error, **BLOCKED**, do not implement a fake handler or change production.
- If Python Core and Windows signed canonical payloads disagree: report actual Core error; do not alter signer or Core validation to make the test green.
- If a test requires bypassing local-console operator enrollment in production: use only test DB fixtures; do not add public registration or a hidden privileged HTTP route.
- If any endpoint authorizes I2V Claim, Lease, attempt or Comfy POST: test **FAIL**, no GPU activation.
- No installer, Maotai release, C011, model download, device access, tag or merge.

## Distinct meanings

| Evidence | Result when CI passes |
| --- | --- |
| Real localhost Python FastAPI challenge + Windows DPAPI Ed25519 witness transport | VERIFIED on runner only |
| Real Core SQLite challenge, approval, frozen Plan and 409 denial | VERIFIED on runner only |
| Real remotely attested same-EXE identity / Windows NTFS / Comfy GPU journal provenance | **UNVERIFIED** |
| Production v1.1 I2V GPU admission | **BLOCKED** |

No bearer/private DPAPI seed should appear in console logs, uploaded artifacts or test report.

### Test-only Program.cs exception (one line)

An initial isolated `ModuleInitializer` design blocked asynchronous `ControlCenterSession.InitializeAsync` while under the CLR module initializer lock (native Run 41125475082, 90-second `run` timeout, last marker `SESSION_INITIALIZE`). Rather than alter the existing session or simulate its HTTP responses, Issue #177's explicitly permitted narrow one-line test `Program.cs` dispatch selects the existing test assembly's `RealPythonCoreInteropTests.RunAsync` asynchronously. This is **not** a production Worker entrypoint, not a second scheduler, and cannot authorize GPU; ordinary smoke-test execution remains unchanged without the explicit flag.
