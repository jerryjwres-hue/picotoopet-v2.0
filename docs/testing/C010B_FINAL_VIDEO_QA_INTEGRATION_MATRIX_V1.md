# C010B — Final Video QA Integration Test Preparation v1

Repository: jerryjwres-hue/picotoopet-v2.0
Branch: test/final-video-qa-integration-v1
Base: C009B ef71d84868e9fc4afd1e8b8f7203d72aa4e12415, including concrete C009A.
Design authority: G006_FINAL_VIDEO_QA_RECEIPT_V1 and C010A_IMPLEMENTATION_BRIEF_V1.

Scope: documentation and isolated tests/fixtures only. No C004, C007, C008, C009A, C009B, C010A, Goal Center/UI, ProductionPackage, Mac Core or publishing modifications. No merge/rebase/tag/release.

## Actual C009A/B contract findings

C009A concrete types are MasterCompositionInputV1, MasterCompositionResult, MasterVideoArtifact, MasterIdentityFacts, MasterArtifactExpectation, MasterInputIdentity, MasterPathPolicy, PostProductionMasterSourceVerifier, PostProductionMasterArtifactCatalog and internal MasterManifest.

C009 artifact identity is EXACTLY MasterInputDigest (not MasterCompositionDigest). The catalog FindVerifiedExactAsync(MasterArtifactExpectation) accepts only the exact managed root and two files:

    %LOCALAPPDATA%\PicotooPet\PostProduction\Master\v1\
      <first-40-sanitized-job>-<sha256(job)[0:16]>\
        <MasterInputDigest-64-lowercase-hex>\
          master.mp4
          master-manifest.json

Artifact fields: ProductionJobId, ProductionPackageId, ProductionPackageDigest, ProductionPlanDigest, MasterInputDigest, OutputProfileId, TargetRuntimeMs, FilePath, ManifestPath, Sha256, Bytes, HasAudio, VisualSourceKind, Reused.

Master profiles: postproduction.master.v1; video.h264.stream-copy.v1; audio.aac-lc.48k.mono.128k.v1. Visual kinds: c004_final_v1 or c008b_overlay_v1.

C009A MasterInputIdentity.Compute does NOT include NarrationManifestSha256 nor C008BManifestSha256 even though MasterManifest records both. C010A qa_input_digest must separately bind these values; include dedicated change-one-hash tests.

C009B landed FixedFfmpegMasterVideoComposer, MasterVideoMediaProbe, IMasterVideoProcessRunner and FixedMasterVideoProcessRunner. The existing media probe does not supply every C010A-required index/per-stream duration/chapters/full-decode datum. C009B's 250ms mux-level duration threshold is not final C010A policy.

C010A observation: the audited QA production branch had not yet landed callable QA service/receipt store/result signatures in this integration base. The C010A brief's proposed names are NOT a callable API. C010A invocation tests are BLOCKED; no fake API contracts or stubs in this preparation branch.

C009B real-Windows acceptance workflow at the audited head (run 38018291934) failed at its isolated unit + real Windows acceptance step; the same-head general Control Center CI succeeded. Final Windows C010B E2E remains UNVERIFIED.

## Machine-readable coverage: 78 cases

- FIXTURE_ORACLE_READY: 20.
- STAGING_AVAILABLE_API_BLOCKED: 17.
- BLOCKED_C010A_API: 35.
- BLOCKED_REAL_WINDOWS_AND_C010A: 6.

All 78 IDs, expected outcomes, fixture origins, dependencies and execution status appear in windows/desktop/tests/PicotooPet.FinalVideoQa.IntegrationPreparation/coverage_scenarios.json.

### Independent media fixture matrix (20 runnable interpretations)

| IDs | Condition | Fixture oracle expected |
| --- | --- | --- |
| FVQ-M-LANDSCAPE-VISUAL/NARRATED | 832x480 @24; zero audio vs AAC-LC 48k mono | PASS |
| FVQ-M-VERTICAL-VISUAL/NARRATED | 480x832 @24; zero audio vs AAC | PASS |
| FVQ-M-SQUARE-VISUAL/NARRATED | 640x640 @24; zero audio vs AAC | PASS |
| FVQ-N-MISSING-AUDIO | narration required but absent | AUDIO_STREAM_INVALID |
| FVQ-N-UNWANTED-AUDIO | narration not required but AAC present | AUDIO_STREAM_INVALID |
| FVQ-N-VIDEO-CODEC | MPEG-4 Part 2, not H.264 | VIDEO_STREAM_INVALID |
| FVQ-N-PIXEL-FORMAT | H.264 yuv444p | VIDEO_STREAM_INVALID |
| FVQ-N-GEOMETRY | 830x480 | OUTPUT_PROFILE_MISMATCH |
| FVQ-N-FPS | 25fps | OUTPUT_PROFILE_MISMATCH |
| FVQ-N-RUNTIME | 3s instead of 2s | RUNTIME_MISMATCH |
| FVQ-N-AUDIO-CHANNELS | AAC stereo | AUDIO_STREAM_INVALID |
| FVQ-N-AUDIO-RATE | AAC 44100 | AUDIO_STREAM_INVALID |
| FVQ-N-EXTRA-AUDIO | two AAC streams | UNEXPECTED_STREAM |
| FVQ-N-SUBTITLE | mov_text stream | UNEXPECTED_STREAM |
| FVQ-N-INVALID-CONTAINER | garbage named .mp4 | CONTAINER_INVALID |
| FVQ-N-TRUNCATED | truncated faststart MP4 | invalid probe OR decode failure |
| FVQ-N-SHA-TAMPER | changed content, same byte count | HASH_MISMATCH |

Synthetic fixture generator writes SHA/bytes and targets in fixture-index.json; independent verifier uses ffprobe plus FFmpeg decode-to-null. This is intentionally NOT product C010A QA: it does not validate full C005 frame plans, Production/Goal lineage or receipts. Locally executed in Linux with FFmpeg: 20 generated, 20 matched expected fixture-oracle outcomes. Windows status UNVERIFIED.

### Lineage and immutable-master negative staging (17 cases)

The staging utility takes a GENUINE C009A master.mp4/master-manifest.json, checks digest directory and exact files, then copies it into disposable isolated test roots. It changes: production_job_id, production_package_digest, production_plan_digest, creative_package_digest, c004_source_sha256, caption_overlay_plan_digest, narration_plan_digest, selected_visual_sha256, master_input_digest, output_sha256, output_bytes, has_audio, optional narration_manifest_sha256, optional c008b_manifest_sha256; it also stages an extra entry, missing manifest and media byte tamper.

Expected at real C009A catalog boundary: MASTER_ARTIFACT_CONFLICT; no overwrite, no C004 fallback. C010A result mapping remains blocked until actual callable API exists. Nullable manifest hashes not present in source are NOT_APPLICABLE_TO_SPECIMEN. Portable stager test uses only synthetic tiny bytes to test mutation mechanics; it does NOT assert they are real C009A artifacts.

## Candidate selection assertions (BLOCKED_C010A_API)

- Both narration_required and overlays_required false => exact verified C004 fallback only.
- Narration true / overlay false => exact current C009 master required.
- Narration false / overlay true => exact current C009 master required.
- Both true => exact current C009 master required.
- Required master missing => FINAL_QA_MASTER_REQUIRED and NEVER C004 fallback.
- Stale master when no post-production => rejected; never choose newest timestamp.
- Reject mismatched Goal/Creative/Production plan/package identities, C007/C008 plan digests and C009 MasterInputDigest.

## PASS-only immutable receipt/restart/digest conflict assertions (BLOCKED_C010A_API)

1. On PASS, exactly one receipt final-artifact-receipt.json under DeliveryReceipts/v1/<job-key>/<qa_input_digest>/; no duplicate MP4. Failure never produces a PASS receipt.
2. Same SHA/lineage/policy after restart => same qa_input_digest and receipt_digest, Reused=true, no repeated ffprobe/full decode, but still rehash candidate and upstream manifest files.
3. Changed ProductionPlan digest, C004 manifest SHA, C007B manifest SHA, C008B manifest SHA, C009 manifest SHA, final MP4 SHA or QA profile => old receipt never selected; new qa_input_digest or rejection as appropriate.
4. verified_at must be excluded from receipt_digest, while actual observed media facts must be included.
5. Tamper receipt JSON, change receipt_digest, inject unknown field, extra file, partial final dir, path reparse/symlink: bounded FINAL_QA_RECEIPT_CONFLICT and no overwrite.
6. Tamper candidate after PASS, preserving byte count: catalog/open must deny; QA Ready projection invalidated. Open wiring belongs to later Goal Center owner, not this branch.
7. No caller-supplied arbitrary ffprobe/ffmpeg args, paths or filter. No raw narration text, overlay text, absolute paths, FFmpeg stderr or raw ffprobe JSON persisted.

## Full decode / video / audio / timing edge assertions (BLOCKED_C010A_API)

C010A must independently probe MP4-family container, H.264, yuv420p, exactly stream 0 video, 24/1 rational FPS, exact profile dimensions, and exactly one AAC-LC/48000/mono audio stream iff narration_required. Other audio/subtitle/data/attachment/unknown streams, chapters, attached pictures must fail. Probe header alone is insufficient; require fixed ffmpeg.exe -nostdin -xerror -i <verified candidate> -map 0:v:0 [-map 0:a:0] -f null - with no persistent output. Cover header-readable corrupted packets, bounded timeout/cancel/kill, no stderr disclosure.

Closed C005 profiles:
- video.landscape.v1: 832x480 @24
- video.vertical.v1: 480x832 @24
- video.square.v1: 640x640 @24

Frame-aware policy: expected_visual_us=sum(FrameCount)*1000000/24; target_us=TargetRuntimeMs*1000; delta_us=abs(expected_visual_us-target_us). Video stream difference vs frame plan <=one frame; format difference vs target <=delta_us+100000; narrated audio difference vs target <=100000. Use integer/rational arithmetic and test one-frame and 100ms boundaries. Never substitute C009B's looser mux threshold, nor silently trim/repair media.

## Real Windows E2E (UNVERIFIED; 6 blocked scenarios)

After C010A API and C009B Windows acceptance are ready, verify actual C004 fallback and C009 narration-only, overlay-only and overlay+narration master. Cover C005 24fps profiles, stream-copy lineage, AAC profile/samplerate/channels, no unexpected streams, full decode, frame-aware runtime, PASS receipt, restart reuse and post-PASS tamper denial. S005 proved stream-copy AAC with a 25fps synthetic visual, not sufficient to replace 24fps C009B integration.

## Execution status / ownership / blockers

Portable preparation unit tests: 5/5 PASS.
Synthetic media fixture oracle: 20/20 PASS on local non-Windows FFmpeg.
C010A_PRODUCT_QA: BLOCKED (callable QA/receipt contract not landed in base).
REAL_WINDOWS_C010B: UNVERIFIED; latest C009B Windows acceptance failure must be resolved.
REAL_MASTER_MUTATIONS: STAGING TOOL READY, real source specimen NOT VERIFIED.

Only docs/testing and independent tests/PicotooPet.FinalVideoQa.IntegrationPreparation are owned. Do not commit generated MP4 files or modify production. No merge/rebase/tag/release.
