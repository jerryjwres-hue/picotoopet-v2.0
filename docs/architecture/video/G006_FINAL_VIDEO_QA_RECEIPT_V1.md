# G006 — Final Video QA & Delivery Receipt v1

Status: implementation-ready architecture for C010 deterministic final-video QA and immutable local
Delivery Receipt.

C010 is a Windows-local verification layer after C009. It does not mutate Production, C004, C007,
C008 or C009 artifacts. It does not publish, upload, re-render or repair media.

---

## CURRENT FACTS

This design is based on the actual repository state audited for G006.

### C004 — visual final MP4

Branch:
`feature/goal-final-video-assembly`

Audited HEAD:
`866af949a1c7d180a867cabf17b6bcb669b856f9`

Current behavior:

- `FinalVideoAssemblyService` consumes PASS ProductionPackage outputs.
- it revalidates managed paths, ordinary-file status, bytes and SHA-256.
- it concatenates visual Production outputs with fixed `ffmpeg.exe`.
- output is H.264, yuv420p, MP4, visual-only (`-an`).
- output root is:
  `%LOCALAPPDATA%\PicotooPet\FinalVideos\`
- `FinalVideoArtifact` exposes:
  - production_job_id
  - production_package_id
  - production_package_digest
  - file path
  - manifest path
  - SHA-256
  - bytes
  - reused
- C004 already has immutable local manifest/reuse/conflict behavior.
- C004 is not modified by C010.

### C005 — frozen Production timeline/output profiles

Branch:
`feature/video-timeline-output-profiles`

Audited HEAD:
`e82df96a7acddfb7cc2b26c023517b58716b226b`

C005 is the timing/output authority.

Current closed profiles:

| profile | width | height | fps |
|---|---:|---:|---:|
| `video.landscape.v1` | 832 | 480 | 24 |
| `video.vertical.v1` | 480 | 832 | 24 |
| `video.square.v1` | 640 | 640 | 24 |

`ProductionPlan` owns:

- `target_runtime_ms`
- ordered Production tasks
- per-task `target_duration_ms`
- per-task `frame_count`
- per-task `fps`

C005 frame-count quantization is intentional. C010 must not compare final media to
`target_runtime_ms` using a naive fixed zero-tolerance rule.

### Goal lineage already available

The existing Windows `GoalVideoContinuationRecord` carries:

- goal_id
- handoff_sha256
- return_sha256
- creative_job_id
- creative_package_id
- creative_package_digest
- creative_status
- production_job_id
- production_status

This is sufficient to bind the Goal/Creative side of the final receipt without adding a new Goal
database or mutating existing Goal records.

### C007A/C007B — narration

C007A already provides the authenticated Core narration plan and canonical
`narration_plan_digest`.

C007B branch:
`feature/windows-local-narration-synthesis-v1`

Audited HEAD:
`1948c6c20aec4849dd17a13bf3f402a11543d067`

C007B implementation is present.

Its managed root is:

`%LOCALAPPDATA%\PicotooPet\Narration\v1\`

The narration manifest binds:

- production_job_id
- creative_package_id/digest
- production_plan_digest
- narration_plan_digest
- TTS/voice profile
- resolved voice identity
- ordered segments
- segment_id / beat_id / order
- text_sha256
- start_ms / end_ms
- WAV file name
- WAV SHA-256 / bytes
- source sample rate / channels / bit depth
- synthesized duration

Current C007B WAVs are PCM 16-bit and may be mono or stereo at 8–48 kHz.

At audit time the latest C007B GitHub Windows workflows were still failing while the branch was in
CI closeout. This does not change C010 architecture; C010 integration should wait for the intended
upstream C007B gates to be green.

### C008A/A2/C008B — overlay visual

C008A/A2 provides:

- authenticated `CaptionOverlayPlanV1`
- canonical `caption_overlay_plan_digest`
- explicit authored overlays from `ScriptBeat.on_screen_text`
- current `captions_required=false`
- current `captions=[]`

C008B branch:
`feature/windows-caption-overlay-render-v1`

Audited HEAD:
`42ac00358999518c75478b0083a1ec2e04d6efbe`

C008B implementation is now present.

Its public local artifact is `TextOverlayArtifact`, including:

- production_job_id
- C004 source final SHA-256
- caption overlay plan digest
- output profile id
- file/manifest path
- output SHA-256 / bytes
- passthrough
- reused

When overlays exist, its immutable manifest additionally binds:

- source ProductionPackage id/digest
- C004 final SHA-256
- caption overlay plan digest
- output profile
- overlay/font/renderer profiles
- artifact identity digest
- ordered overlay cue identities
- text_sha256, start/end timing
- resolved font names/identity hashes
- derived output SHA/bytes
- passthrough flag

C008B's renderer already probes its derived output for H.264/yuv420p, dimensions, duration and absence
of non-video streams.

C010 still performs its own final media QA because:

- C008B is not the final mastered artifact when narration exists.
- C008B currently does not make C010's final delivery decision.
- C010 must independently verify fps, final audio shape, final runtime, final lineage and final SHA.

At audit time the latest C008B GitHub Windows workflows were still failing while CI closeout was in
progress. C010 integration should use a green upstream integration base.

### G004 / C009 architecture

G004 branch:
`design/postproduction-compositor-v1`

Audited HEAD:
`b7635b7caf4cb32247406ba7311f2294cfd3dab9`

G004 freezes C009 v1 as:

- if overlays are required, consume verified C008B derived MP4
- otherwise consume C004 visual MP4
- align C007B narration WAVs to C007A timing
- encode final narration to AAC-LC, 48 kHz, mono, 128 kb/s
- stream-copy H.264 video (`-c:v copy`)
- do not rerun drawtext in C009
- produce a local immutable master under:
  `%LOCALAPPDATA%\PicotooPet\PostProduction\Master\v1\`

G004 also freezes this selection rule:

```text
postproduction_required = narration_required || overlays_required
```

If post-production is not required, C009 creates no redundant master and C004 remains the legitimate
delivery fallback.

C009 implementation has not yet landed at G006 design time. Therefore C010 must consume the concrete
C009 artifact/manifest types that land from C009 rather than invent a second incompatible master
contract.

---

## QA TARGET SELECTION

C010 has exactly two valid candidate kinds:

- `c009_master_v1`
- `c004_fallback_v1`

The candidate is selected by current authenticated plan facts, never by "newest file".

### Selection rule

```text
postproduction_required =
    narration_plan.narration_required
    OR caption_overlay_plan.overlays_required
```

Then:

```text
if postproduction_required:
    QA target = exact current C009 master
else:
    QA target = exact current C004 FinalVideoArtifact
```

### Required consequences

If narration or overlay is required:

- C009 master is mandatory.
- missing C009 master is a QA/not-ready failure.
- C010 must not silently QA or open C004 instead.
- C008B derived MP4 is lineage evidence, not the final delivery candidate.

If neither narration nor overlay is required:

- C004 is the canonical fallback.
- no C009 copy/remux is required.
- C010 QA directly certifies the C004 artifact.

If a stale historical C009 master exists for a job whose current plans require no post-production:

- it is ignored.
- file timestamp/mtime does not make it authoritative.

---

## QA INPUT CONTRACT

C010 should accept a closed internal context assembled from existing trusted projections.

Conceptually:

```text
FinalVideoQaContextV1
  goal_continuation
  production_job
  production_plan
  production_package

  narration_plan_response
  caption_overlay_plan_response

  c004_final_artifact
  c007b_narration_artifact?    # required iff narration_required
  c008b_overlay_artifact?      # required iff overlays_required
  c009_master_artifact?        # required iff postproduction_required
```

The exact C009 type names come from C009 implementation.

### No caller renderer authority

C010 input must not carry caller-selected:

- artifact path
- receipt path
- ffprobe path
- ffmpeg path
- ffprobe arguments
- ffmpeg arguments
- codec
- pixel format
- width/height/fps
- duration tolerance
- sample rate/channels
- stream indexes
- output profile
- filter
- shell command
- arbitrary JSON manifest
- URL/provider/model

All expected media facts come from C005/G004 fixed profiles and verified upstream artifacts.

---

## LINEAGE VALIDATION

C010 independently closes the complete delivery lineage before probing media.

### Goal -> Creative

Require:

- current Goal id equals `GoalVideoContinuationRecord.GoalId`
- continuation has a nonblank production_job_id
- creative_job_id is present
- creative_package_id is present
- creative_package_digest is valid SHA-256
- creative status represents the adopted ready Creative package
- production status is `production_ready`

The receipt binds:

- goal_id
- handoff_sha256
- return_sha256
- creative_job_id
- creative_package_id
- creative_package_digest

### Creative -> Production

Require:

- ProductionJob.production_job_id equals continuation production_job_id
- ProductionJob.creative_package_id equals continuation creative_package_id
- ProductionJob.creative_package_digest equals continuation creative_package_digest
- ProductionJob has a bound plan_digest
- ProductionJob status is `production_ready`

Require ProductionPlan:

- production_job_id matches
- creative_package_id/digest match
- recomputed canonical ProductionPlan digest equals ProductionJob.plan_digest
- output profile is a closed C005 profile
- target runtime is valid
- ordered tasks and frame facts are valid

Require ProductionPackage:

- production_job_id matches
- creative_package_id matches
- plan_digest matches current ProductionPlan digest
- quality_outcome is PASS
- package id/digest are valid
- bounded manifest identity agrees with the record
- manifest Creative/Production provenance agrees with the continuation/job

### Production -> C004

Always require C004:

- production_job_id matches
- production_package_id matches
- production_package_digest matches
- C004 file/manifest are under the fixed FinalVideos root
- C004 file/manifest are ordinary files
- no reparse-point escape
- bytes and SHA-256 are recomputed
- C004 manifest binds the same ProductionPackage and output hash

C004 is always part of lineage even when the final candidate is C009.

### Production -> C007

Require C007A narration plan:

- production_job_id matches
- creative_package_id/digest match
- production_plan_digest matches
- target_runtime_ms equals C005 ProductionPlan target_runtime_ms
- canonical narration plan digest matches response digest

If narration_required:

- C007B artifact/manifest is required
- C007B manifest production/creative/plan/narration digests match C007A
- every planned narration segment resolves exactly once
- WAV SHA/bytes/media facts revalidate

If narration_required=false:

- final candidate must not gain an audio stream merely because stale narration files exist.

### Production -> C008

Require C008A2 overlay plan:

- production_job_id matches
- creative_package_id/digest match
- production_plan_digest matches
- target_runtime_ms equals C005
- output_profile_id equals C005
- canonical caption-overlay digest matches response digest

Current C010 v1 additionally requires:

- `captions_required=false`
- `captions=[]`

If a future nonempty caption contract reaches this v1:

`FINAL_QA_CAPTION_PROFILE_UNSUPPORTED`

must fail closed rather than silently certifying a video that may lack captions.

If overlays_required:

- C008B non-passthrough artifact/manifest is required
- C008B production_job_id matches
- C008B source_final_sha256 equals reverified C004 SHA
- C008B caption_overlay_plan_digest matches C008A2
- C008B output profile matches C005
- C008B output SHA/bytes revalidate
- C008B manifest cue ids/order/text hashes/start/end match the overlay plan
- C008B manifest hash is captured as lineage evidence

### C004/C007/C008 -> C009

When post-production is required, require the exact current C009 master.

C010 verifies the C009 manifest against current facts, including at minimum:

- production_job_id
- ProductionPackage id/digest
- CreativePackage id/digest
- ProductionPlan digest
- target_runtime_ms
- output_profile_id
- C004 source final SHA/bytes
- selected visual source kind
- selected visual SHA/bytes
- narration plan digest
- narration_required
- C007B manifest SHA when narration is required
- caption overlay plan digest
- overlays_required
- C008B manifest SHA when overlays are required
- master video/audio policy ids
- master composition digest
- output SHA/bytes

If overlays are required:

`selected_visual_source_kind` must be `c008b_overlay_v1`.

If overlays are not required:

`selected_visual_source_kind` must be `c004_final_v1`.

C010 hashes the master manifest itself and records that manifest SHA in the Delivery Receipt.

---

## MANAGED FILE VERIFICATION

Before launching ffprobe/ffmpeg, C010 revalidates the selected final candidate.

### C009 master candidate

Expected root:

`%LOCALAPPDATA%\PicotooPet\PostProduction\Master\v1\`

Require:

- expected deterministic job/digest directory
- ordinary `master.mp4`
- ordinary strict master manifest
- no reparse escape in any path component
- file size > 0 and bounded
- recomputed MP4 SHA equals C009 artifact/manifest
- recomputed manifest SHA equals current lineage evidence

### C004 fallback candidate

Expected root:

`%LOCALAPPDATA%\PicotooPet\FinalVideos\`

Require:

- exact deterministic C004 final file for the current Production job
- exact C004 manifest
- ordinary files
- no reparse escape
- recomputed MP4 bytes/SHA match `FinalVideoArtifact`
- manifest agrees with ProductionPackage and final hash

### No path persisted as authority

The receipt stores file names/root-profile identities and hashes, not arbitrary absolute paths.

When Goal Center later opens the artifact, the local catalog reconstructs/resolves the path from:

- candidate kind
- current job/digest identity
- fixed managed root

and rechecks ordinary-file status + SHA/bytes.

---

## FIXED MEDIA PROBE BOUNDARY

C010 owns a fixed media-verification process boundary.

### Allowed executables

Only:

- `ffprobe.exe`
- `ffmpeg.exe`

No caller can select an executable.

### Process rules

Both tools use:

- `UseShellExecute=false`
- `CreateNoWindow=true`
- `ProcessStartInfo.ArgumentList`
- no shell
- no PowerShell/cmd
- fixed internally-authored arguments
- fixed bounded timeout
- process-tree termination on timeout/cancel
- stdout/stderr drained
- bounded ffprobe stdout
- raw stderr never persisted or shown to the user

### Structural probe

Use fixed `ffprobe.exe` JSON output.

The internal probe requests only fields required by the QA policy, conceptually:

- format name
- format duration
- stream count
- stream index
- codec_type
- codec_name
- codec profile
- pix_fmt
- width / height
- avg_frame_rate / r_frame_rate
- stream duration / time base where available
- audio sample_rate
- audio channels / channel_layout
- stream disposition needed to reject attached pictures

The exact command is source-controlled.

No arbitrary `show_entries` string may enter from caller data.

### Decode readability pass

A successful ffprobe header/index parse alone does not prove every packet is decodable.

C010 v1 therefore also performs one fixed decode-to-null validation with `ffmpeg.exe`:

- input is only the already verified final candidate
- map the expected video stream
- map expected audio stream only when narration is required
- decode to the fixed null muxer
- write no media output
- any decode error/nonzero exit fails QA
- cancellation/timeout terminates the process

This is deterministic media readability checking, not re-rendering.

The QA decode must not:

- scale
- transcode to a persistent file
- repair timestamps
- drop errors
- trim
- rewrite the candidate

---

## DETERMINISTIC MEDIA CHECKS

C010 PASS requires every check below.

### Container

Require:

- ffprobe exits successfully
- format identifies the input as MP4-family
- candidate extension is the internally expected `.mp4`
- fixed decode-to-null pass succeeds
- format duration is positive and parseable
- exactly the expected streams exist

### Video stream count/order

Require exactly one video stream.

For v1:

- video stream index must be 0
- attached-pic disposition must be false
- no second video stream is allowed

### Video codec / pixel format

Require:

- `codec_name == h264`
- `pix_fmt == yuv420p`

C010 does not merely trust the C009/C004 manifest for these facts.

### Width / height

Resolve the C005 output profile and require exact equality.

Examples:

- landscape: 832x480
- vertical: 480x832
- square: 640x640

No rotation metadata may be used to reinterpret a mismatched coded size.

### FPS

C005 v1 is 24 fps for all three profiles.

Require the probed effective video frame rate to equal the closed C005 fps as an exact rational
equivalent.

Examples accepted for 24 fps:

- `24/1`
- another mathematically equal rational representation

Reject:

- 23.976
- 25
- 30
- unknown/zero frame rate

C010 should parse rationals, not compare locale-dependent floating strings.

---

## RUNTIME POLICY

### Why a naive fixed target tolerance is wrong

C005 target duration is millisecond business/timeline intent.

Production video is frame-quantized.

Therefore C010 must account for the exact C005 frame plan before deciding whether final MP4 duration
is valid.

### Expected visual duration

All Production tasks in a C005 profile share one fps.

Compute with rational/integer arithmetic:

```text
expected_visual_duration =
    sum(task.frame_count) / fps
```

Do not use binary floating point as authority.

Equivalent microsecond form:

```text
expected_visual_duration_us =
    sum(frame_count) * 1_000_000 / fps
```

### C005 target quantization delta

Compute:

```text
target_runtime_us = target_runtime_ms * 1000

quantization_delta_us =
    abs(expected_visual_duration_us - target_runtime_us)
```

This is the actual expected difference introduced by the frozen frame plan, not a guessed global
allowance.

### Video-stream tolerance

Define:

```text
one_frame_us = ceil(1_000_000 / fps)
```

The final candidate video stream must satisfy both:

```text
abs(observed_video_duration_us - expected_visual_duration_us)
    <= one_frame_us
```

and:

```text
abs(observed_video_duration_us - target_runtime_us)
    <= quantization_delta_us + one_frame_us
```

This catches timestamp/frame loss while honoring legitimate C005 quantization.

### Container/AAC tolerance

C009 narration uses an exact target-duration silence timeline but AAC/MP4 packetization can introduce
small timestamp/priming differences.

Freeze C010 v1 container budget to:

```text
container_timestamp_budget_us = 100_000   # 100 ms
```

Then require:

```text
abs(observed_format_duration_us - target_runtime_us)
    <= quantization_delta_us + 100_000
```

For narrated masters additionally require:

```text
abs(observed_audio_duration_us - target_runtime_us)
    <= 100_000
```

when ffprobe exposes a usable audio duration.

If stream duration is not reported, C010 may derive bounded duration from format/packet timing using
the fixed probe implementation; it must not silently skip the runtime check.

### Cross-duration sanity

Require format duration to be consistent with the longest intended stream within the same 100 ms
container budget.

C010 must not pass a media file because only one of video/audio/container duration happens to match.

### No repair

C010 never:

- trims
- pads
- duplicates video frames
- time-stretches audio
- remuxes to make duration pass

A duration mismatch is a QA failure.

---

## AUDIO CHECKS

### narration_required = true

Require exactly one audio stream.

For G004/C009 v1 require:

- audio stream index = 1
- codec_name = `aac`
- codec profile = AAC-LC / ffprobe `LC`
- sample_rate = 48000
- channels = 1
- channel layout = mono when reported
- positive duration
- duration conforms to the runtime policy above

Do not require an exact reported AAC bitrate for PASS.

The source-controlled C009 command owns the nominal 128 kb/s policy; container bitrate reporting can
vary due AAC/container overhead and is not a reliable independent QA gate.

### narration_required = false

Require:

- zero audio streams

Do not accept an all-silence AAC track.

This makes audio presence a deterministic assertion of the product contract.

---

## UNEXPECTED STREAMS

Expected final shapes are closed.

### Narrated master

Exactly:

```text
stream 0 = one H.264/yuv420p video
stream 1 = one AAC-LC 48 kHz mono audio
```

Total stream count = 2.

### Non-narrated master or C004 fallback

Exactly:

```text
stream 0 = one H.264/yuv420p video
```

Total stream count = 1.

Reject any:

- additional video
- second audio
- subtitle
- data stream
- attachment
- attached picture
- unknown stream type

Unexpected chapters should also fail v1 unless a future profile explicitly introduces chapters.

---

## OVERLAY / CAPTION EVIDENCE WITHOUT VISUAL AI

### What deterministic C010 can prove

When overlays are required, C010 can deterministically prove the complete provenance chain:

```text
C008A2 plan digest
  -> exact authored cue ids/order/text_sha256/start/end
  -> verified C008B manifest
  -> verified C008B output SHA
  -> C009 selected_visual_sha256
  -> C009 master composition digest
  -> final master SHA
  -> Delivery Receipt
```

C010 should compare C008B cue provenance against C008A2:

- cue_id
- beat_id
- order
- text_sha256
- start_ms
- end_ms

It also verifies:

- C008B renderer/style/font profile identities are the closed supported ones
- C008B output SHA/bytes
- C009 selected visual kind/hash
- C009 manifest hash

This proves that the exact deterministic overlay stage intended by the plan is in the certified
lineage.

### What deterministic C010 cannot honestly prove

Without decoding pixels into an OCR/vision system, C010 cannot independently prove:

- the exact human-readable glyphs visibly appear
- typography is aesthetically pleasing
- the text is visually salient
- line wrapping is optimal
- a spoken phrase is semantically correct

C010 must not pretend manifest provenance is pixel OCR.

### Why OCR/AI is excluded

OCR or vision-model judgement would introduce:

- non-determinism
- model/version drift
- language/font false negatives
- network/provider risk if cloud-based
- false delivery failures unrelated to deterministic artifact integrity

Therefore no OCR/vision AI gates C010 v1.

### Captions

Current trusted-caption state is:

- captions_required=false
- captions=[]

The receipt records those facts.

C010 must not synthesize captions from narration and must not use ASR to decide whether captions
exist.

When a trusted caption contract is introduced later, the pipeline/QA profile must be versioned.

---

## AI QUALITY BOUNDARY

C010 v1 is deterministic artifact QA.

It answers:

- Is this the exact intended artifact?
- Is its cryptographic lineage intact?
- Is the MP4 structurally readable/decodable?
- Are codec/format/geometry/fps/runtime/audio streams correct?
- Is required overlay/narration provenance present?
- Is this safe to mark delivery-ready?

It does **not** answer:

- Is the video beautiful?
- Is pacing engaging?
- Is narration expressive?
- Is the overlay aesthetically placed?
- Is the content persuasive?
- Did an AI model like the result?

A later AI quality evaluator may produce an advisory score/report.

It must not replace or silently weaken C010 deterministic PASS.

AI quality evaluation is not a prerequisite for `FinalArtifactReceiptV1` in v1.

---

## DELIVERY RECEIPT CONTRACT

C010 persists a Delivery Receipt only for a complete PASS.

A QA failure does **not** produce a PASS-like receipt.

Recommended model:

```text
FinalArtifactReceiptV1
  schema_version
  qa_profile_id
  qa_input_digest
  receipt_digest
  outcome = PASS

  goal_id
  handoff_sha256
  return_sha256

  creative_job_id
  creative_package_id
  creative_package_digest

  production_job_id
  production_plan_digest
  production_package_id
  production_package_digest

  target_runtime_ms
  output_profile_id

  narration_required
  narration_plan_digest
  narration_manifest_sha256?

  overlays_required
  captions_required
  caption_overlay_plan_digest
  text_overlay_manifest_sha256?

  c004_final_manifest_sha256
  c004_final_sha256
  c004_final_bytes

  candidate_kind
  master_composition_digest?
  master_manifest_sha256?

  selected_visual_source_kind
  selected_visual_sha256

  artifact_root_profile_id
  artifact_file_name
  artifact_sha256
  artifact_bytes

  observed_media
  passed_check_ids

  verified_at
```

### Closed candidate_kind

- `c009_master_v1`
- `c004_fallback_v1`

### artifact_root_profile_id

Closed values, for example:

- `final-videos.local.v1`
- `postproduction-master.local.v1`

No absolute path is persisted in the receipt.

### observed_media

Recommended bounded structure:

```text
ObservedFinalMediaV1
  container_family = mp4
  format_duration_us

  stream_count

  video:
    index
    codec = h264
    pixel_format = yuv420p
    width
    height
    fps_numerator
    fps_denominator
    duration_us

  audio?:
    index
    codec = aac
    profile = LC
    sample_rate = 48000
    channels = 1
    duration_us?
```

Do not persist raw ffprobe JSON.

### passed_check_ids

Use a fixed ordered allowlist such as:

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

For no-overlay cases, the overlay check means "current plan proves overlay not required", not that
C010 performed visual OCR.

The list is versioned evidence, not arbitrary user text.

---

## DIGESTS

C010 uses two different digests for two different purposes.

### qa_input_digest

This is the deterministic identity of "what exactly is being certified under which policy".

Canonical input includes:

- qa_profile_id
- Goal/Creative/Production lineage ids/digests
- C005 target runtime/output profile
- C005 frame-count/fps timing facts required by the runtime policy
- C007 narration_required + narration plan digest
- C007B narration manifest SHA when required
- C008 overlays_required/captions_required + caption-overlay plan digest
- C008B manifest SHA/output SHA when required
- C004 manifest SHA/final SHA/bytes
- candidate kind
- C009 master composition digest/manifest SHA when master is required
- final candidate SHA/bytes
- fixed expected media policy ids

Excluded:

- absolute path
- mtime
- UI state
- retry count
- verified_at

Serialization:

- UTF-8
- canonical property ordering
- invariant integer/rational representation
- no raw text
- SHA-256

### receipt_digest

`receipt_digest` binds the deterministic certification content:

- qa_input_digest
- PASS outcome
- all lineage fields
- observed media facts
- passed check ids

`verified_at` is informational and excluded from `receipt_digest`.

This makes the receipt's cryptographic certification stable for the same bits/policy even if a
receipt must later be reconstructed after external deletion.

The serialized receipt must be strict and canonical enough that unknown fields are rejected.

---

## RECEIPT MANAGED ROOT

C010 v1 owns metadata only:

`%LOCALAPPDATA%\PicotooPet\PostProduction\DeliveryReceipts\v1\`

Recommended layout:

```text
DeliveryReceipts\v1\
  <bounded-job-key>\
    <qa-input-digest>\
      final-artifact-receipt.json
```

The receipt directory contains no copy of the MP4.

The video remains in its authoritative upstream root:

- C004 FinalVideos root, or
- C009 Master root

No raw narration/overlay text appears in directory names.

---

## RESTART / IDEMPOTENCY

### Fresh QA

1. assemble current trusted QA context.
2. perform lineage validation.
3. select C009 master or C004 fallback.
4. reverify managed candidate SHA/bytes.
5. derive `qa_input_digest`.
6. check exact receipt directory.
7. if absent, run fixed media probe/decode checks.
8. construct PASS receipt.
9. write to a generated temp receipt directory/file under the managed receipt root.
10. atomically promote to the exact digest directory.

C010 never modifies the candidate MP4.

### Receipt reuse

If the exact receipt directory already exists:

- require ordinary receipt file
- reject reparse escape
- enforce bounded receipt size
- strict-deserialize
- recompute receipt_digest
- require qa_input_digest equals the current expected identity
- reverify current final artifact SHA/bytes
- reverify current source manifests needed by the receipt lineage

If all match:

- return QA-ready with `Reused=true`
- full ffprobe/decode does not need to rerun because the certified artifact bits and policy identity
  are unchanged

If a future QA profile changes:

- qa_profile_id changes
- qa_input_digest changes
- a new receipt is required

### Conflict

If the exact expected receipt directory exists but is:

- incomplete
- malformed
- noncanonical
- tampered
- mismatched to candidate SHA
- mismatched to current lineage

fail closed:

`FINAL_QA_RECEIPT_CONFLICT`

Do not overwrite.

### Changed artifact/lineage

A changed master SHA, plan digest or upstream manifest hash produces a different
`qa_input_digest`.

Old receipts may remain as historical immutable evidence but are not selected for the current Goal.

### QA failure

If media QA fails before receipt promotion:

- no durable PASS receipt is written
- temp receipt state is removed best-effort
- upstream artifact remains untouched
- bounded QA failure is returned to the coordinator

C010 is a verifier, not a repairer.

---

## LOCAL CATALOG / LOOKUP

C010 does not need a mutable SQLite catalog in v1.

Use deterministic lookup.

Recommended `FinalDeliveryCatalog` behavior:

1. receive the current trusted Goal/Production/C007/C008 context.
2. derive whether current candidate must be C009 or C004.
3. derive the expected current `qa_input_digest`.
4. resolve only that exact receipt directory.
5. verify receipt + candidate again.
6. return a `VerifiedFinalArtifact` in memory.

Do not choose:

- newest receipt
- newest MP4
- highest mtime
- first directory match

This prevents a historical master/receipt from becoming current authority after plan changes.

Recommended in-memory result:

```text
VerifiedFinalArtifact
  Receipt
  FilePath
  ManifestPath
  Sha256
  Bytes
  CandidateKind
  Reused
```

`FilePath` is trusted in-memory state after managed-root verification; it is not persisted as
receipt authority.

---

## GOAL CENTER PROJECTION

C010 does not implement UI in this task, but it defines the later Goal Center state semantics.

Recommended delivery phases:

- `Idle`
- `WaitingForArtifact`
- `Verifying`
- `Ready`
- `QaFailed`

### Ready

Goal Center may expose "Open final video" only when:

- the current Goal continuation is still the same
- the exact current C010 PASS receipt resolves
- final artifact is still ordinary
- SHA/bytes still match the receipt

The open action should revalidate receipt/candidate immediately before launch.

### QA failure

On deterministic QA failure:

- `CanOpen=false`
- surface only a bounded safe failure code/message
- do not expose raw ffprobe/ffmpeg output
- do not expose absolute paths
- do not automatically open the failed artifact

### Fallback rule

If:

```text
narration_required=false
AND
overlays_required=false
```

then C004 is the correct candidate and can become QA Ready after C010 PASS.

If either is true and C009 is absent/fails QA:

- do not fall back to C004
- Goal Center remains not-ready/QA-failed

This prevents silently delivering a video missing required narration or authored overlays.

### C004 compatibility

C004 remains unchanged.

A later Goal integration slice should place C010/DeliveryCatalog in front of the current open
decision, rather than changing `FinalVideoAssemblyService` into a QA service.

---

## SECURITY

### Fixed roots only

C010 reads only from internally known roots:

- C004 FinalVideos
- C007B Narration v1
- C008B TextOverlay v1
- C009 Master v1
- C010 DeliveryReceipts v1

Every path is normalized, containment-checked and reparse-checked.

### Fixed process authority

Only fixed `ffprobe.exe` and `ffmpeg.exe` are allowed.

No shell.

No caller arguments.

No caller output path.

No media rewrite.

### Bounded parsing

Bound:

- receipt size
- upstream local manifest sizes
- ffprobe stdout
- stream count
- narration segment count
- file bytes according to existing product limits

Strict JSON parsing rejects unexpected fields for C010-owned receipts.

### Sensitive/raw data

Never persist or expose through C010 errors:

- raw narration text
- raw overlay text
- raw package manifest
- absolute paths
- raw ffprobe JSON
- raw FFmpeg stderr
- command line
- token/credentials
- stack trace

Hashes and bounded profile identities are safe provenance.

---

## ERROR MODEL

Recommended local C010 codes:

- `FINAL_QA_INPUT_INVALID`
  - malformed or unsupported QA context.

- `FINAL_QA_LINEAGE_MISMATCH`
  - Goal/Creative/Production/C004/C007/C008/C009 identities disagree.

- `FINAL_QA_MASTER_REQUIRED`
  - post-production is required but exact current C009 master is absent.

- `FINAL_QA_CAPTION_PROFILE_UNSUPPORTED`
  - nonempty/required captions reach C010 v1.

- `FINAL_QA_ARTIFACT_INVALID`
  - candidate is missing, outside its managed root, non-ordinary, escaped or has invalid bounded facts.

- `FINAL_QA_HASH_MISMATCH`
  - candidate bytes/SHA do not match trusted artifact/manifest.

- `FINAL_QA_PROBE_UNAVAILABLE`
  - fixed ffprobe/ffmpeg verifier is unavailable.

- `FINAL_QA_PROBE_FAILED`
  - fixed ffprobe structural probe failed.

- `FINAL_QA_DECODE_FAILED`
  - fixed decode-to-null validation failed.

- `FINAL_QA_CONTAINER_INVALID`

- `FINAL_QA_VIDEO_STREAM_INVALID`

- `FINAL_QA_OUTPUT_PROFILE_MISMATCH`

- `FINAL_QA_RUNTIME_MISMATCH`

- `FINAL_QA_AUDIO_STREAM_INVALID`

- `FINAL_QA_UNEXPECTED_STREAM`

- `FINAL_QA_OVERLAY_PROVENANCE_INVALID`

- `FINAL_QA_RECEIPT_CONFLICT`

Timeout should map to a bounded QA timeout code if the implementation keeps timeout distinct.

User cancellation should propagate as cancellation rather than creating a durable failure/receipt.

---

## PUBLISHING / EXPORT BOUNDARY

C010 PASS means:

"this exact local artifact is verified delivery-ready under deterministic v1 policy."

It does not mean:

- uploaded
- published
- copied to cloud
- exported to social media
- approved for a specific platform
- publicly shared

Future export/publishing must consume a valid C010 receipt and perform its own platform-specific
rules.

Publishing must not be implemented inside C010.

---

## READY_TO_IMPLEMENT

**READY_TO_IMPLEMENT: yes**

C010 v1 architecture is frozen around:

- QA the C009 master whenever narration or overlay post-production is required.
- QA C004 directly only when both are not required.
- independently reverify complete lineage and final SHA/bytes.
- require a structurally readable and fully decodable MP4.
- require H.264/yuv420p and exact C005 width/height/fps.
- use C005 frame-plan-aware runtime tolerance.
- require exactly one AAC-LC 48 kHz mono audio stream iff narration is required.
- reject every unexpected stream.
- prove overlays through deterministic plan/manifest/hash provenance, not OCR/vision AI.
- persist an immutable PASS-only Delivery Receipt.
- make Goal Center ready/open depend on the exact current valid receipt.

---

## NEXT IMPLEMENTATION SLICE

**C010A — Windows deterministic QA core + immutable receipt store, no Goal UI changes.**

Recommended scope:

1. new strict C010 receipt/media-fact contracts
2. current-lineage validator
3. candidate selector:
   - C009 master when post-production required
   - C004 fallback otherwise
4. managed-root/SHA/bytes verification
5. fixed ffprobe structural probe
6. fixed ffmpeg decode-to-null verifier
7. C005 frame-plan-aware runtime checker
8. video/audio/unexpected-stream checker
9. deterministic `qa_input_digest` + `receipt_digest`
10. DeliveryReceipts/v1 atomic PASS receipt write/reuse/conflict
11. isolated tests

Do not modify Goal Center in C010A.

After C010A is stable:

**C010B — Goal delivery projection/catalog integration**

- add master/fallback receipt-aware delivery selector
- add Verifying/Ready/QaFailed state projection
- open only a reverified receipt-qualified artifact
- keep C004 semantics unchanged

Publishing remains later.

---

## FILES OWNERSHIP

### G006 docs-only ownership

This task owns only:

`docs/architecture/video/G006_FINAL_VIDEO_QA_RECEIPT_V1.md`

No implementation code is modified by G006.

### Suggested C010A implementation ownership

Prefer new files only, for example:

- `windows/desktop/src/PicotooPet.Desktop/Services/FinalVideoQaService.cs`
- `windows/desktop/src/PicotooPet.Desktop/Services/FinalVideoQaMediaProbe.cs`
- `windows/desktop/src/PicotooPet.Desktop/Services/FinalArtifactReceiptStore.cs`
- `windows/desktop/src/PicotooPet.Desktop/Services/FinalDeliveryCatalog.cs`

If small C010-only records are needed, keep them in the new C010 file set instead of changing C004,
C007B, C008B or C009 contracts merely for convenience.

Preferred isolated tests:

`windows/desktop/tests/PicotooPet.FinalVideoQa.SmokeTests/`

Do not edit a shared smoke `Program.cs` if that creates parallel ownership overlap.

### Forbidden C010A modifications

Do not modify:

- `FinalVideoAssemblyService.cs`
- C004 manifest/artifact semantics
- C007A narration compiler/API
- C007B synthesis implementation
- C008A/A2 compiler/API
- C008B drawtext/font/glyph implementation
- C009 compositor implementation
- ProductionPackage
- `src/picotoopet_core/production/**`
- Windows Production executor
- Goal Center/UI in C010A
- Maotai/Natural Motion
- deploy/macos
- publishing/export

### Later C010B ownership

C010B should prefer new Goal delivery selector/coordinator files.

It should not repurpose C004's assembler as a QA coordinator.

---

## TESTS

### Candidate selection

- no narration/no overlay => C004 candidate
- narration only => C009 candidate required
- overlay only => C009 candidate required
- narration + overlay => C009 candidate required
- missing required C009 => fail; never C004 fallback
- stale historical master does not override current digest

### Goal/Creative/Production lineage

- Goal id mismatch rejected
- continuation creative_job_id mismatch rejected
- creative package id/digest mismatch rejected
- Production job id mismatch rejected
- Production plan digest mismatch rejected
- ProductionPackage id/digest mismatch rejected
- non-PASS package rejected
- C004 ProductionPackage lineage mismatch rejected

### C007 narration lineage

- narration plan job/package/plan mismatch rejected
- narration plan digest mismatch rejected
- narration_required=true + missing C007B artifact rejected
- C007B manifest digest mismatch rejected
- WAV tamper rejected
- narration_required=false cannot authorize final audio

### C008 overlay lineage

- overlay plan job/package/plan mismatch rejected
- overlay plan digest mismatch rejected
- overlays_required=true + missing C008B artifact rejected
- passthrough C008B rejected when overlay required
- C008B source C004 SHA mismatch rejected
- C008B output tamper rejected
- C008B manifest tamper rejected
- cue id/order/text_sha256/start/end mismatch rejected
- nonempty captions rejected by v1

### C009 lineage

- master production identity mismatch rejected
- master ProductionPlan digest mismatch rejected
- C004 source hash mismatch rejected
- overlay-required master selecting C004 visual rejected
- no-overlay master claiming C008B visual rejected
- narration manifest SHA mismatch rejected
- overlay manifest SHA mismatch rejected
- master composition digest mismatch rejected
- master output SHA/bytes tamper rejected

### Managed path/security

- correct C004 root accepted
- correct C009 root accepted
- traversal rejected
- reparse-point candidate rejected
- reparse-point manifest rejected
- arbitrary external MP4 rejected
- arbitrary caller ffprobe/ffmpeg/path field impossible
- raw absolute paths absent from receipt
- raw authored text absent from receipt/errors

### MP4 readability

- valid MP4 ffprobe PASS
- corrupt MP4 probe failure
- header-readable but corrupt packet stream fails full decode-to-null
- fixed verifier timeout bounded
- cancellation terminates process
- raw stderr not exposed

### Video stream

- exactly one video PASS
- zero video rejected
- two videos rejected
- H.264 PASS
- non-H.264 rejected
- yuv420p PASS
- other pixel format rejected
- attached picture rejected

### Output profile

For every closed C005 profile:

- exact width/height accepted
- swapped/mismatched dimensions rejected
- exact 24 fps rational accepted
- 23.976 rejected
- 25 rejected
- unknown/zero fps rejected

### Runtime

- exact expected frame duration PASS
- one-frame boundary PASS
- beyond one-frame expected-video deviation rejected
- legitimate C005 frame quantization vs target PASS
- target delta beyond quantization + one frame rejected for video stream
- container delta within quantization + 100 ms PASS
- container delta above quantization + 100 ms rejected
- use rational/integer arithmetic; no locale/double rounding dependency
- many-shot accumulated quantization handled from actual C005 frame plan

### Audio

When narration_required=true:

- one AAC-LC 48 kHz mono stream PASS
- missing audio rejected
- two audio streams rejected
- non-AAC rejected
- AAC non-LC rejected
- 44.1 kHz rejected
- stereo rejected
- audio runtime over 100 ms budget rejected

When narration_required=false:

- zero audio PASS
- silent AAC track still rejected

### Unexpected streams

- subtitle rejected
- data stream rejected
- attachment rejected
- extra unknown stream rejected
- unexpected chapter rejected

### Overlay/caption evidence

- overlay-required exact C008A2 -> C008B -> C009 chain PASS
- changed cue text_sha256 rejected
- changed cue timing rejected
- changed C008B output SHA rejected
- no OCR/vision model invoked
- no ASR invoked
- captions currently empty/optional recorded accurately

### Receipt / digest

- same deterministic inputs => same qa_input_digest
- same certification facts => same receipt_digest
- verified_at does not change receipt_digest
- artifact SHA change => qa_input_digest changes
- plan digest change => qa_input_digest changes
- upstream manifest SHA change => qa_input_digest changes
- QA profile version change => qa_input_digest changes
- PASS writes one immutable receipt
- failure writes no PASS receipt
- identical rerun reuses receipt without ffprobe/decode
- receipt tamper => conflict
- partial receipt => conflict/cleanup according to temp/final ownership
- changed digest creates a new receipt directory and does not overwrite old evidence

### Goal delivery projection

- valid current receipt => Ready/CanOpen
- missing receipt => not Ready
- QA failure => QaFailed/CanOpen=false
- open action rechecks candidate hash
- candidate tampered after PASS => Open denied / QA invalidated
- post-production-required failure never falls back to C004
- no-post-production C004 receipt can become Ready

### Regression

- C004 smoke tests green
- C005 timeline tests green
- C007A/A2 tests green
- C007B narration smoke tests green
- C008A/A2 tests green
- C008B overlay smoke tests green
- C009 master tests green
- Desktop Release build 0 errors
- no ProductionPackage mutation/regression

### Real Windows acceptance

Before final C010 PASS:

1. QA a real no-post-production C004 MP4.
2. QA a real narration-only C009 master.
3. QA a real overlay-only C009 master.
4. QA a real overlay+narration C009 master.
5. confirm ffprobe reports H.264/yuv420p and exact profile dimensions/fps.
6. confirm narrated master reports AAC-LC 48 kHz mono.
7. confirm non-narrated artifact has zero audio.
8. corrupt a copy inside an isolated test root and confirm probe/decode failure.
9. verify duration tolerance against a real multi-shot C005 plan.
10. create PASS receipt, restart, and confirm exact receipt reuse.
11. tamper artifact after PASS and confirm catalog/open revalidation fails.
12. verify receipt contains no absolute paths, raw text, commands or raw tool output.

---

## BLOCKERS

No unresolved architecture decision blocks C010.

Implementation sequencing blockers:

1. **C009 concrete master artifact/manifest must land first.**
   G004 freezes its semantics, but C010 implementation must consume the actual C009 C# types and
   manifest fields rather than duplicating them.

2. **C007B/C008B intended CI closeout should be green in the C010 integration base.**
   Both implementations are present, but at the audited latest heads their queried Windows workflow
   runs were still failing.

3. **The 100 ms AAC/container budget requires real C009 Windows acceptance evidence.**
   The budget is frozen for C010 v1 design; C009/C010 real-machine tests must prove the actual FFmpeg
   AAC mux stays inside it. If real evidence disproves it, change the versioned QA profile rather
   than silently widening tolerance inside implementation.

4. **C010B Goal Center integration follows C010A.**
   This is sequencing, not an architecture blocker: the verifier/receipt store should stabilize
   before UI/open behavior starts depending on it.

No merge/rebase/tag/release or Production lifecycle change is required for C010.
