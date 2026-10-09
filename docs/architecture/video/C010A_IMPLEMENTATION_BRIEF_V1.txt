# C010A — Deterministic Final Video QA + Immutable Delivery Receipt v1
## Implementation Brief

This is an implementation brief for C010A. It converts G006 into concrete work against the actual
C009A contracts already present on this branch.

C010A is Windows-local, read-only with respect to every upstream artifact, and PASS-only with respect
to durable receipt creation.

It must not modify C004, C007, C008, C009A, C009B, Production, Goal Center, UI or publishing.

---

## 1. Audited concrete state

### C009A concrete contracts are already frozen

The C009A implementation on this branch defines these exact types:

- `MasterCompositionInputV1`
- `MasterCompositionResult`
- `MasterVideoArtifact`
- `MasterIdentityFacts`
- `MasterArtifactExpectation`
- `PostProductionMasterArtifactCatalog`
- `PostProductionMasterSourceVerifier`
- internal `MasterManifest`
- internal `MasterManifestNarrationSegment`
- internal `MasterInputIdentity`
- internal `MasterPathPolicy`

The exact profile constants are:

- schema: `1.0`
- master profile: `postproduction.master.v1`
- video profile: `video.h264.stream-copy.v1`
- audio profile: `audio.aac-lc.48k.mono.128k.v1`
- C004 visual kind: `c004_final_v1`
- C008B visual kind: `c008b_overlay_v1`

The C009A durable artifact identity is named **`MasterInputDigest`**.

C010A must use that exact name. Do not introduce a competing
`master_composition_digest` name for the same C009 identity.

### Exact C009A managed root

Production creation resolves:

`%LOCALAPPDATA%\PicotooPet\PostProduction\Master\v1`

The exact C009A durable layout is:

```text
Master\v1\
  <safe-job-prefix>-<sha256(production_job_id)[0:16]>\
    <MasterInputDigest>\
      master.mp4
      master-manifest.json
```

`MasterPathPolicy.JobDirectory()` uses:

- at most the first 40 sanitized characters of production_job_id
- only ASCII alphanumeric, `-`, `_`; all other characters become `_`
- a 16-hex SHA-256 suffix

`MasterPathPolicy.ArtifactDirectory()` uses the full lower-case 64-hex
`MasterInputDigest`.

`PostProductionMasterArtifactCatalog` requires the final artifact directory to contain exactly two
entries:

- `master.mp4`
- `master-manifest.json`

Any extra/missing entry is a conflict.

### Exact C004/C007B/C008B roots already used by C009A

C009A production creation resolves:

- C004:
  `%LOCALAPPDATA%\PicotooPet\FinalVideos`
- C007B:
  `%LOCALAPPDATA%\PicotooPet\Narration\v1`
- C008B:
  `%LOCALAPPDATA%\PicotooPet\PostProduction\TextOverlay\v1`
- C009:
  `%LOCALAPPDATA%\PicotooPet\PostProduction\Master\v1`

C010A must derive these roots internally in production code. No caller-provided root/path is
authority.

### S005 real Windows evidence

`S005_WINDOWS_AUDIO_MUX_RESULT.md` is real-Windows PASS with decision:

`RECOMMEND_STREAM_COPY_AAC_MUX`

Proven final narrated shape:

- exactly one video stream
- exactly one audio stream
- no other stream
- H.264
- yuv420p
- AAC profile LC
- 48,000 Hz
- mono
- exact 8.000 s test timeline
- video packet MD5 unchanged by mux
- cancellation bounded
- timeout bounded
- overlong narration rejected before FFmpeg
- failure leaves no output

S005 used a 25 fps synthetic visual. C005 product profiles are 24 fps, so C010A real acceptance must
still cover actual C005 24 fps media.

### C009B state and reuse boundary

C009B is being implemented behind the already-frozen:

```csharp
Task ComposeAsync(
    MasterVideoCompositionRequest request,
    CancellationToken cancellationToken);
```

Its task explicitly allows only fixed FFmpeg/ffprobe process execution, media probing, stream-copy
video and fixed AAC output.

C010A may reuse a **generic already-landed C009B process execution primitive and/or neutral media
probe primitive only if** all of the following are true when C009B lands:

1. the primitive is independently callable without invoking composition/mux;
2. it accepts only internally-authored executable/arguments;
3. it has bounded stdout/stderr and bounded timeout/cancellation behavior;
4. its returned media facts are neutral facts, not a C009B-specific PASS decision;
5. using it requires **zero edits** to C009B-owned files.

C010A must **not guess or freeze a C009B class name now**.

C010A must not reuse:

- `IMasterVideoComposer`
- the narration filter graph
- the mux command builder
- C009B's output acceptance threshold
- any logic that writes or repairs media

C010A still owns:

- the exact QA ffprobe field contract
- full decode-to-null verification
- C005 frame-aware runtime policy
- final stream policy
- candidate selection
- lineage
- qa_input_digest
- receipt_digest
- receipt persistence/reuse/conflict

If C009B lands without an independently reusable generic primitive, C010A creates its own small
fixed process/probe boundary in C010A-owned new files. Do not modify C009B to force reuse.

---

## 2. Existing exact upstream types C010A consumes

### Goal

Use existing:

`GoalVideoContinuationRecord`

Exact fields relevant to C010A:

- `GoalId`
- `HandoffSha256`
- `ReturnSha256`
- `CreativeJobId`
- `CreativePackageId`
- `CreativePackageDigest`
- `CreativeStatus`
- `ProductionJobId`
- `ProductionStatus`

### Production

Use existing:

`ProductionJobRecord`

Relevant fields:

- `ProductionJobId`
- `CreativePackageId`
- `CreativePackageDigest`
- `ProductionProfile`
- `PlanDigest`
- `Status`

Use existing:

`ProductionPlanRecord`

Relevant exact fields:

- `SchemaVersion`
- `ProductionProfile`
- `ProductionJobId`
- `CreativePackageId`
- `CreativePackageDigest`
- `ProjectKey`
- `OutputProfileId`
- `TargetRuntimeMs`
- `Tasks`

Each `ProductionTaskPlanRecord` provides:

- `Order`
- `Width`
- `Height`
- `Fps`
- `FrameCount`
- `TargetDurationMs`

Use existing:

`ProductionPackageRecord`

Relevant fields:

- `ProductionPackageId`
- `ProductionJobId`
- `CreativePackageId`
- `PlanDigest`
- `PackageDigest`
- `QualityOutcome`

### Existing complete post-production source graph

Use the exact existing:

`MasterCompositionInputV1`

It already carries:

- `FinalVideoArtifact C004`
- `NarrationPlanResponseRecord NarrationPlan`
- `NarrationArtifact? NarrationArtifact`
- `CaptionOverlayPlanResponseRecord OverlayPlan`
- `TextOverlayArtifact? OverlayArtifact`

C010A should reuse this source graph instead of inventing duplicate C004/C007/C008 input records.

### C009 candidate

Use the exact existing:

`MasterVideoArtifact`

Fields:

- `ProductionJobId`
- `ProductionPackageId`
- `ProductionPackageDigest`
- `ProductionPlanDigest`
- `MasterInputDigest`
- `OutputProfileId`
- `TargetRuntimeMs`
- `FilePath`
- `ManifestPath`
- `Sha256`
- `Bytes`
- `HasAudio`
- `VisualSourceKind`
- `Reused`

The artifact alone is **not enough** to certify full lineage. C010A must also verify the current
source graph and the strict `MasterManifest`.

---

## 3. Exact C009A MasterManifest fields

C010A must treat the landed internal `MasterManifest` as the C009 durable truth and must not
invent an alternate C009 manifest schema.

Exact fields are:

- `schema_version`
- `master_profile_id`
- `video_profile_id`
- `audio_profile_id`
- `production_job_id`
- `production_package_id`
- `production_package_digest`
- `creative_package_id`
- `creative_package_digest`
- `production_plan_digest`
- `target_runtime_ms`
- `output_profile_id`
- `narration_required`
- `narration_plan_digest`
- `narration_manifest_sha256`
- `narration_segments[]`
- `overlays_required`
- `caption_overlay_plan_digest`
- `c004_source_sha256`
- `c004_source_bytes`
- `selected_visual_kind`
- `selected_visual_sha256`
- `selected_visual_bytes`
- `c008b_artifact_sha256`
- `c008b_artifact_bytes`
- `c008b_manifest_sha256`
- `output_file_name`
- `output_sha256`
- `output_bytes`
- `has_audio`
- `master_input_digest`
- `created_at`

Each `MasterManifestNarrationSegment` contains:

- `segment_id`
- `beat_id`
- `order`
- `text_sha256`
- `start_ms`
- `end_ms`
- `wav_sha256`
- `wav_bytes`
- `actual_duration_ms`
- `sample_frames`
- `sample_rate`
- `channels`
- `bits_per_sample`

C010A records/hash-binds these facts but never persists raw narration text.

### Important exact digest nuance

Current `MasterInputIdentity.Compute()` does bind:

- C004 source SHA/bytes
- C008B artifact SHA/bytes
- caption overlay plan digest
- Creative package id/digest
- master/video/audio profile ids
- narration plan digest
- narration_required
- full narration segment identities
- output profile
- overlays_required
- Production job/package/plan identities
- selected visual SHA/bytes/kind
- target runtime

Current `MasterInputIdentity.Compute()` does **not** include:

- `NarrationManifestSha256`
- `C008BManifestSha256`

Those hashes still exist in `MasterManifest` and catalog equality validation.

Therefore C010A's `qa_input_digest` must explicitly bind both upstream manifest hashes when they are
present. Do not assume `MasterInputDigest` alone cryptographically commits those two manifest file
hashes.

---

## 4. Exact C010A input contract

Add one C010A-owned record with this exact semantic shape:

```text
FinalVideoQaInputV1
  GoalContinuation : GoalVideoContinuationRecord
  ProductionJob    : ProductionJobRecord
  ProductionPlan   : ProductionPlanRecord
  ProductionPackage: ProductionPackageRecord
  MasterInput      : MasterCompositionInputV1
  MasterArtifact   : MasterVideoArtifact?
```

No other path/media authority is accepted.

### Cardinality rule

Compute only from the existing plans:

```text
postproduction_required =
    MasterInput.NarrationPlan.Plan.NarrationRequired
    OR
    MasterInput.OverlayPlan.Plan.OverlaysRequired
```

Then enforce:

#### If postproduction_required = true

- `MasterArtifact` MUST be non-null.
- final QA candidate MUST be that exact current `MasterVideoArtifact`.
- `MasterInput.C004` remains mandatory lineage.
- C004 is never a fallback candidate.
- if exact C009 artifact is absent: `FINAL_QA_MASTER_REQUIRED`.

#### If postproduction_required = false

- `MasterArtifact` MUST be null.
- `MasterInput.NarrationArtifact` MUST be null.
- `MasterInput.OverlayArtifact` MUST be null or a non-authoritative passthrough object only if an
  already-existing caller flow cannot omit it; preferred contract is null.
- final QA candidate MUST be `MasterInput.C004`.
- no C009 master lookup becomes delivery authority.

C010A must reject an input that tries to make a stale C009 artifact authoritative when both plans say
post-production is not required.

### C007/C008 exact validation

Before candidate lookup:

- call `NarrationPlanContract.Validate(MasterInput.NarrationPlan)`;
- call `CaptionOverlayPlanParser.Validate(MasterInput.OverlayPlan)`;
- recompute overlay digest using the already-landed canonical path
  `PostProductionMasterSourceVerifier.ComputeOverlayPlanDigest()`;
- require computed overlay digest equals
  `MasterInput.OverlayPlan.CaptionOverlayPlanDigest`.

Current v1 must still require:

- `CaptionsRequired == false`
- `Captions.Count == 0`

Non-empty/required captions fail:

`FINAL_QA_CAPTION_PROFILE_UNSUPPORTED`

### ProductionPlan digest validation

C010A must recompute the current `ProductionPlanRecord` canonical digest rather than trusting only
the repeated string.

Use the existing canonical JSON behavior:

1. `JsonSerializer.SerializeToNode(ProductionPlan)`
2. `CanonicalJson.Serialize(node)`
3. SHA-256 lower-case hex

Require that result equals all current authorities:

- `ProductionJob.PlanDigest`
- `ProductionPackage.PlanDigest`
- `MasterInput.NarrationPlan.Plan.ProductionPlanDigest`
- `MasterInput.OverlayPlan.Plan.ProductionPlanDigest`
- when C009 required: `MasterArtifact.ProductionPlanDigest`
- when C009 required: `MasterManifest.ProductionPlanDigest`

### Goal/Production lineage

Require:

- Goal production job id exists and equals `ProductionJob.ProductionJobId`
- Goal production status is `production_ready`
- ProductionJob status is `production_ready`
- Goal creative package id/digest equal ProductionJob creative package id/digest
- ProductionPlan production job/package id/digest agree
- ProductionPackage production job id equals ProductionJob
- ProductionPackage creative package id equals Goal/Production
- ProductionPackage quality outcome is `PASS`
- C004 production job id/package id/package digest agree with ProductionPackage
- narration/overlay plan production job/package id/digest agree with current Production facts
- narration target runtime equals ProductionPlan target runtime
- overlay target runtime equals ProductionPlan target runtime
- overlay output profile equals ProductionPlan output profile

Receipt additionally carries Goal's:

- `GoalId`
- `HandoffSha256`
- `ReturnSha256`
- `CreativeJobId`

### Reuse C009A source verification

C010A should reuse the already-landed `PostProductionMasterSourceVerifier` from the same Desktop
assembly for upstream local artifacts.

Use the exact fixed roots.

Reverify:

- C004 always
- C007B only if narration required
- C008B only if overlays required

This gives C010A the same fail-closed path/hash/manifest semantics C009A used to create the master,
without changing the verifier.

C010A then independently adds final media QA and Delivery Receipt logic.

### Exact current C009 expectation

When post-production is required, build current `MasterIdentityFacts` from the newly reverified
sources using the same field mapping C009A currently uses in
`PostProductionMasterCompositorService.ComposeAsync()`.

Compute:

`MasterInputIdentity.Compute(identity)`

Require it equals:

- supplied `MasterArtifact.MasterInputDigest`
- strict `MasterManifest.MasterInputDigest`

Construct:

`MasterArtifactExpectation(identity, computedDigest)`

Then call the existing:

`PostProductionMasterArtifactCatalog.FindVerifiedExactAsync(expectation)`

The returned verified artifact must match the supplied `MasterArtifact` for:

- ProductionJobId
- ProductionPackageId
- ProductionPackageDigest
- ProductionPlanDigest
- MasterInputDigest
- OutputProfileId
- TargetRuntimeMs
- normalized FilePath
- normalized ManifestPath
- Sha256
- Bytes
- HasAudio
- VisualSourceKind

`Reused` is operational and is not receipt identity.

This is the exact digest-scoped lookup. Do not scan the Master root by timestamp or filename.

### Exact C004 fallback lookup

When no post-production is required, verify C004 through the landed source verifier.

The exact C004 file names remain:

- `final-<sha256(production_job_id)[0:32]>.mp4`
- `final-<sha256(production_job_id)[0:32]>.final-video.json`

under:

`%LOCALAPPDATA%\PicotooPet\FinalVideos`

Hash the verified C004 manifest and bind that SHA to the receipt.

---

## 5. Final QA media policy

### Fixed QA profile

Freeze:

`final-video.qa.windows.v1`

### Candidate kinds

Freeze:

- `c009_master_v1`
- `c004_fallback_v1`

### Artifact root profile ids

Freeze:

- C009: `postproduction-master.local.v1`
- C004: `final-videos.local.v1`

### Output profile mapping

C010A owns this closed mapping:

| OutputProfileId | width | height | fps |
|---|---:|---:|---:|
| `video.landscape.v1` | 832 | 480 | 24 |
| `video.vertical.v1` | 480 | 832 | 24 |
| `video.square.v1` | 640 | 640 | 24 |

Unknown profile fails closed.

---

## 6. Fixed ffprobe contract

C010A probes only the already SHA/bytes/path-verified candidate.

Allowed executable:

`ffprobe.exe`

No caller executable or arguments.

Required process properties:

- `UseShellExecute=false`
- `CreateNoWindow=true`
- `ArgumentList`
- bounded timeout
- process-tree kill on timeout/cancel
- bounded stdout
- stderr drained but never returned in user-facing errors/receipt

Use a fixed field set equivalent to:

```text
-v error
-count_packets
-show_entries
  format=format_name,duration,nb_streams:
  stream=index,codec_type,codec_name,profile,pix_fmt,width,height,
         r_frame_rate,avg_frame_rate,duration,time_base,
         sample_rate,channels,channel_layout,nb_read_packets:
  stream_disposition=attached_pic
-of json
<candidate>
```

The implementation may format this as one source-controlled `-show_entries` argument; caller data
must not alter it.

Bound the returned JSON before parsing.

Strictly parse only the needed facts into a C010A-owned neutral media fact record. Do not persist raw
ffprobe JSON.

### Required probe result

Container:

- MP4-family format
- positive finite duration
- stream count exactly matches expected shape

Video:

- exactly one video stream
- index 0
- `codec_name == h264`
- `pix_fmt == yuv420p`
- width/height exactly match output profile
- effective fps mathematically equals 24/1
- attached_pic false
- positive duration/timing
- packet count, when reported, must be positive

FPS parsing uses exact rational integer arithmetic.

Do not accept 24000/1001 as 24.

---

## 7. Full decode-to-null contract

A successful ffprobe is not sufficient.

Allowed executable:

`ffmpeg.exe`

Run one fixed decode validation after structural probe.

Equivalent non-narrated shape:

```text
-hide_banner
-loglevel error
-nostdin
-xerror
-i <verified candidate>
-map 0:v:0
-f null
-
```

Equivalent narrated shape:

```text
-hide_banner
-loglevel error
-nostdin
-xerror
-i <verified candidate>
-map 0:v:0
-map 0:a:0
-f null
-
```

No:

- persistent output
- codec selection
- filter
- scale
- trim
- timestamp repair
- error-ignore flag
- shell

Any nonzero exit, timeout or malformed execution fails QA.

Raw stderr is never persisted or surfaced.

---

## 8. Exact stream rules

### narration_required = false

Require exactly:

- total streams = 1
- stream 0 = H.264/yuv420p video
- zero audio
- zero subtitle/data/attachment/unknown streams

A silent AAC stream still fails.

### narration_required = true

Require exactly:

- total streams = 2
- stream 0 = H.264/yuv420p video
- stream 1 = AAC audio
- AAC profile = `LC`
- sample rate = 48000
- channels = 1
- channel layout = mono when ffprobe reports it
- zero subtitle/data/attachment/unknown streams

Also require:

- `MasterVideoArtifact.HasAudio == true`
- `MasterManifest.HasAudio == true`
- `MasterManifest.NarrationRequired == true`

When narration is false, all three corresponding facts must be false.

Do not gate on exact reported AAC bitrate. S005 freezes 128 kb/s as producer policy, but container
bitrate reporting is not a reliable independent QA measurement.

---

## 9. Frame-aware runtime policy

Do not compare final duration to `TargetRuntimeMs` with one naive fixed tolerance.

### First validate C005 task timing facts

Require:

- tasks non-empty
- orders contiguous from 1
- all task fps = profile fps = 24
- all task width/height equal the profile
- each FrameCount > 0
- each TargetDurationMs > 0
- sum(TargetDurationMs) == ProductionPlan.TargetRuntimeMs

### Expected visual duration

Compute with integer/rational arithmetic:

```text
total_frames = sum(task.FrameCount)
fps = 24

expected_visual_duration_us =
    total_frames * 1_000_000 / fps
```

Keep numerator/denominator or checked integer arithmetic until comparison; do not use locale-dependent
double formatting as identity.

```text
target_runtime_us =
    ProductionPlan.TargetRuntimeMs * 1000

quantization_delta_us =
    abs(expected_visual_duration_us - target_runtime_us)

one_frame_us =
    ceil(1_000_000 / fps)
```

### Video duration acceptance

Require:

```text
abs(observed_video_duration_us - expected_visual_duration_us)
    <= one_frame_us
```

and:

```text
abs(observed_video_duration_us - target_runtime_us)
    <= quantization_delta_us + one_frame_us
```

If ffprobe exposes both stream duration and packet-count/fps-derived duration, require them to be
mutually consistent within one frame.

### Format/container duration acceptance

Freeze C010A v1:

`ContainerTimestampBudgetUs = 100_000`

Require:

```text
abs(observed_format_duration_us - target_runtime_us)
    <= quantization_delta_us + 100_000
```

### Narrated audio duration

When narration is required and a usable audio stream duration is reported:

```text
abs(observed_audio_duration_us - target_runtime_us)
    <= 100_000
```

If audio stream duration is unavailable, implementation must derive an equivalent bounded timing fact
from the fixed probe path or fail closed. It must not silently skip the audio runtime check.

### Cross-duration sanity

Container duration must agree with the longest intended stream within the same 100 ms container
budget.

C010A never modifies media to make duration pass.

### S005 interpretation

S005 real Windows produced exact 8.000 s output under the frozen AAC path, so 100 ms is a deliberately
conservative container/AAC budget.

C009B real C005 24 fps integration is still required before final system acceptance; implementation
must not silently widen the budget based on one machine.

---

## 10. Overlay/caption deterministic evidence

C010A does not OCR the video and does not invoke a vision model.

When overlays are required, deterministic evidence is:

```text
CaptionOverlayPlanDigest
  -> reverified C008B artifact SHA/bytes
  -> reverified C008B manifest SHA
  -> C009 MasterManifest.C008B*
  -> MasterManifest.SelectedVisualKind == c008b_overlay_v1
  -> MasterManifest.SelectedVisualSha256
  -> MasterInputDigest
  -> final master SHA
  -> C010 receipt
```

When overlays are false:

- selected visual kind must be `c004_final_v1`;
- C008B artifact/manifest fields in current Master identity must be null;
- fallback case uses C004 directly.

Captions remain:

- required = false
- list empty

No ASR/OCR/AI may turn narration into captions for C010A.

---

## 11. QA digest identity

C010A defines a new digest. It does not rename/recompute C009's `MasterInputDigest`.

### qa_input_digest

Use canonical UTF-8 JSON with sorted keys, compact separators and invariant numeric representation.

The canonical identity must include:

#### Policy

- `schema_version = 1.0`
- `qa_profile_id = final-video.qa.windows.v1`
- fixed container timestamp budget
- fixed candidate kind
- fixed artifact-root-profile id

#### Goal

- goal_id
- handoff_sha256
- return_sha256
- creative_job_id
- creative_package_id
- creative_package_digest

#### Production

- production_job_id
- recomputed production_plan_digest
- production_package_id
- production_package_digest
- output_profile_id
- target_runtime_ms
- ordered task timing/media facts:
  - order
  - width
  - height
  - fps
  - frame_count
  - target_duration_ms

#### C007

- narration_required
- narration_plan_digest
- narration_manifest_sha256 nullable

#### C008

- captions_required
- overlays_required
- caption_overlay_plan_digest
- c008b_artifact_sha256 nullable
- c008b_artifact_bytes nullable
- c008b_manifest_sha256 nullable

#### C004

- c004_manifest_sha256
- c004_final_sha256
- c004_final_bytes

#### C009 when required

- master_profile_id = exact `postproduction.master.v1`
- video_profile_id = exact `video.h264.stream-copy.v1`
- audio_profile_id = exact `audio.aac-lc.48k.mono.128k.v1`
- master_input_digest
- master_manifest_sha256
- selected_visual_kind
- selected_visual_sha256
- selected_visual_bytes

#### Final candidate

- artifact_file_name
- artifact_sha256
- artifact_bytes

Do not include:

- absolute paths
- mtimes
- `Reused`
- process ids
- retry counts
- `verified_at`
- raw narration/overlay text

### Why manifest hashes are explicitly included

C009A's `MasterInputDigest` does not currently include the C007B or C008B manifest SHA fields.

C010A deliberately binds them in `qa_input_digest` so the Delivery Receipt certifies the exact
upstream provenance files that were reverified.

---

## 12. PASS-only receipt persistence

C010A owns:

`%LOCALAPPDATA%\PicotooPet\PostProduction\DeliveryReceipts\v1`

Use deterministic layout:

```text
DeliveryReceipts\v1\
  <safe-job-prefix>-<sha256(production_job_id)[0:16]>\
    <qa_input_digest>\
      final-artifact-receipt.json
```

Use the same safe-job policy shape as C009A.

No MP4 is copied into the receipt root.

### Atomic write

For a fresh PASS:

1. create generated sibling temp directory under the receipt job directory;
2. write only `final-artifact-receipt.json`;
3. close handle;
4. strict re-read/recompute digest;
5. atomically move temp directory to exact qa_input_digest directory.

On failure/cancel:

- remove only C010A-owned temp state best-effort;
- never modify/delete C004/C007B/C008B/C009 artifacts;
- write no durable PASS receipt.

### Exact reuse

If exact receipt directory exists:

- require exactly one entry with exact file name;
- ordinary file only;
- no reparse escape;
- bounded size;
- strict deserialize with unmapped members disallowed;
- qa_input_digest must equal current expected digest;
- recompute receipt_digest;
- reverify final candidate SHA/bytes and current manifest hashes;
- if all match, return reused PASS without rerunning ffprobe/decode.

### Conflict

If the expected exact receipt directory exists but any durable fact differs:

`FINAL_QA_RECEIPT_CONFLICT`

Never overwrite.

A changed input produces a different qa_input_digest directory.

---

## 13. Error model

Use bounded C010A-only codes:

- `FINAL_QA_INPUT_INVALID`
- `FINAL_QA_LINEAGE_MISMATCH`
- `FINAL_QA_MASTER_REQUIRED`
- `FINAL_QA_CAPTION_PROFILE_UNSUPPORTED`
- `FINAL_QA_ARTIFACT_INVALID`
- `FINAL_QA_HASH_MISMATCH`
- `FINAL_QA_PROBE_UNAVAILABLE`
- `FINAL_QA_PROBE_FAILED`
- `FINAL_QA_DECODE_FAILED`
- `FINAL_QA_TIMEOUT`
- `FINAL_QA_CONTAINER_INVALID`
- `FINAL_QA_VIDEO_STREAM_INVALID`
- `FINAL_QA_OUTPUT_PROFILE_MISMATCH`
- `FINAL_QA_RUNTIME_MISMATCH`
- `FINAL_QA_AUDIO_STREAM_INVALID`
- `FINAL_QA_UNEXPECTED_STREAM`
- `FINAL_QA_OVERLAY_PROVENANCE_INVALID`
- `FINAL_QA_RECEIPT_CONFLICT`

Cancellation propagates as cancellation.

Never expose:

- raw ffprobe JSON
- FFmpeg stderr
- absolute path
- narration text
- overlay text
- command line
- token
- stack trace

---

# READY_TO_IMPLEMENT

**YES — C010A core is ready to implement against the concrete C009A contracts already on this
branch.**

Implementation does not need to wait for C009B class names.

C009B is a final real-media dependency for end-to-end acceptance, not a blocker for implementing:

- lineage validation
- candidate selection
- C009 catalog lookup
- C004 fallback verification
- media policy
- digest logic
- receipt storage/reuse/conflict
- fake-process/fake-probe tests

C010A must not modify Goal Center. Goal projection remains C010B.

# DEPENDENCIES

Required code/contracts already available in the C010A base:

1. **C004**
   - `FinalVideoArtifact`
   - fixed C004 FinalVideos root/manifest convention.

2. **C005**
   - `ProductionPlanRecord.OutputProfileId`
   - `ProductionPlanRecord.TargetRuntimeMs`
   - `ProductionTaskPlanRecord.Width/Height/Fps/FrameCount/TargetDurationMs`.

3. **C007A/C007B**
   - `NarrationPlanResponseRecord`
   - `NarrationPlanContract`
   - `NarrationArtifact`.

4. **C008A/A2/C008B**
   - `CaptionOverlayPlanResponseRecord`
   - `CaptionOverlayPlanParser`
   - `TextOverlayArtifact`.

5. **C009A**
   - `MasterCompositionInputV1`
   - `MasterVideoArtifact`
   - `MasterIdentityFacts`
   - `MasterArtifactExpectation`
   - `MasterInputIdentity`
   - `MasterPathPolicy`
   - `PostProductionMasterSourceVerifier`
   - `PostProductionMasterArtifactCatalog`
   - exact `MasterManifest`.

6. **S005**
   - real-Windows proof of H.264 stream-copy + AAC-LC/48k/mono and fixed timeline behavior.

7. **C009B**
   - not required to begin C010A implementation;
   - required before final narrated-master real-Windows acceptance;
   - C010A may reuse a generic process/probe primitive only if it lands independently reusable with
     zero C009B file changes.

# FILES OWNERSHIP

C010A should prefer new files only.

Recommended owned source files:

- `windows/desktop/src/PicotooPet.Desktop/Services/FinalVideoQaContracts.cs`
- `windows/desktop/src/PicotooPet.Desktop/Services/FinalVideoQaService.cs`
- `windows/desktop/src/PicotooPet.Desktop/Services/FinalVideoQaMediaProbe.cs`
- `windows/desktop/src/PicotooPet.Desktop/Services/FinalArtifactReceiptStore.cs`

Optional if separation is useful:

- `windows/desktop/src/PicotooPet.Desktop/Services/FinalVideoQaLineageValidator.cs`

Owned tests:

- `windows/desktop/tests/PicotooPet.FinalVideoQa.SmokeTests/`

Do not modify:

- C004 `FinalVideoAssemblyService.cs`
- C007 narration producer/contracts
- C008 overlay producer/contracts
- C009A contracts/catalog/source verifier/compositor
- C009B composer/process/media files
- Production/Core schemas
- ProductionPackage
- Goal Center/UI
- Maotai/Natural Motion
- deploy/macos
- publishing/export
- shared smoke `Program.cs` if it creates parallel ownership overlap

This docs-only task itself owns only:

`docs/architecture/video/C010A_IMPLEMENTATION_BRIEF_V1.md`

# EXACT INPUT CONTRACT

Implement C010A around this semantic contract:

```text
FinalVideoQaInputV1
  GoalContinuation  : GoalVideoContinuationRecord
  ProductionJob     : ProductionJobRecord
  ProductionPlan    : ProductionPlanRecord
  ProductionPackage : ProductionPackageRecord
  MasterInput       : MasterCompositionInputV1
  MasterArtifact    : MasterVideoArtifact?
```

Rules:

1. validate Goal -> Production job/package lineage;
2. recompute and validate ProductionPlan digest;
3. validate C007/C008 strict plans/digests;
4. derive:
   `postproduction_required = NarrationRequired || OverlaysRequired`;
5. reverify C004/C007B/C008B through existing C009A source verifier;
6. when post-production is required:
   - `MasterArtifact` is mandatory;
   - reconstruct exact current `MasterIdentityFacts`;
   - recompute exact `MasterInputDigest`;
   - build `MasterArtifactExpectation`;
   - use exact C009A digest-scoped catalog lookup;
   - candidate = verified `MasterVideoArtifact`;
7. otherwise:
   - `MasterArtifact` must be null;
   - candidate = reverified `MasterInput.C004`;
8. no arbitrary path/executable/media-policy field is present.

Production constructor may internally derive the five fixed roots:

- FinalVideos
- Narration/v1
- TextOverlay/v1
- Master/v1
- DeliveryReceipts/v1

Tests may inject isolated absolute roots through an internal constructor.

# EXACT RECEIPT CONTRACT

Implement a strict C010A-owned:

`FinalArtifactReceiptV1`

with exactly the following semantic fields:

### Header

- `schema_version = "1.0"`
- `qa_profile_id = "final-video.qa.windows.v1"`
- `qa_input_digest` — 64 lower-case hex
- `receipt_digest` — 64 lower-case hex
- `outcome = "PASS"`

### Goal / Creative

- `goal_id`
- `handoff_sha256`
- `return_sha256`
- `creative_job_id`
- `creative_package_id`
- `creative_package_digest`

### Production

- `production_job_id`
- `production_plan_digest`
- `production_package_id`
- `production_package_digest`
- `target_runtime_ms`
- `output_profile_id`

### C007

- `narration_required`
- `narration_plan_digest`
- `narration_manifest_sha256` nullable
- `narration_segments[]`, bounded, each containing:
  - segment_id
  - beat_id
  - order
  - text_sha256
  - start_ms
  - end_ms
  - wav_sha256
  - wav_bytes
  - actual_duration_ms
  - sample_frames
  - sample_rate
  - channels
  - bits_per_sample

For no narration, the list is empty and manifest SHA is null.

### C008

- `captions_required` — v1 must be false
- `overlays_required`
- `caption_overlay_plan_digest`
- `c008b_artifact_sha256` nullable
- `c008b_artifact_bytes` nullable
- `c008b_manifest_sha256` nullable

For no overlay, all C008B artifact fields are null.

### C004

- `c004_manifest_sha256`
- `c004_source_sha256`
- `c004_source_bytes`

### Candidate / C009

- `candidate_kind`
  - `c009_master_v1`
  - `c004_fallback_v1`
- `artifact_root_profile_id`
  - `postproduction-master.local.v1`
  - `final-videos.local.v1`
- `selected_visual_kind`
  - exact C009 value, or `c004_final_v1` for fallback
- `selected_visual_sha256`
- `selected_visual_bytes`
- `master_profile_id` nullable
- `video_profile_id` nullable
- `audio_profile_id` nullable
- `master_input_digest` nullable
- `master_manifest_sha256` nullable
- `artifact_file_name`
- `artifact_sha256`
- `artifact_bytes`

For C009 candidate, master/profile/digest/manifest fields are required and must match exact C009A
constants/manifest.

For C004 fallback, those C009-only fields are null.

### Observed media

Nested strict `observed_media`:

- `container_family = "mp4"`
- `format_duration_us`
- `stream_count`
- `video`:
  - index
  - codec_name
  - pixel_format
  - width
  - height
  - fps_numerator
  - fps_denominator
  - duration_us
  - packet_count nullable
- `audio` nullable:
  - index
  - codec_name
  - profile
  - sample_rate
  - channels
  - channel_layout nullable
  - duration_us

Do not persist raw ffprobe JSON.

### QA evidence

- `passed_check_ids[]`, exact ordered closed list:
  - `lineage.v1`
  - `managed-file.v1`
  - `sha-bytes.v1`
  - `mp4-probe.v1`
  - `full-decode.v1`
  - `video-stream.v1`
  - `output-profile.v1`
  - `runtime.v1`
  - `audio-contract.v1`
  - `unexpected-streams.v1`
  - `overlay-provenance.v1`

- `verified_at`

`receipt_digest` binds every deterministic field above except:

- `receipt_digest` itself
- `verified_at`

`qa_input_digest` follows the exact identity defined earlier and excludes observed media and
verification timestamp.

Receipt is persisted only after every check passes.

# TESTS

## Pure/contract

- strict input shape; no caller path/executable/codec/filter authority
- exact C009 profile constants accepted
- unknown profile rejected
- ProductionPlan canonical digest matches known Core fixture
- bad ProductionJob/Package/Plan digest rejected
- C007 digest mismatch rejected
- C008 digest mismatch rejected
- captions required/nonempty rejected
- same QA input => same qa_input_digest
- narration/C008 manifest SHA change => qa_input_digest changes even if MasterInputDigest is same
- verified_at does not change receipt_digest
- observed media change changes receipt_digest

## Candidate selection

- no narration/no overlay => exact C004 fallback
- narration only => exact C009 required
- overlay only => exact C009 required
- narration + overlay => exact C009 required
- post-production required + null master => FINAL_QA_MASTER_REQUIRED
- no post-production + supplied stale master => reject
- never select by timestamp/newest directory

## C009A exact lookup

- reconstruct current MasterIdentityFacts
- computed digest equals MasterArtifact.MasterInputDigest
- exact job/digest path accepted
- wrong digest directory rejected
- extra master directory entry rejected
- missing master manifest/output rejected
- catalog tamper/conflict propagated as bounded C010 failure
- supplied artifact must equal catalog-returned artifact except Reused operational flag
- hash MasterManifest and bind to receipt

## C004/C007B/C008B lineage

- C004 exact final path/hash/bytes pass
- C004 manifest tamper fail
- narration-required exact narration manifest/WAV chain pass
- narration manifest/WAV tamper fail
- overlay-required exact C008B plan/artifact/manifest chain pass
- overlay source C004 SHA mismatch fail
- C008B artifact/manifest tamper fail
- no raw narration/overlay text in receipt/error

## ffprobe

- fixed executable only
- fixed field set only
- bounded stdout
- malformed JSON fail
- valid MP4 pass
- corrupt MP4 fail
- exactly one video
- H.264 only
- yuv420p only
- attached picture fail
- no second video

## Output profiles

Parameterize all C005 profiles:

- 832x480 @ 24
- 480x832 @ 24
- 640x640 @ 24

Negative:

- swapped dimensions
- off-by-one dimension
- 24000/1001
- 25 fps
- 30 fps
- zero/unknown fps

## Runtime

- exact frame-plan duration pass
- one-frame boundary pass
- >1 frame deviation fail
- legitimate C005 quantization delta pass
- format within quantization + 100 ms pass
- format beyond bound fail
- narrated audio within 100 ms pass
- narrated audio beyond 100 ms fail
- rational math independent of locale
- multi-shot sum uses C005 FrameCount, not Creative durations

## Audio

Narration required:

- one AAC LC / 48000 / mono pass
- no audio fail
- second audio fail
- non-AAC fail
- non-LC fail
- 44100 fail
- stereo fail

Narration false:

- zero audio pass
- silent AAC still fail

## Unexpected streams

Reject:

- subtitle
- data
- attachment
- second video/audio
- unknown stream
- attached picture
- unexpected chapter

## Full decode

- structurally readable valid file decodes to null
- header-valid corrupted packets fail
- timeout kills process tree
- cancel kills process tree
- stderr not surfaced
- no persistent output

## Receipt/restart

- PASS writes one immutable receipt directory
- failure writes no receipt
- identical restart reuses receipt without ffprobe/decode
- receipt strict unknown field rejected
- receipt tamper conflict
- artifact tamper after receipt invalidates reuse
- upstream manifest tamper invalidates reuse
- partial final receipt directory conflict
- C010 temp cleanup only
- changed qa_input_digest creates new directory, never overwrites old receipt

## Real Windows

After C009B lands:

1. C004 fallback real 832x480 @24 QA PASS.
2. C009 narration-only real 832x480 @24 QA PASS.
3. C009 overlay-only real master QA PASS.
4. C009 overlay+narration real master QA PASS.
5. Repeat for vertical/square media metadata at minimum through parameterized real fixtures.
6. Confirm exactly H.264/yuv420p.
7. Confirm AAC LC / 48000 / mono when narration required.
8. Confirm zero audio otherwise.
9. Confirm no unexpected streams.
10. Confirm duration policy against actual C005 frame plans.
11. Confirm ffmpeg full decode-to-null.
12. Corrupt a test copy and prove probe/decode rejection.
13. Create receipt, restart, prove exact reuse.
14. Tamper final artifact after PASS and prove reuse/open candidate becomes invalid.
15. Confirm receipt contains no absolute path, raw text, raw command, stderr or raw ffprobe JSON.

Regression:

- C009A smokes green
- C009B focused smokes green once landed
- C007B smokes green
- C008B smokes green
- C004 smokes green
- Windows Release build 0 errors
- no ProductionPackage mutation

# BLOCKERS

No architecture blocker prevents C010A implementation.

Remaining sequencing/acceptance dependencies:

1. **C009B implementation is still in progress.**
   C010A can be implemented now, but final narrated-master real-Windows acceptance waits for the
   concrete C009B output.

2. **Do not guess a C009B reusable class name.**
   Reuse only an already-landed generic process/probe primitive that fits the boundary above without
   modifying C009B. Otherwise keep the C010A process/probe local.

3. **Actual C005 24 fps C009B output must validate the frozen 100 ms container/AAC budget.**
   S005 real Windows PASS strongly supports the policy but used a 25 fps synthetic video.
   Do not silently widen the C010A tolerance. If product evidence disproves it, version the QA
   profile/brief explicitly.

4. **Goal Center QA Ready/QaFailed/Open wiring is not C010A.**
   It remains a later C010B slice after the receipt/catalog contract is stable.

No merge/rebase/tag/release is required by this brief.
