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

15 groups in C010BIntegration.cs use real FinalVideoQaService.VerifyAsync(FinalVideoQaInputV1):

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

## Honest reporting

Actual Windows workflow **38021044347** completed SUCCESS on test commit e5969c10fe70991a525644bf443684082b36a678: 15/15 group PASS, 4/4 real media modes, corrupted-packet full decode rejected and timeout/cancel PASS. This evidence covers only the mapped group tests, not separately staged mutation cases. Existing 17 C009A manifest-mutation scenarios require a genuine master specimen and remain blocked. The Goal Center Open final-video action is owned by a later slice; no Open UI is tested here. C010B does not independently repeat every C005 profile real media case (upstream C010A Windows acceptance does).

See docs/testing/C010B_FINAL_VIDEO_QA_INTEGRATION_MATRIX_V1.md and ../PicotooPet.FinalVideoQa.IntegrationPreparation/coverage_scenarios.json.

No merge/rebase/tag/release.
