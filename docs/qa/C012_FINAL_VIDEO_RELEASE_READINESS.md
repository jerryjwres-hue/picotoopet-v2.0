# C012 Final Video Release Candidate — Native Windows Integration

This document is **source composition and CI acceptance**, not a public release authorization.

## Frozen composition

- C011 base: `ec468b9975a3b1cd706e6e74223bfb05f7733a86`.
- Frozen C009B PR #74 Job Object + hardening: `1e75cab7daf201a1883e3e98ea5ddb8a753e8e82`.
- Selected C009B production blobs **exactly**:
  - `FixedFfmpegMasterVideoComposer.cs`: `53609c0c78dd6e8c1189a865b04b1aaaec1c39df`
  - `MasterVideoMediaProbe.cs`: `8b998f9de7820f8bdebaad011b471164eeb59359`
  - `MasterVideoProcessRunner.cs`: `e82e72f086a84867c0c38ebe4e6e5ff689385dfa`.
- C009B frozen matching owned test files: `GlobalUsings.cs`, `HardeningTests.cs`, `ProcessLineage.cs`, `Program.cs`, `RealHardening.cs`, `RealWindowsAcceptance.cs`, `UnitTests.cs`, and the test `.csproj`, selected by exact source blob SHA from #74.
- C010A/C011 QA receipt, Goal Center, delivery coordinator production source stays on C011 base Git blobs, asserted at runtime with Git object identity. No Issue #83 development, Maotai assets, other test/producer branch code is absorbed.
- C010B owner test SHA `8c8f1d7c01dc82baf2df636ef93df5af7125cd3c`; G005 owner test SHA `99cccbb867c3c4d532e816907f2350a0c6d043e0`. Both checked out separately and overlay **test directories only** into ephemeral C012 candidate checkout, compiled directly against C012 production project, not prior binaries.

## Actual Windows acceptance

Independent workflow `.github/workflows/c012-final-video-release-candidate-windows.yml` runs native Windows 2025, .NET pinned to `windows/desktop/global.json`, real FFmpeg and ffprobe. It runs:
1. Native C009B Job Object + master mux 3 output profiles, real Windows mux/hardening tests.
2. C010A production `FinalVideoQaService` real Windows 3 profiles × 4 narration/overlay modes; independently require 12 real markers, provenance and full decode.
3. C010B 17 independent integration groups, 17 C009A master-negative cases, 12 native profile/mode combinations. Each marker count verified rather than passing through a single aggregate.
4. C011 production QA-gated delivery and Open click-time tests, all independent named markers.
5. G005 36-scenario test on actual C012 production: require 30 individual PASS with assertions and retain 3 BLOCKED and 3 UNVERIFIED. Controlled authority does **not** establish live Mac Core network.

All logs and run/owner/head evidence emitted to the workflow artifact `c012-native-release-readiness-evidence`. Generated `c012-candidate-tests.json`, `c012-release-gate.json`, `c012-release-readiness.json` contain candidate SHA, frozen source SHA, actual GitHub Actions run ID, component PASS/FAIL statuses and artifact log SHA-256 identities.

## Release boundary

Original official `Build-Phase2WindowsRelease.ps1 -ValidationScope Full` executes against **C012 candidate**. Issue #78 Maotai `torso_neutral.png` genuine asset is absent; never provide placeholder or skip full smoke. When actual build logs confirm `PHASE2_CORE_SMOKE=FAIL` + missing file, classify the official release gate BLOCKED and prove no ZIP was created; unexpected build failure is FAIL, not an expected blocker.

Further required before release:
- `FV-012/031/035`: adversarial real process atomic crash, AAC timeline corruption, native missing-FFmpeg validation (BLOCKED pending independently reproduced scenarios).
- `FV-032/033/034`: real published GUI concurrent Open, clean profile packaged install, independent process PID forced kill/restart (UNVERIFIED until actual published artifact and UI).
- Live Mac Core network session, reconnect/auth authority (UNVERIFIED).
- Maotai `torso_neutral.png` official full release gate (BLOCKED).
- Public signature, formal publish and release authorization absent.

**A green C012 integration workflow does not mean RELEASE READY.** No merge/rebase/force-push/tag/release. Draft PR only, target C011 staging.
