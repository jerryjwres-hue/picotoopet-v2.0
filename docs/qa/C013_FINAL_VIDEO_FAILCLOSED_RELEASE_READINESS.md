# C013 Final Video Release Candidate — Native Windows Integration

This document is **source composition and CI acceptance**, not a public release authorization.

## Frozen composition

- C011 base: `ec468b9975a3b1cd706e6e74223bfb05f7733a86`.
- Frozen C009B Claude PR #85 fail-closed Job Object uplift: `100d3788776204770d7aaff11c5c28e53ef93c41`.
- Selected C009B production blobs **exactly**:
  - `FixedFfmpegMasterVideoComposer.cs`: `56d9233afc299125b85bb3b541ee9e72fc7a1716`
  - `MasterVideoMediaProbe.cs`: `c5403c0e68c02214882c9e01d6361165f7584621`
  - `MasterVideoProcessRunner.cs`: `3d3229245e8771c87b55f0e204d12a0952ac825d`.
- C009B frozen matching owned test files: `GlobalUsings.cs`, `HardeningTests.cs`, `ProcessLineage.cs`, `Program.cs`, `RealHardening.cs`, `RealWindowsAcceptance.cs`, `UnitTests.cs`, and the test `.csproj`, selected by exact source blob SHA from #74.
- C010A/C011 QA receipt, Goal Center, delivery coordinator production source stays on C011 base Git blobs, asserted at runtime with Git object identity. No Issue #83 development, Maotai assets, other test/producer branch code is absorbed.
- C010B owner test SHA `8c8f1d7c01dc82baf2df636ef93df5af7125cd3c`; G005 owner test SHA `0c92fbb5152c149e30db0e88a09b4e7eade18e02`. Both checked out separately and overlay **test directories only** into ephemeral C013 candidate checkout, compiled directly against C013 production project, not prior binaries.

## Actual Windows acceptance

Independent workflow `.github/workflows/c013-final-video-release-candidate-windows.yml` runs native Windows 2025, .NET pinned to `windows/desktop/global.json`, real FFmpeg and ffprobe. It runs:
1. Native C009B Job Object + master mux 3 output profiles, real Windows mux/hardening tests.
2. C010A production `FinalVideoQaService` real Windows 3 profiles × 4 narration/overlay modes; independently require 12 real markers, provenance and full decode.
3. C010B 17 independent integration groups, 17 C009A master-negative cases, 12 native profile/mode combinations. Each marker count verified rather than passing through a single aggregate.
4. C011 production QA-gated delivery and Open click-time tests, all independent named markers.
5. G005 36-scenario test on actual C013 production: require 33 individual PASS with assertions, including native FV-012/031/035, with 0 FAIL / 0 BLOCKED and 3 UNVERIFIED. Controlled authority does **not** establish live Mac Core network.

All logs and run/owner/head evidence emitted to the workflow artifact `c013-native-release-readiness-evidence`. Generated `c013-candidate-tests.json`, `c013-release-gate.json`, `c013-release-readiness.json` contain candidate SHA, frozen source SHA, actual GitHub Actions run ID, component PASS/FAIL statuses and artifact log SHA-256 identities.

## Release boundary

Original official `Build-Phase2WindowsRelease.ps1 -ValidationScope Full` executes against **C013 candidate**. Issue #78 Maotai `torso_neutral.png` genuine asset is absent; never provide placeholder or skip full smoke. When actual build logs confirm `PHASE2_CORE_SMOKE=FAIL` + missing file, classify the official release gate BLOCKED and prove no ZIP was created; unexpected build failure is FAIL, not an expected blocker.

C013 C009B hardening remains exactly frozen at PR #74. Claude PR #85 is **not** composed or approved; a separate reviewer-authorized, auditable source blob upgrade with full rerun will be needed before claiming its process safety improvements. Keep the original Full Release Builder real `torso_neutral.png` failure, never substitute an asset or skip the gate.

Further required before release:
- `FV-012/031/035`: G005 frozen native Windows real-process crash/recovery, AAC corruption and isolated missing-tools tests must execute **on this C013 candidate production assembly**, with independent case markers and 16/9/11 native assertions respectively. These scenarios are PASS only when the C013-specific run validates the emitted per-case evidence. FV-012 kills a pre-commit staged child, not during `Directory.Move`; FV-031 proves SHA-bound denial of corrupt audio, not semantic audio-policy rejection of a reauthorized file.
- `FV-032/033/034`: real published GUI concurrent Open, clean profile packaged install, independent process PID forced kill/restart (UNVERIFIED until actual published artifact and UI).
- Live Mac Core network session, reconnect/auth authority (UNVERIFIED).
- Maotai `torso_neutral.png` official full release gate (BLOCKED).
- Public signature, formal publish and release authorization absent.

**A green C013 integration workflow does not mean RELEASE READY.** No merge/rebase/force-push/tag/release. Draft PR only, target C011 staging.

## C013 frozen provenance and security-specific acceptance

- C013 starts **exactly** from C012 release candidate `b1977ffc36d9151e1b8ff17d369583d0ed0e0334`. C012 PR #86 and Claude PR #85 branches remain untouched.
- Previous C009B PR #74 freeze: `1e75cab7daf201a1883e3e98ea5ddb8a753e8e82`; promoted owner source: Claude PR #85 `100d3788776204770d7aaff11c5c28e53ef93c41`.
- Three selected **production** Git blobs are `FixedFfmpegMasterVideoComposer.cs=56d9233afc299125b85bb3b541ee9e72fc7a1716`, `MasterVideoMediaProbe.cs=c5403c0e68c02214882c9e01d6361165f7584621`, `MasterVideoProcessRunner.cs=3d3229245e8771c87b55f0e204d12a0952ac825d`; original C011/C010A/Goal Center production remains frozen by the unchanged C013 acceptance script's `git rev-parse` checks.
- Matching C009B owned test files are selectively copied verbatim from #85, including `RealFailClosed.cs`. The full #85 branch history is not merged.
- **CreateProcessW review:** `MasterVideoProcessRunner.cs:584-596` passes `lpApplicationName = null` and a NUL-terminated command line built from fixed `ffmpeg.exe` / `ffprobe.exe` names (allowlist at lines 116-122). Windows resolves the executable through its native executable search order: PATH/search-directory trust remains an explicit security boundary; this implementation does not prove absolute executable provenance. `WorkingDirectory` is supplied as `lpCurrentDirectory`; environment is inherited (`lpEnvironment = null`), not copied from arbitrary `ProcessStartInfo.Environment`. Do **not** call this a proven hijack without a controlled Windows exploit test.
- **Handle inheritance:** `MasterVideoProcessRunner.cs:543-585` configures `PROC_THREAD_ATTRIBUTE_JOB_LIST` and `PROC_THREAD_ATTRIBUTE_HANDLE_LIST` to include exactly the three pipe handles; `bInheritHandles=true` is required by HANDLE_LIST. Explicit Win32 pipe handle closing and SafeHandle ownership are at lines 336-381, 445-452. Real executable argv quoting and special characters must pass `MASTER_MUX_FAILCLOSED_ARGV_ROUNDTRIP=PASS`.
- **Containment & cleanup:** `MasterVideoProcessRunner.cs:124-172` requires job enrollment verification; termination and root+job cleanup are implemented at lines 175-221; Job-close / stream disposal ordering is at lines 445-452. Native `JOB_CREATE`, `ENROLL`, `VERIFY`, `SUPPRESS_TERMINATION` tests must each PASS on C013 candidate. Suppressed termination must report `CleanupIncomplete=true`, never falsely claim a clean termination. Exact descendant-zero validation (with Windows console-host timing limits) is evidenced by the real hardening/failclosed native tests; PID observation alone is insufficient.
- A green C013 native integration workflow only approves the **controlled-Core release candidate**, not a published installation, executable search provenance guarantee, or live Mac Core transport lifecycle.
- Formal Full Release Builder stays mandatory: an actual `torso_neutral.png` missing asset failure is **BLOCKED**, with `zip_count=0` and `release_ready=false`, never converted into an artificial PASS.

**C013 is not permission to modify Maotai, PR #85, PR #86, release tags or signed published assets.**
