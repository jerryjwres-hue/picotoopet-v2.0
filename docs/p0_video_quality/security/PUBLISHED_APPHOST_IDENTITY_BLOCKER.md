# Issue 171: published Desktop process proof

Status: **BLOCKED / UNVERIFIED**. Frozen source:
`2d2fbd1b91bdcb25532e73410f3efc860d240af0`.
Branch: `test/p0q2-win-published-apphost-identity-20261030`.
Contract: <https://github.com/jerryjwres-hue/picotoopet-v2.0/issues/171>.

## Read-only investigation

The existing published application has no noninteractive entrypoint that invokes
`CoreWorkerChallengeClient.MeasureProcessImageAsync`, builds the canonical witness,
and returns the measured identity and signed field for comparison.

| Existing route | Behavior | Why it cannot supply this proof |
| --- | --- | --- |
| `Program.Main` → `MockProviderChild.TryRun` | Fixed Mock Broker child | Does not measure or sign the Worker witness. |
| `--p0-media-worker` | Calls `P0MediaWorkerHost.RunAsync` | Production Worker entrypoint; excluded from this CPU-only read-only investigation. |
| `--self-test` → `App.OnStartup` → `AppSelfTest.Run` | Existing noninteractive WPF self-test, before the normal session/Worker startup | Tests UI rendering, local logging and sandbox Mock Broker execution. It does not invoke process measurement or witness signing, and its JSON report contains neither identity nor signed witness. |
| Normal startup, including unknown flags | Creates the session/shell and calls `StartP0MediaWorker` | Launches a Worker; not a diagnostic substitute. |

The measurement and signing methods remain internal. Loading the Desktop DLL in
a test process and calling them through reflection would measure the test process.
An external observer could query a launched process path and hash a file, but could
not obtain that process's `Environment.ProcessPath`, pinned measurement lifetime,
or actual canonical signed witness through any existing read-only interface.
Debugger injection, startup hooks and an alternate entry assembly are not used.

`CoreWorkerChallengeClient.RunExpectedDenyAsync` is not a read-only identity
diagnostic: it uses a session and Core challenge transport, validates approvals and
snapshots, opens the protected key, and spends a durable nonce when signing. Its
presence does not authorize a new shipping invocation path.

## Publish and native verification boundary

The existing `windows/desktop/scripts/Build-Phase2WindowsRelease.ps1` owns the
Desktop `dotnet publish` flow (`Release`, `win-x64`), diagnostics, package validation
and lifecycle. Existing release workflows and Maotai checks are unchanged. This
task stops before invoking the builder or starting Desktop, because publishing or
hashing its bytes alone cannot resolve the missing runtime diagnostic interface.
No new artifact is represented as a formal package or installable release.

There is also a source-visible packaging compatibility concern: that builder uses
`PublishSingleFile=true` and `IncludeNativeLibrariesForSelfExtract=true`.
`CurrentImagePath` explicitly rejects an empty `Assembly.GetEntryAssembly().Location`
with `WORKER_EXE_HOST_UNVERIFIED`. Bundled managed assemblies normally have empty
`Location`; the current code deliberately treats unsupported single-file hosts as
unverified. This is a predicted rejection from the frozen source, **not an observed
published-process result**. Removing that guard, changing publish flags, extracting
a different DLL or testing an unbundled build would exceed this task's permission
and cannot establish the requested shipping proof.

The narrowly owned `P0 Published Desktop Identity Readiness` workflow uses the
existing hosted `windows-2025`, checkout and artifact actions. It records the exact
checkout SHA and SHA256 of the reviewed **source files**, not an executable hash.
It writes explicit null values for unobserved process paths, running EXE SHA256 and
signed witness field. It then deliberately fails the acceptance step with
`P0_PUBLISHED_DESKTOP_RUNNING_IMAGE=UNVERIFIED; ACCEPTANCE=BLOCKED`.
Its Run ID is native source-readiness evidence, **not a completed native Desktop
process-identity test**. An upload/checkout failure is an infrastructure failure,
not the expected acceptance blocker. No existing smoke-test registration or test
project is changed, and no uncallable test class is added.

## Evidence that must remain distinct

- #169/#170 Run `41095882426` proved the SmokeTests apphost hash/signature path. It
  does not prove a running published `Picotoo Pet AI.exe`.
- Direct managed rejection of a generic `dotnet.exe` host and CLR startup refusal
  of the renamed muxer are different evidence. The latter never reached managed
  measurement and is not comprehensive executable attestation.
- A published file's digest, a manifest, or a locally signed digest cannot alone
  establish remote trusted same-EXE identity or Comfy Journal attestation.

## Remaining blocker and required future authorization

Completing acceptance requires a separately approved, bounded, non-authorizing
shipping diagnostic path capable of observing the actual Desktop process's OS
identity, `Environment.ProcessPath`, pinned PE/file identity and SHA256, and the
exact canonical signed field, without production Worker startup, Core enrollment,
Claim/Lease or Comfy POST. Its key/nonce side effects and read-only constraints
must be resolved in that approval; no production code change is proposed here.
Current owner permission explicitly excludes shipping `Program.cs`, signer/DPAPI,
factory and Core authorization changes. Issue 171's stop condition applies.

The implementation/delivery plan is therefore limited to recording these source
findings, validating the new workflow syntax and owner-file scope, pushing the
independent branch, and collecting the native readiness Run ID. The final status
must retain BLOCKED/UNVERIFIED even if other smoke suites pass. Production I2V and
`I2V_CROSS_ENDPOINT_WORKER_PROOF_REQUIRED` remain unchanged and fail closed.
