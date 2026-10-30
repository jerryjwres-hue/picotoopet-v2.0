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

## Native result

Pending actual Windows execution. Until a matching-SHA native run completes,
published process identity remains **UNVERIFIED**. Historical #171/#172 source-only
evidence and SmokeTests EXE results do not satisfy this test.
