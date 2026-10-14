# C010B — Real C010A API Integration Matrix v2

Repository: jerryjwres-hue/picotoopet-v2.0
Test branch: test/final-video-qa-integration-v1
C010A PR #71 current audited implementation: b418777f1e3f72e1eb394a26a1e6202e62e718cc (core f82a184d).
C009B native Windows PASS: d399f720e8347488a43282722ad37c43cd3cb337 / workflow 38019671051.

## Actual API used

- FinalVideoQaInputV1: GoalContinuation / ProductionJob / ProductionPlan / ProductionPackage / MasterInput / MasterArtifact
- FinalVideoQaService.VerifyAsync(input, CancellationToken)
- FinalVideoQaResult (Receipt / ReceiptPath / Reused)
- FinalArtifactReceiptV1, FinalQaIdentity.ReceiptDigest
- FinalVideoQaException.Code
- FinalVideoQaMediaProbe.Parse and Validate
- C009A PostProductionMasterCompositorService.ComposeAsync and MasterVideoArtifact
- Existing C010A test Fixture.cs and LifecycleTests.cs, compile-linked rather than copied

The actual internal dependency-injection constructor is used through C010A's existing test-friend AssemblyName; no new QA implementation/API has been created. C009 MasterInputDigest does not independently bind NarrationManifestSha256 and C008BManifestSha256, so C010A QA digest must include source manifest hashes separately.

## Original 78-case coverage status — final native Windows evidence

| Status | Cases | Meaning |
| --- | ---: | --- |
| FIXTURE_ORACLE_READY | 20 | Standalone synthetic-media oracle, not product acceptance |
| COVERED_BY_PASS_NATIVE_WINDOWS_SUITE | 57 | 39 prior mappings plus 17 actual C009A master negatives and 1 independent 3-profile scenario; native Windows run 38645293453 PASS |
| BLOCKED_GOAL_CENTER_OPEN_API | 1 | Later Goal Center Open behavior not in C010A |
| TOTAL | 78 | No invented PASS |

All 17 original real-master negative cases are independently executed against actual C009A catalog and C010A VerifyAsync, and the missing three-profile independent native scenario is now executed as 12 separate profile/mode combinations. The only remaining original blocker is Goal Center Open. The 57 mappings are coverage counts, not 57 separate C# test methods.

## Independent integration test groups

| Group | Cases / expected behavior |
| --- | --- |
| candidate-selection-pass-only-4-modes | C004 fallback + three required C009 modes, one PASS-only receipt per verified candidate |
| no-fallback-wrong-candidate | missing C009, wrong MasterInputDigest/path, stale C009 with no postprocessing all rejected |
| wrong-goal-production-and-plan-lineage | nine Goal/Creative/Production/Package/status/profile mismatches |
| receipt-restart-no-decode | immutable digest reuse on restart; NeverRunner proves no process re-execution |
| receipt-tamper-conflict | malformed/duplicate/unknown receipt fields, changed outcome/hash/check IDs all reject |
| receipt-directory-conflict | extra entry/partial final receipt directory reject, no overwrite |
| qa-digest-new-provenance | new Goal return SHA and legitimate, consistently recomputed C005 frame-plan/C007/C008 digests yield new receipt |
| qa-manifest-digest-independent-of-master | changed C007B/C008B manifest SHA, updated C009 manifest hash, same MasterInputDigest but new qa_input_digest |
| failed-decode-no-pass-receipt | actual C010A VerifyAsync + controlled failure on ffmpeg stage, no PASS |
| failed-probe-no-pass-receipt | actual C010A VerifyAsync + controlled failure on ffprobe stage, no PASS |
| artifact-tamper-after-pass | same-byte-count mutation, exact lineage recheck rejects |
| media-policy-negative-facts | actual FinalVideoQaMediaProbe Parse/Validate rejects non-H264/pix/fps, data/chapters/attached pic, wrong AAC/rate/channels/runtime |
| windows-real-four-delivery-shapes | real FFmpeg/ffprobe on C004 fallback, narration-only, overlay-only, narration+overlay; receipt restart |
| windows-header-readable-corrupted-packets-rejected | real C004 path/hash/manifest updated for deliberately corrupted packet specimen, then actual C010A full decode rejects, no receipt |
| windows-process-timeout-and-cancel | real bounded FFmpeg runner timeout/cancel termination |

For the first 12 groups, controlled media facts test receipt/lineage/service policy; they do not certify synthetic fake bytes as playable media. The last five groups run on native Windows: three preexisting real scenarios plus two new Issue #76 scenarios.

## Issue #76 actual execution (native Windows)

- Commit under test: 8bcbd52d59f8c66410520981cbcbc2ac060fcfaa
- Run: [38645293453](https://github.com/jerryjwres-hue/picotoopet-v2.0/actions/runs/38645293453) — SUCCESS.
- C010B_INTEGRATION_SUMMARY=passed=17;failed=0;real=True (previous 15 plus 2 new groups)
- C010B_REAL_MASTER_MANIFEST_SUMMARY=passed=17;failed=0;source=C009B_REAL
- C010B_THREE_PROFILE_REAL_SUMMARY=passed=12;failed=0

The 17 negative IDs are: production-job-mismatch, production-package-mismatch, production-plan-mismatch, creative-package-mismatch, source-c004-mismatch, caption-plan-mismatch, narration-plan-mismatch, selected-visual-mismatch, master-input-digest-mismatch, master-output-sha-mismatch, master-output-bytes-mismatch, master-audio-flag-mismatch, narration-manifest-mismatch, overlay-manifest-mismatch, unexpected-directory-entry, missing-master-manifest, and master-media-byte-tamper.

Every one has an actual C009B durable master source, exact master identity/catalog expectation, C009A catalog rejection, C010A VerifyAsync rejection, unchanged PASS receipt during tamper, and successful post-restore exact reuse.

The 12 native video cases are 832x480 landscape, 480x832 vertical, and 640x640 square, each times: no narration/no overlay, narration only, overlay only, and both. All have real ffprobe and full decode, exact stream contracts and durable receipt/restart.

**Only remaining original BLOCKED:** FVQ-R-open-reverify-exact-candidate — Goal Center Open action and its click-time receipt gate are owned by C009C/C010B delivery wiring, not this G006 QA test-only slice. No production/UI file was touched.

The old Python fixture oracle still provides 20 synthetic media fixtures independently from the native C010A suite. Do not describe that as 20 additional C010A service calls.

This test branch never merges/rebases another branch. GitHub Actions composes C010B-owned tests in a disposable pinned-C010A checkout and leaves original branches intact. No merge/rebase/tag/release.
