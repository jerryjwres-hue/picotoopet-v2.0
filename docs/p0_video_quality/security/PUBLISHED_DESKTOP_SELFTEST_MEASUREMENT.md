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

## Discovered build blocker

The Linux cross-publish diagnostic using the workflow's exact publish properties
failed with IL3000 at the two existing `entry.Location` uses in frozen
`CoreWorkerChallengeClient.CurrentImagePath`. The repository treats warnings as
errors. This is compiler evidence, not a published Windows runtime rejection.
The native workflow must confirm its own result and uploads `publish-result.json`
even when the publish step fails; it cannot proceed to launch a nonexistent EXE.

No suppression of those frozen Core errors, `WarningsNotAsErrors`, analyzer
disable, guard removal or alternate unbundled publish is added to obtain a green
result. The new diagnostic locally acknowledges IL3000 only at its own intentional
observation of `entry.Location`; it cannot suppress errors in another file. That Core source
is outside the owner's permission. If the native compiler reports the same
failure, the published process path, running SHA256, entry `Location` and frozen
runtime measurement remain **BLOCKED / UNVERIFIED**, with the new runtime test
implementation itself not accepted as proven. Resolving the original IL3000
diagnostics requires a separate, explicitly scoped decision.
