# C010B — Independent Actual-C010A API Integration Tests

This project tests the **real C010A service and receipt store**, not a recreated QA API.

## Composition without merging

C010B: test/final-video-qa-integration-v1.
Pinned C010A PR #71: b418777f1e3f72e1eb394a26a1e6202e62e718cc (includes f82a184d).
C009A/B are part of that audited C010A checkout.

The C010B GitHub Actions job checks out each branch separately and copies **only this test project** into a disposable C010A source checkout. The .csproj directly references the actual PicotooPet.Desktop production project and compile-links, without copying, C010A's existing Fixture.cs and LifecycleTests.cs. The AssemblyName matches the already-authorized C010A test friend assembly to access its internal constructor. No production file changes or new QA API.

## How to run

The test branch itself intentionally has no C010A production code; the isolated C010B test project must be executed in a temporary C010A checkout after test-only file composition:

    dotnet run --project windows/desktop/tests/PicotooPet.FinalVideoQa.IntegrationTests -c Release -- --real

Requires Windows, pinned .NET 10, FFmpeg/ffprobe, H.264 native libraries and fonts for C008B.

## Actual assertions

17 groups in C010BIntegration.cs use real FinalVideoQaService.VerifyAsync(FinalVideoQaInputV1):

- four candidate selection modes and PASS-only receipt
- missing C009 master never falls back to C004, wrong digest/wrong candidate rejected
- nine Goal/Creative/Production/package/profile lineage failures
- restart with a runner which throws if ffprobe/decode is repeated
- receipt tamper: digest/outcome/unknown and duplicate fields, malformed JSON, invalid checks
- extra entry/partial final receipt directory conflict, no overwrite
- changes to valid Goal and fully recomputed C005/C007/C008 plan lineage generate new immutable QA digest
- narration/overlay upstream manifest edits independently change QA digest without changing C009 MasterInputDigest
- full decoder/probe failures: no durable PASS receipt
- post-PASS same-size artifact mutation must fail verification
- exact C010A H.264, yuv420p, 24fps, AAC-LC 48k mono, unexpected stream/chapters, frame-aware timing policies
- native Windows four C004/C009 modes and receipt restart
- header-readable real MP4 with altered P-frame packets: update isolated source hash/manifest first so validation reaches real ffmpeg full decoder and fails with FINAL_QA_DECODE_FAILED
- native real FFmpeg timeout and cancellation

A controlled runner proves **service/receipt contract behavior**, not actual MP4 decoding. Only native Windows real-media groups prove decode/stream acceptance.

## Issue #76: completed real master tamper and independent 3-profile media verification

C010BRealMasterManifestNegatives.cs constructs an actual real C009B master (narration and overlays both enabled) using the existing C010A fixture/producer. It derives the EXACT MasterArtifactExpectation from real lineage facts. All 17 original master-manifest mutations trigger both C009A PostProductionMasterArtifactCatalog.FindVerifiedExactAsync => MASTER_ARTIFACT_CONFLICT and C010A FinalVideoQaService.VerifyAsync => FINAL_QA_ARTIFACT_INVALID. An existing immutable PASS receipt stays unchanged during each tamper; the master is then restored byte-for-byte and the original receipt must reuse successfully. No fake JSON oracle.

C010BThreeProfileWindowsMedia.cs independently executes 3 C005 24fps profiles x 4 audio/overlay modes = 12 actual Windows FFmpeg/ffprobe/full-decode/receipt cases with exact video dimensions, H.264/yuv420p, AAC-LC/48k/mono iff narrated, and restart reuse without executing a process.

**Run 38645293453 SUCCESS**:
- 17/17 C010B integration groups PASS (previous 15 preserved, 2 new).
- 17/17 individually emitted C010B_MASTER_MANIFEST_NEGATIVE_PASS markers.
- 12/12 C010B_THREE_PROFILE_REAL_PASS native media markers.
- No production changes; only current test project and dedicated workflow.

The original 78-case matrix now counts 57 original scenarios mapped to native C010B PASS, 20 separate synthetic-media fixture oracle cases, and 1 blocked Goal Center Open receipt-gate integration. 57 is mapped case coverage, NOT 57 individually executed C# methods.

The only remaining BLOCKED scenario is FVQ-R-open-reverify-exact-candidate; Goal Center Open belongs to another production owner.

See docs/testing/C010B_FINAL_VIDEO_QA_INTEGRATION_MATRIX_V1.md and ../PicotooPet.FinalVideoQa.IntegrationPreparation/coverage_scenarios.json.

No merge/rebase/tag/release.
