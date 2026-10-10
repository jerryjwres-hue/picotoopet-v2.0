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

## Original 78-case coverage status

| Status | Cases | Meaning |
| --- | ---: | --- |
| FIXTURE_ORACLE_READY | 20 | Standalone synthetic-media oracle, not product acceptance |
| INTEGRATION_TEST_ADDED_UNVERIFIED | 39 | Mapped to actual API test source; real Windows C010B execution must be confirmed |
| STAGING_READY_REAL_MASTER_BLOCKED | 17 | Real master specimen/catalog negative scenario execution still needed |
| BLOCKED_GOAL_CENTER_OPEN_API | 1 | Later Goal Center Open behavior not in C010A |
| BLOCKED_C010B_ALL_PROFILES_REAL_WINDOWS | 1 | Independent three-profile native C010B E2E not yet added |
| TOTAL | 78 | No invented PASS |

The former 35 BLOCKED_C010A_API entries are now 34 actual-API-backed test mappings plus one Goal Center Open blocker.

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

For the first 12 groups, controlled media facts test receipt/lineage/service policy; they do not certify synthetic fake bytes as playable media. The last three groups must run on native Windows with actual FFmpeg/ffprobe.

## Remaining blockers / run policy

1. Composed C010B Windows CI must execute successfully. Code written != PASS.
2. The 17 full C009A master manifest negative staging scenarios need genuine durable master specimen plus catalog verification test adapter.
3. Goal Center Open final-video action/receipt-gated catalog remains owned elsewhere, not C010A.
4. C010B does not independently repeat real 480x832 and 640x640 profiles; upstream C010A real Windows CI verifies them, but does not silently count as C010B independent coverage.

GitHub Actions composes by two separate checkouts and copies only C010B test source into a disposable C010A checkout. No merge/rebase/tag/release and no production edits.
