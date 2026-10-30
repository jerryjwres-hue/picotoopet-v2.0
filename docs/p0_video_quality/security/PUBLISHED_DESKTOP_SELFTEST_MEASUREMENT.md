# Issue 173: read-only published Desktop measurement

Contract: <https://github.com/jerryjwres-hue/picotoopet-v2.0/issues/173>.
Frozen source: `2d2fbd1b91bdcb25532e73410f3efc860d240af0`.

## Bounded implementation and verification plan

1. Add a focused test file for exact two-flag selection, invalid/missing/managed/
   reparse file refusal, actual published process measurement, unchanged legacy
   self-test behavior and unknown lookalike argument rejection. Observe the new
   selection contract fail before implementing it.
2. Only in `AppSelfTest.cs`, opt in when both `--self-test` and
   `--self-test-exe-identity` are present. Return directly from a read-only branch
   before normal self-test fixtures, Mock Broker, session or Worker creation.
   Query the OS and environment process paths, pin the namespace and PE file,
   hash the actual running EXE with bounded cancellation, recheck path/file
   identity, and report entry assembly name and actual `Location` state.
3. Separately invoke the existing frozen **measurement only** method. Record
   acceptance or its explicit refusal without changing its guards. Never invoke
   protected keys, signing, nonce reservation, Core transport or Comfy.
4. A focused hosted Windows workflow directly publishes the exact Desktop project
   with Release/win-x64, self-contained single-file and native-library extraction.
   A disposable test harness runs that EXE with a timeout, compares independent
   OS process path and EXE/build-DLL hashes, and saves scoped JSON evidence.
   It also runs legacy self-tests. This is a technical measurement, not an
   official package, formal Release pass or permission to install.

Only the owned AppSelfTest source, new focused test file, workflow and this
security document may change. No new production entrypoint, public API, executor,
signer or authorization path is added. The original release builder and Maotai
asset requirements remain unchanged.

## Interpreting evidence

`exe_identity.status=PASS` will mean the actual published Desktop process's
read-only identity evidence was complete. It cannot mean witness signing,
remote trusted Worker identity, a Claim/Lease, or GPU admission succeeded.
`frozen_worker_measurement=REJECTED` with `WORKER_EXE_HOST_UNVERIFIED` is a valid
discovered compatibility result; the frozen method explicitly rejects an empty
entry assembly `Location`. No fallback DLL digest is used as the EXE digest.

A bundled managed assembly has no independently addressable file when its
`Location` is blank. Its in-process managed-file digest must remain null with an
explicit reason. The native test can separately compare the build's managed DLL
digest with the actual published EXE digest; that comparison does not assert that
the DLL was a separately loaded runtime file.

Missing identity, invalid PE, unstable paths/files, cancellation, unexpected
frozen-measurement errors, child-process observations or a failed published
self-test must fail acceptance. Diagnostic errors use fixed codes rather than
raw exception/stdout bodies. A timeout terminates only the test-created process
tree. Peer-process polling provides bounded observation, not comprehensive remote
process attestation. No GPU absence claim is derived merely from that polling.

## Native evidence

The focused workflow's per-run JSON artifacts and matching checkout SHA are the
authority for each native result. Until a matching-SHA native run completes,
published process identity remains **UNVERIFIED**. Historical #171/#172 source-only
evidence and SmokeTests EXE results do not satisfy this test. The source-only
compiled-metadata preflight observed the missing opt-in method before this change;
it is DIAGNOSTIC and does not replace Windows behavioral tests.

## Standard publish failure and bounded diagnostic configuration

The initial Linux cross-publish using the standard single-file publish properties
failed with IL3000 at the two existing `entry.Location` uses in frozen
`CoreWorkerChallengeClient.CurrentImagePath`. The repository treats warnings as
errors. Windows Run `41112584802` on
`caca915f40d641ffa34b179648c58f005b2eb7a6` confirmed the compiler failure at lines
179/181 and never launched the published process. That standard publish remains
**FAIL**; this is compiler evidence, not a runtime rejection.

The focused workflow now supplies `-p:WarningsNotAsErrors=IL3000` **only to the
disposable diagnostic publish**. IL3000 remains visible in its compiler output;
other warnings remain errors. The warning describes the exact blank-Location
behavior Issue 173 asks to observe, and the frozen code already explicitly rejects
it. This bounded technical build configuration allows observation without removing
that guard or touching its source. It is not an official Release configuration or
a repair of standard-publish compatibility. The diagnostic report explicitly
records the exception and the failed standard run. The new diagnostic locally
acknowledges IL3000 at its own intentional `Location` observation as well.

No `NoWarn`, analyzer disable, alternate unbundled publish, production guard change
or additional warning exception is applied. The workflow uploads
`publish-result.json` even on failure and stops if this diagnostic publish fails;
it cannot launch a nonexistent EXE or substitute an older build. Formal Release,
Maotai requirements, trusted Worker identity and I2V authorization remain separate
and unchanged. A diagnostic measurement PASS cannot imply any of those passed.
