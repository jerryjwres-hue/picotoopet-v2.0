# G004 — Post-production Master Compositor v1

Status: implementation-ready architecture for C009.

This document defines the Windows-local C009 master compositor that sits after the existing visual,
narration and text-overlay stages. It does not change Production, C004, C007B or C008B.

---

## CURRENT FACTS

### Audited implementation state

The design is based on the actual repository state, not a hypothetical pipeline.

- C004 branch: `feature/goal-final-video-assembly`
  - audited HEAD: `866af949a1c7d180a867cabf17b6bcb669b856f9`
  - `FinalVideoAssemblyService` verifies ProductionPackage outputs, resolves them under the managed
    Comfy output root, re-hashes every WebM source, concatenates them with fixed `ffmpeg.exe`,
    encodes H.264/yuv420p MP4, writes under
    `%LOCALAPPDATA%\PicotooPet\FinalVideos\`, and persists an immutable local manifest.
  - its public local artifact is `FinalVideoArtifact` with Production job/package identity,
    file/manifest path, SHA-256, bytes and reused flag.
  - its output is visual-only because the fixed assembler uses `-an`.
  - C004 already has source verification, path containment, reparse-point rejection, bounded FFmpeg
    timeout/cancel behavior, immutable artifact reuse and fail-closed conflict handling.
  - C004 must remain unchanged.

- C005 branch: `feature/video-timeline-output-profiles`
  - audited HEAD: `e82df96a7acddfb7cc2b26c023517b58716b226b`
  - `ProductionPlan.target_runtime_ms` and ordered
    `ProductionTaskPlan.target_duration_ms` are the frozen timeline authority.
  - closed output profiles are currently:
    - `video.landscape.v1` = 832x480 @ 24 fps
    - `video.vertical.v1` = 480x832 @ 24 fps
    - `video.square.v1` = 640x640 @ 24 fps
  - Production frame counts remain renderer-quantized; C009 must not reopen Creative timing.

- C007A exists in the C009 design base.
  - `NarrationPlanV1` carries:
    - production_job_id
    - creative_package_id/digest
    - production_plan_digest
    - target_runtime_ms
    - narration_required
    - ordered non-overlapping narration segments
    - per-segment start_ms/end_ms and text_sha256
  - C007A timing is derived from the C005 ProductionPlan.
  - C009 must not derive timing again from Creative floating-point durations.

- C007B branch: `feature/windows-local-narration-synthesis-v1`
  - audited HEAD: `2da47106a2fea798c460ec2bc0042d60116aa8e1`
  - Windows narration synthesis is already represented by
    `WindowsNarrationSynthesisService` and `NarrationArtifact`.
  - managed root is
    `%LOCALAPPDATA%\PicotooPet\Narration\v1\`.
  - each segment is an immutable WAV plus a local narration manifest.
  - current WAV validator accepts PCM format 1, 16-bit, mono or stereo, sample rate 8 kHz through
    48 kHz.
  - therefore C007B does **not** provide one fixed sample rate/channel layout to C009.
  - C007B records per-segment SHA-256, bytes, sample rate, channels, bits and synthesized duration.
  - current C007B allows a synthesized segment up to 250 ms beyond the C007A window before it rejects
    synthesis. C009 must not silently trim such speech.

- C008A/A2 exists in the C009 design base.
  - `CaptionOverlayPlanV1` binds the same production_job_id, creative package facts,
    production_plan_digest and target_runtime_ms.
  - current captions are empty and `captions_required=false` because no trusted transcript contract
    exists yet.
  - explicit authored `ScriptBeat.on_screen_text` becomes `overlays[]`.
  - `ShotPlan.text_reference` is not overlay authority.
  - overlay plan digest is canonical and stable.

- C008B branch: `feature/windows-caption-overlay-render-v1`
  - audited HEAD: `0a853d03ab5dbcf32e62a318c87beed45107680d`
  - at this audited HEAD the implementation branch contains the C008B implementation task contract,
    while the shipping renderer files have not yet landed.
  - the C008B contract is nevertheless explicit:
    - input is verified C004 `FinalVideoArtifact` + authenticated C008A2 plan
    - backend is fixed FFmpeg drawtext
    - output is H.264/yuv420p MP4
    - output has no audio
    - managed root is
      `%LOCALAPPDATA%\PicotooPet\PostProduction\TextOverlay\v1\`
    - manifest binds source C004 SHA, overlay-plan digest, output SHA/bytes and resolved font
      identities
    - empty overlay plan is a passthrough, not an unnecessary re-encode.

- S004 Windows compatibility probe:
  - real Windows FFmpeg 9.0 full build passed drawtext, libfreetype, H.264 and ffprobe validation.
  - English Arial and Chinese Microsoft YaHei paths were proven through the closed font policy.
  - cancellation and timeout were bounded.
  - S004 explicitly recommends drawtext for C008B/C009 text rendering.

### Existing safety primitives worth reusing

C009 should reuse the existing path/file discipline exposed by
`ProductionLocalEnvironment`, including:

- `ResolveUnderRoot`
- `AssertNoLinkEscape`
- `IsOrdinaryFile`
- `Sha256FileAsync`

C009 must not add another Production lifecycle or mutate ProductionPackage.

---

## ARCHITECTURE DECISION

### v1 chooses **A: consume the verified C008B derived MP4, then mux narration**

C009 v1 must **not** independently re-run the C008B drawtext primitive.

The selected graph is:

```text
ProductionPackage
      |
      v
C004 verified visual-only H.264 MP4
      |
      +------------------------------+
      |                              |
      | overlays_required=false      | overlays_required=true
      |                              |
      v                              v
C004 MP4                       C008B verified overlay MP4
                                      |
                                      +---- binds C004 source SHA
                                      +---- binds CaptionOverlayPlan digest
                                      +---- fixed drawtext/font policy
      |                              |
      +---------------+--------------+
                      |
                      v
              selected visual MP4
                      |
       C007B narration WAV artifacts
                      |
                      v
        C009 fixed audio timeline + mux
                      |
                      v
          mastered H.264/AAC MP4
```

### Why A is preferred over B

The key point is that muxing narration does **not** require another H.264 encode.

C009 will use:

```text
-c:v copy
```

for every FFmpeg master operation.

Therefore, when overlays exist:

- C004 performs its existing H.264 visual assembly.
- C008B performs the one required overlay burn-in H.264 encode.
- C009 copies the already-encoded H.264 video stream and encodes only the narration audio.

There is no second C009 video encode.

That removes the principal quality argument for option B.

### Quality

Option A and option B have the same number of post-C004 lossy video encodes in the overlay case:

- A: C008B burns overlay once; C009 stream-copies video.
- B: C009 burns overlay once while muxing audio.

A therefore does not introduce additional visual generation loss when `-c:v copy` is enforced.

C009 tests must fail if the final mux path specifies `libx264`, `h264_nvenc`, another video encoder,
a video filter, scale, fps conversion or pixel-format conversion.

### Restart safety

A is materially safer for v1:

- C008B can finish and persist a verified overlay artifact once.
- a later narration synthesis or mux failure does not force overlay re-render.
- C009 restart can reuse both C008B and C007B immutable artifacts.
- C008B font resolution/glyph validation remains isolated from audio failures.
- C007B TTS failures remain isolated from overlay rendering.
- partial C009 cleanup never touches C004/C007B/C008B durable artifacts.

### Minimal duplicate construction

A avoids reimplementing or extracting all of the following into C009:

- Windows font candidate selection
- SFNT cmap glyph coverage
- drawtext textfile preparation
- drawtext timing expression generation
- overlay style geometry
- overlay-specific timeout/error mapping
- C008B source-manifest semantics

Those are already C008B responsibilities.

### Operational tradeoff

A keeps one intermediate derived MP4 when overlays exist.

That costs local disk I/O/storage, but the intermediate already exists by design and provides a
valuable restart/provenance boundary. For v1, this is a better trade than coupling C009 directly to
overlay internals.

### Future optimization

A future compositor profile may collapse C008B + C009 into one FFmpeg process if profiling shows
that the intermediate file is a meaningful bottleneck.

That would require a deliberately versioned shared overlay primitive.

It is not the C009 v1 architecture.

---

## MASTER INPUT CONTRACT

C009 is a local Windows service. Its input is a set of existing trusted typed artifacts and plan
responses, not a public request carrying renderer authority.

Conceptually:

```text
MasterCompositionInputV1
  c004_source: FinalVideoArtifact
  narration_plan: NarrationPlanResponseRecord
  narration_artifact: NarrationArtifact?       # required iff narration_required
  overlay_plan: CaptionOverlayPlanResponseRecord
  overlay_artifact: CaptionOverlayArtifact?    # required iff overlays_required
```

The exact C008B record type should use the name that lands with C008B; C009 must not invent a second
overlay artifact shape if C008B already publishes one.

### Prohibited input authority

The C009 input contract must not contain caller-supplied:

- source path
- output path
- executable path
- FFmpeg command
- filter string
- codec
- bitrate
- sample rate
- channel count
- font path
- drawtext expression
- URL
- provider/model
- shell command
- arbitrary metadata

Trusted file paths come only from verified C004/C007B/C008B artifact objects.

### Cross-source identity validation

Before any output or temp directory is created, C009 must verify:

1. C004 source `ProductionJobId` equals the requested production job.
2. C007 narration-plan production_job_id equals C004 production job.
3. C008 overlay-plan production_job_id equals C004 production job.
4. C007 and C008 creative_package_id are equal.
5. C007 and C008 creative_package_digest are equal.
6. C007 and C008 production_plan_digest are equal.
7. C007 and C008 target_runtime_ms are equal.
8. C008 output_profile_id is one of the closed C005 profiles.
9. current v1 has `captions_required=false` and `captions=[]`.
   - if a future trusted-caption plan becomes populated before the compositor profile is upgraded,
     fail closed rather than silently ignore captions.
10. if `overlays_required=true`:
    - C008B artifact is required.
    - it must not be a passthrough.
    - its production_job_id must match.
    - its source production_package_id/digest must match C004.
    - its source_final_sha256 must equal the reverified C004 SHA.
    - its caption_overlay_plan_digest must equal the authenticated C008 digest.
11. if `overlays_required=false`:
    - C009 selects C004 directly.
    - C008B output is not required.
    - an optional C008B passthrough may exist, but it is not master authority.
12. if `narration_required=true`:
    - a C007B narration artifact is required.
    - its narration manifest must bind the exact C007 narration_plan_digest.
    - every planned segment must have exactly one matching WAV entry.
13. if `narration_required=false`:
    - C009 must create no audio stream.
    - narration WAVs are not required.
    - a pre-existing empty C007B manifest may be verified for provenance but must not cause audio to
      appear.

### Selected visual source

C009 derives one and only one visual source:

```text
if overlays_required:
    visual = verified C008B derived MP4
else:
    visual = verified C004 FinalVideoArtifact MP4
```

C009 never lets a caller choose between those sources.

### Source SHA re-verification

C009 must independently reverify the selected inputs immediately before composition.

C004 source:

- ordinary file
- under `%LOCALAPPDATA%\PicotooPet\FinalVideos\`
- no reparse/symlink escape
- bytes match artifact
- SHA-256 matches artifact

C008B visual source when required:

- ordinary file
- under `%LOCALAPPDATA%\PicotooPet\PostProduction\TextOverlay\v1\`
- no reparse/symlink escape
- output bytes/SHA match the C008B manifest/artifact
- C008B manifest is itself bounded and matches the current C004 source + C008 plan

C007B narration source when required:

- narration manifest is an ordinary bounded file under
  `%LOCALAPPDATA%\PicotooPet\Narration\v1\`
- each WAV is an ordinary file in the expected narration job directory
- no reparse/symlink escape
- WAV file name is managed/generated, never caller-selected
- bytes/SHA match the narration manifest
- WAV is reparsed before mux; do not trust only the recorded media facts

---

## MASTER ARTIFACT CONTRACT

C009 owns a local derived artifact, not a Core database record.

Recommended in-memory contract:

```text
MasterVideoArtifact
  ProductionJobId
  ProductionPackageId
  ProductionPackageDigest
  ProductionPlanDigest
  MasterCompositionDigest
  OutputProfileId
  TargetRuntimeMs
  FilePath
  ManifestPath
  Sha256
  Bytes
  HasNarration
  VisualSourceKind
  Reused
```

`VisualSourceKind` is a closed enum:

- `c004_final_v1`
- `c008b_overlay_v1`

### When C009 is required

Define:

```text
postproduction_required = narration_required || overlays_required
```

If both are false:

- C009 is not required.
- do not copy or remux C004 merely to rename it.
- Goal Center/C010 later use the verified C004 artifact as the no-postproduction fallback.

If overlays are required but narration is not:

- C009 still produces a master artifact under the master root.
- it may use a verified byte-copy of the C008B visual MP4 into the master temp directory.
- no FFmpeg invocation is necessary.
- output SHA must equal selected visual SHA.
- there is no audio stream.

If narration is required:

- C009 runs the fixed master mux.
- video is stream-copied.
- audio is encoded to the fixed master audio profile.

This gives one stable master-root artifact for every job that actually required post-production.

### Managed root

C009 v1 owns:

```text
%LOCALAPPDATA%\PicotooPet\PostProduction\Master\v1\
```

Recommended durable layout:

```text
Master\v1\
  <bounded-job-key>\
    <master-composition-digest>\
      master.mp4
      master-manifest.json
```

The job key should be derived from a bounded sanitized production_job_id plus a hash suffix, following
the same non-authoritative-name approach used by C007B.

No raw text belongs in a path.

### Directory-level atomic promotion

C009 should improve two-file restart safety by staging output and manifest together.

Recommended flow:

1. derive final digest directory.
2. if it exists, verify/reuse or conflict.
3. create a sibling generated temporary directory.
4. write `master.mp4`.
5. verify output bytes/hash.
6. write `master-manifest.json`.
7. close all handles.
8. atomically `Directory.Move(tempDirectory, finalDigestDirectory)` on the same volume.

A process crash before step 8 leaves only a generated temporary directory, not a half-promoted
output/manifest pair.

On restart, stale generated temporary directories may be safely removed only if they are under the
C009 root and match the C009-owned temp naming policy.

### Immutable master manifest

Recommended `master-manifest.json` fields:

- schema_version = `1.0`
- production_job_id
- production_package_id
- production_package_digest
- creative_package_id
- creative_package_digest
- production_plan_digest
- target_runtime_ms
- output_profile_id
- compositor_profile_id = `postproduction.master.windows.v1`
- selected_visual_source_kind
- c004_source_final_sha256
- c004_source_final_bytes
- selected_visual_sha256
- selected_visual_bytes
- c008b_manifest_sha256 nullable
- caption_overlay_plan_digest
- overlays_required
- narration_plan_digest
- narration_required
- c007b_manifest_sha256 nullable
- ordered narration segment provenance when narration is present:
  - segment_id
  - beat_id
  - order
  - text_sha256
  - start_ms
  - end_ms
  - wav_sha256
  - wav_bytes
  - source_sample_rate
  - source_channels
  - source_bits
  - exact source sample frames or equivalent exact duration fact
- master_audio_profile_id
- master_video_policy_id
- master_composition_digest
- output_file_name
- output_sha256
- output_bytes
- has_audio
- created_at

The manifest must not persist:

- raw narration text
- raw overlay text
- absolute source/output paths
- font paths
- raw FFmpeg arguments
- raw filter graph
- raw stderr
- raw Core responses
- credentials/tokens

---

## DATA FLOW

### Case 1 — no narration, no overlay

```text
C004 FinalVideoArtifact
C007 narration_required=false
C008 overlays_required=false
        |
        v
C009 NOT REQUIRED
        |
        v
C004 remains delivery fallback
```

No C009 file is created.

### Case 2 — overlay only

```text
C004 FinalVideoArtifact
        +
C008A2 overlay plan
        |
        v
C008B derived H.264 MP4
        |
        v
C009 verifies lineage
        |
        v
verified byte-copy -> Master/v1/.../master.mp4
(no audio)
```

No additional video encoding occurs.

### Case 3 — narration only

```text
C004 H.264 MP4 --------------------------+
                                         |
C007A narration plan -> C007B WAVs ------+--> C009 audio timeline + mux
                                                  |
                                                  +-- video: stream copy
                                                  +-- audio: AAC encode
                                                  v
                                               master.mp4
```

### Case 4 — overlay + narration

```text
C004 MP4 -> C008B overlay H.264 MP4 ------+
                                          |
C007A narration plan -> C007B WAVs -------+--> C009 audio timeline + mux
                                                   |
                                                   +-- video: stream copy
                                                   +-- audio: AAC encode
                                                   v
                                                master.mp4
```

C009 does not rebuild the overlay.

---

## FFmpeg BOUNDARY

### Fixed executable authority

When narration is present, C009 may execute only:

```text
ffmpeg.exe
```

through `ProcessStartInfo` with:

- `UseShellExecute=false`
- `CreateNoWindow=true`
- `ArgumentList`
- redirected stdout/stderr drained but never persisted raw
- fixed timeout
- process-tree termination on timeout/cancel

No `cmd.exe`, PowerShell, shell expansion or caller command line is allowed.

### Fixed video policy

C009 v1 video policy id:

```text
video.h264.stream-copy.v1
```

Required semantics:

- map exactly one selected video stream
- `-c:v copy`
- no video filter graph
- no scale
- no fps conversion
- no pixel-format conversion
- no overlay filter
- no video encoder
- no user-selected stream index
- strip or replace unneeded metadata in a fixed way when compatible with stream-copy
- output MP4 with `+faststart`

This policy is the architectural guarantee that option A does not add another lossy video encode.

### Fixed audio policy

C009 v1 final audio profile:

```text
audio.aac-lc.48k.mono.128k.v1
```

Fixed output properties:

- codec: AAC-LC
- sample rate: 48,000 Hz
- channels: 1 mono
- bitrate: 128 kb/s
- one narration audio stream
- no background music
- no sound-effects mix
- no caller gain
- no caller pan
- no caller loudness target
- no time-stretch
- no pitch shift

C009 source WAVs may be 8–48 kHz and mono/stereo because C007B currently permits those.

C009 normalizes them internally to the fixed master format before AAC encoding.

### Fixed mux shape

Narrated master:

```text
stream 0: H.264 video copied from selected visual
stream 1: AAC-LC 48 kHz mono narration
```

Non-narrated master:

```text
stream 0: H.264 video only
```

No subtitle/data/attachment/extra audio streams are intentionally created.

### Internally-authored audio filter graph only

The only complex filter authority in C009 is audio timing.

It must be generated from bounded integer timing plus verified WAV inputs.

A suitable v1 model is:

1. create an internal 48 kHz mono silence base with exact C005 target duration.
2. normalize each verified WAV to 48 kHz mono.
3. delay each normalized segment by exactly its C007A `start_ms`.
4. combine silence + delayed non-overlapping narration segments with a fixed internal mixer whose
   normalization/gain behavior is disabled/fixed.
5. encode the resulting one audio stream as AAC-LC.

Because C007A segments are non-overlapping, this is placement over silence, not creative mixing.

Caller-provided filter syntax is forbidden.

---

## AUDIO TIMELINE RULES

### Timeline authority

C007A segment `start_ms/end_ms`, which were derived from C005 ProductionPlan, are the sole narration
placement authority.

C009 must not:

- infer timing from word count
- infer timing from WAV file name
- recompute timing from Creative beat duration
- shift a segment to make it fit
- overlap adjacent segments
- stretch speech
- truncate speech
- invent narration

### Exact WAV duration preflight

C009 must reparse each WAV and determine exact PCM sample-frame count.

For each segment:

```text
window_duration = end_ms - start_ms
source_duration = sample_frames / source_sample_rate
```

The exact source duration must not exceed the plan window.

Do not rely only on C007B's current integer `SynthesizedDurationMs`, because it is rounded/floored and
C007B currently permits a +250 ms synthesis tolerance.

If source speech is longer than its planned window:

```text
MASTER_NARRATION_SEGMENT_TOO_LONG
```

and composition stops before FFmpeg.

No `atrim`, `-t` or `-shortest` rule may be used as a hidden way to make overlong speech pass.

### Segment shorter than its window

A short narration segment starts exactly at `start_ms`.

After its actual samples end, the remainder of its plan window is silence.

C009 does not extend the spoken waveform to `end_ms`.

### Silence gaps

Silence is deterministic.

The silence base covers:

- time 0 to the first segment start
- any gap between the actual end of one spoken waveform and the next planned start
- unused remainder inside a segment's C007A beat window
- tail from the last spoken waveform to `target_runtime_ms`

There is no room-tone generation or learned ambience in v1.

### No narration

When `narration_required=false`:

- C009 adds no audio track.
- it must not generate an all-silence AAC track.
- C010 can therefore use audio-stream presence as a deterministic check against
  `narration_required`.

### Runtime boundary

The audio timeline authority is `target_runtime_ms`.

C009 does not modify the selected visual stream to force it to that duration.

The selected C004/C008B visual artifact is immutable and video is stream-copied.

Any small physical-duration difference caused upstream by frame quantization remains visible to C010,
which should apply an explicit bounded duration tolerance.

C009 must not hide an upstream duration mismatch by re-encoding, duplicating frames or silently
trimming visual content.

---

## OVERLAY INTEGRATION RULES

### C008B is visual post-production authority

If `overlays_required=true`, C009 must use the verified C008B derived visual artifact.

It must not:

- rerun drawtext
- reopen the font policy
- parse fonts
- re-check glyphs independently as a second overlay engine
- regenerate cue text files
- rebuild overlay geometry
- alter C008A timing
- consume raw `on_screen_text` directly

This keeps one overlay implementation.

### C008B provenance required

C009 needs enough C008B artifact metadata to verify:

- production_job_id
- source production_package_id/digest
- source_final_sha256
- caption_overlay_plan_digest
- output_profile_id
- output SHA-256/bytes
- passthrough flag
- immutable manifest identity

The C008B manifest hash should be captured by C009 as upstream provenance.

### Empty overlays

If `overlays_required=false` and `overlays=[]`:

- use C004 directly.
- do not require C008B to have emitted a local manifest.
- do not invoke drawtext.
- do not create an overlay-only intermediate.

### Captions

Current C008A produces no captions without a trusted transcript.

C009 v1 therefore expects:

```text
captions_required=false
captions=[]
```

C009 does not turn narration text into captions.

When a future caption source exists, the text-rendering contract must first be versioned so that C008B
is explicitly authoritative for those caption cues. C009 should then continue to consume the verified
visual artifact rather than becoming a second caption renderer.

---

## DIGEST IDENTITY

### Master composition identity

Define a strict canonical identity document separate from the local manifest timestamp.

Conceptually:

```text
MasterCompositionIdentityV1
  schema_version
  compositor_profile_id
  production_job_id
  production_package_id
  production_package_digest
  creative_package_id
  creative_package_digest
  production_plan_digest
  target_runtime_ms
  output_profile_id

  c004_source_final_sha256
  c004_source_final_bytes

  selected_visual_source_kind
  selected_visual_sha256
  selected_visual_bytes

  caption_overlay_plan_digest
  overlays_required
  c008b_manifest_sha256?     # required when overlays_required

  narration_plan_digest
  narration_required
  c007b_manifest_sha256?     # required when narration_required
  narration_segments[]       # ids/timing/text hash/WAV hash+bytes+media facts

  master_video_policy_id
  master_audio_profile_id
```

Canonical serialization:

- UTF-8 JSON
- sorted property names
- compact separators
- invariant numbers
- no timestamp
- no path
- no raw text

`master_composition_digest` is SHA-256 of that canonical document.

### What changes the digest

At minimum, the digest changes if any of these changes:

- C004 source SHA
- ProductionPackage digest
- ProductionPlan digest
- target runtime/output profile
- overlay-plan digest
- C008B derived visual SHA/manifest identity
- narration-plan digest
- any narration WAV SHA/bytes/media fact
- compositor profile
- audio/video policy

### What does not change the digest

- created_at
- local absolute path
- temporary directory name
- UI state
- Goal Center state
- retry count

---

## RESTART/IDEMPOTENCY

### Deterministic lookup

For a job requiring post-production:

1. validate all current upstream facts.
2. derive `master_composition_digest`.
3. derive deterministic final digest directory.
4. inspect only that exact directory.

### Reuse

If the exact final directory exists:

- reject reparse escape
- require exactly the expected bounded files
- parse strict manifest
- recompute master output SHA/bytes
- reverify current upstream C004/C007B/C008B hashes
- require complete identity equality
- return `Reused=true`

No FFmpeg call occurs.

### Conflict

If the exact final directory exists but:

- manifest is missing
- output is missing
- unexpected durable entries exist
- manifest identity differs
- output SHA/bytes differ
- current upstream source differs
- path safety fails

then fail closed:

```text
MASTER_ARTIFACT_CONFLICT
```

Do not overwrite.

### Changed expected digest

A changed input identity produces a different digest directory.

C009 does not overwrite an older master artifact.

The caller/catalog selects only the master matching the currently verified input graph.

### Partial failure

All work is performed in a generated temporary directory under the C009 managed root.

On:

- FFmpeg nonzero exit
- timeout
- user cancellation
- hash mismatch
- WAV validation failure
- write failure

C009:

- kills the FFmpeg process tree when applicable
- closes streams
- deletes the C009-owned temporary directory best-effort
- leaves C004/C007B/C008B artifacts untouched
- does not promote a master manifest or master MP4

Cancellation should propagate as cancellation, not be persisted as an immutable failed artifact.

---

## SECURITY

C009 is a derived-media service, not an execution API.

### Trust boundary

Allowed authority:

- Core-authored C007A/C008A2 plans
- verified C004 artifact
- verified C007B artifact
- verified C008B artifact
- source-controlled compositor profiles

Not authority:

- UI strings
- Creative raw text
- arbitrary filesystem path
- arbitrary executable
- arbitrary filter
- arbitrary codec/profile
- arbitrary font
- raw package JSON supplied by a caller

### Path safety

Every file operation must:

- derive roots internally
- use full-path normalization
- require containment
- reject reparse-point escape
- require ordinary files
- bound manifest/WAV/output size
- never follow a caller path outside managed roots

### Process safety

- fixed `ffmpeg.exe`
- no shell
- ArgumentList only
- bounded input count: narration plan max 60 segments
- bounded total narration bytes
- bounded timeout
- process tree killed on timeout/cancel
- stdout/stderr drained
- raw stderr never exposed to UI or manifest

### Text privacy

C009 never needs raw overlay text.

It sees narration WAVs plus narration-plan metadata. If the narration plan object containing text is in
memory for identity validation, raw text must never be logged or persisted by C009.

Master manifest stores only narration `text_sha256`.

---

## ERROR MODEL

Recommended bounded local codes:

- `MASTER_NOT_REQUIRED`
  - typed non-failure disposition when both narration and overlays are absent; caller uses C004.
- `MASTER_INPUT_INVALID`
  - malformed/unsupported plan or artifact contract.
- `MASTER_SOURCE_IDENTITY_MISMATCH`
  - C004/C007/C008 job/package/plan lineage does not agree.
- `MASTER_VISUAL_SOURCE_INVALID`
  - selected C004/C008B file or manifest fails path/hash/bytes verification.
- `MASTER_OVERLAY_ARTIFACT_REQUIRED`
  - overlays are required but no valid C008B derived artifact exists.
- `MASTER_CAPTION_PROFILE_UNSUPPORTED`
  - nonempty/required captions reach this v1 before the visual renderer contract is upgraded.
- `MASTER_NARRATION_ARTIFACT_REQUIRED`
  - narration is required but no valid C007B artifact exists.
- `MASTER_NARRATION_SOURCE_INVALID`
  - narration manifest/WAV identity, SHA or PCM structure is invalid.
- `MASTER_NARRATION_SEGMENT_TOO_LONG`
  - actual speech exceeds its C007A window.
- `MASTER_AUDIO_TIMELINE_INVALID`
  - ordering/timing cannot produce the closed target timeline.
- `MASTER_FFMPEG_UNAVAILABLE`
- `MASTER_FFMPEG_FAILED`
- `MASTER_FFMPEG_TIMEOUT`
- `MASTER_OUTPUT_INVALID`
- `MASTER_ARTIFACT_CONFLICT`

Errors must never include:

- narration text
- overlay text
- absolute path
- raw FFmpeg filter graph
- raw stderr
- raw manifest
- token/credential
- stack trace in user-visible status

---

## GOAL CENTER INTEGRATION

C009 must not modify C004.

A later Goal Center slice should add a separate master-first projection instead of changing
`FinalVideoAssemblyService` semantics.

### Selection rule

For a production-ready Goal:

1. determine whether post-production is required from C007/C008 plans.
2. if a valid C009 master exists for the current input digest:
   - present/open C009 master.
3. if no post-production is required:
   - use the existing C004 final video as fallback.
4. if post-production is required but the expected C009 master is missing or failed:
   - do **not** silently fall back to un-narrated/un-overlaid C004.
   - surface post-production not-ready/failure.
5. never choose an older master whose digest does not match current verified inputs.

### Why fallback is conditional

C004 fallback is semantically correct only when:

```text
narration_required == false
AND
overlays_required == false
```

If authored overlay or required narration exists, opening C004 would silently omit required content.

### Integration shape

Preferred later addition:

- a new `GoalMasteredVideoCoordinator` or `GoalDeliveryArtifactSelector`
- a new delivery-candidate abstraction for Goal Center
- existing `GoalFinalVideoCoordinator` remains the C004 assembly/fallback implementation

Do not retrofit C004's `FinalVideoArtifact` to pretend it is a C009 master.

---

## C010 QA INTERFACE

C009 should hand C010 a strict trusted candidate, not make C010 rediscover the graph from arbitrary
paths.

Recommended internal projection:

```text
FinalDeliveryCandidateV1
  kind: master_v1 | c004_fallback
  production_job_id
  production_package_id
  production_package_digest
  production_plan_digest
  target_runtime_ms
  output_profile_id
  narration_required
  overlays_required
  narration_plan_digest
  caption_overlay_plan_digest
  file_path                  # trusted in-memory local path only
  manifest_path              # trusted in-memory local path only
  file_sha256
  file_bytes
  master_composition_digest? # master only
```

### C010 selection rule

- if post-production was required, C010 QA must target the C009 master.
- if neither narration nor overlays were required, C010 may QA the verified C004 fallback.
- C010 must never silently QA C004 when required post-production is missing.

### C010 deterministic checks enabled by C009

C010 can validate:

- ordinary managed file
- SHA/bytes
- MP4 readability
- exactly one H.264 video stream
- yuv420p
- C005 width/height/fps
- duration vs target runtime with a versioned explicit tolerance
- exactly one AAC audio stream iff narration_required=true
- 48 kHz mono when narration is required
- no audio stream when narration_required=false
- no unexpected data/subtitle/attachment streams
- master manifest identity and digest chain

For overlay/caption presence, deterministic v1 QA should validate provenance:

- overlays_required implies selected_visual_source_kind=`c008b_overlay_v1`
- C008B manifest digest is bound into C009
- C008B manifest binds the exact CaptionOverlayPlan digest

C010 should **not** try to infer visible text pixels with fragile visual AI in deterministic v1.

AI aesthetic/semantic quality evaluation belongs in a later non-deterministic layer and must not gate
the deterministic C010 receipt.

---

## FILE OWNERSHIP

### G004 docs-only ownership

This task owns only:

`docs/architecture/video/G004_POSTPRODUCTION_COMPOSITOR_V1.md`

No implementation file is modified by G004.

### Suggested C009 implementation ownership

Prefer new files only, for example:

- `windows/desktop/src/PicotooPet.Desktop/Services/PostProductionMasterCompositorService.cs`
- `windows/desktop/src/PicotooPet.Desktop/Services/PostProductionMasterAudioTimeline.cs`
- `windows/desktop/src/PicotooPet.Desktop/Services/PostProductionMasterProcessRunner.cs`
- `windows/desktop/src/PicotooPet.Desktop/Services/PostProductionMasterArtifactCatalog.cs`

Optional local contracts may remain in the same C009 file set rather than modifying existing C007/C008
contracts.

Preferred isolated tests:

- `windows/desktop/tests/PicotooPet.PostProductionMaster.SmokeTests/`

Do not add the smoke project to a shared solution if that creates parallel-branch overlap; shipping
Desktop source files are auto-included today.

### Forbidden C009 modifications

C009 should not modify:

- `FinalVideoAssemblyService.cs`
- C004 final-video manifest semantics
- ProductionPackage
- `src/picotoopet_core/production/**`
- C006A/C006B
- C007A narration compiler
- C007B synthesis implementation
- C008A/A2 compiler/API semantics
- C008B drawtext/font/glyph implementation
- Windows Production execution files
- Goal Center/UI in the core C009 slice
- Maotai/Natural Motion
- deploy/macos
- publishing/export

A separate later Goal integration slice may add new selector/coordinator files.

---

## TEST MATRIX

### Pure contract / identity

- same complete input graph => same master_composition_digest
- timestamp/path changes do not change digest
- C004 source SHA change => digest changes
- ProductionPlan digest change => digest changes
- narration plan digest change => digest changes
- any WAV SHA change => digest changes
- overlay plan digest change => digest changes
- C008B output SHA/manifest digest change => digest changes
- unknown audio/video profile rejected
- populated captions rejected by current v1 profile
- raw command/filter/path fields cannot enter the input contract

### Identity mismatch

- C007/C008 production_job_id mismatch rejected
- C007/C008 creative package mismatch rejected
- C007/C008 production plan digest mismatch rejected
- target_runtime mismatch rejected
- C008B source-final SHA not equal C004 SHA rejected
- C008B overlay-plan digest mismatch rejected
- C007B narration-plan digest mismatch rejected

### Four pipeline modes

- no narration + no overlay => typed not-required/C004 fallback; no C009 artifact
- overlay only => C008B selected, C009 master has no audio, video bytes can be copied without encode
- narration only => C004 selected, H.264 stream copy + AAC narration
- overlay + narration => C008B selected, H.264 stream copy + AAC narration

### Audio timeline

- leading silence
- middle gap
- trailing silence
- segment starting at 0
- segment ending exactly at target
- short segment leaves silence to next planned start
- multiple ordered non-overlapping segments
- source mono 8 kHz -> fixed 48 kHz mono output
- source stereo 48 kHz -> fixed 48 kHz mono output
- source PCM format other than accepted C007B facts rejected
- overlong segment by 1 sample rejected
- overlong segment inside C007B's current 250 ms tolerance still rejected by C009
- no narration => no silence-only audio stream

### FFmpeg authority

- executable is exactly `ffmpeg.exe`
- shell disabled
- video codec is exactly copy
- no video filter
- no video encoder flag
- no caller filter input
- no caller output path
- fixed AAC-LC/48k/mono/128k
- bounded timeout
- cancel kills process tree
- stderr never reaches manifest/user-facing error

### Source safety

- valid C004 root accepted
- C004 hash tamper rejected
- C008B hash tamper rejected
- narration manifest tamper rejected
- WAV tamper rejected
- path traversal rejected
- reparse source rejected
- arbitrary external MP4/WAV rejected

### Artifact/restart

- fresh render creates one immutable digest directory
- same inputs reuse without FFmpeg
- tampered master output conflicts
- tampered master manifest conflicts
- final directory with missing pair conflicts
- stale C009-owned temp directory is cleaned
- cancellation leaves no durable final directory
- FFmpeg failure leaves no durable final directory
- changed digest does not overwrite old artifact
- manifest contains no raw text/absolute paths/filter/stderr

### Regression

- C004 smoke tests remain green
- C007A/A2 Core tests remain green
- C007B narration smoke tests remain green
- C008A/A2 Core tests remain green
- C008B overlay smoke/real-Windows tests remain green
- Desktop Release build 0 errors
- no Production regression

### Real Windows acceptance

Before C009 PASS on a real Windows host:

1. create narration-only master from a real C004 MP4 and real C007B WAV.
2. create overlay+narration master from a real C008B MP4 and C007B WAV.
3. verify with ffprobe that video codec is H.264 and was stream-copied rather than re-encoded.
4. verify AAC-LC 48 kHz mono.
5. listen for correct start timing and silence gaps.
6. verify no speech truncation.
7. cancel an in-flight mux and confirm bounded termination/temp cleanup.
8. rerun identical input and confirm artifact reuse.
9. tamper one WAV and confirm fail closed.
10. tamper selected visual and confirm fail closed.

---

## IMPLEMENTATION SLICES

### C009A — Master contracts, identity and source validation

Recommended scope:

- new C009 local contract/service files only
- cross-source identity validation
- selected-visual decision
- C004/C007B/C008B managed source verification
- exact WAV parser/sample-duration validation
- canonical master composition digest
- deterministic managed root/digest directory
- manifest schema
- pure tests with fake artifacts/process boundary

Do not execute FFmpeg yet.

This slice can be developed once the concrete C008B artifact/manifest type has landed.

### C009B — Fixed audio timeline + stream-copy master mux

Recommended scope:

- fixed internally-authored audio filter builder
- fixed `ffmpeg.exe` runner
- `-c:v copy` hard invariant
- AAC-LC 48 kHz mono 128k output
- timeout/cancel cleanup
- overlay-only byte-copy master path
- directory-level atomic promotion
- reuse/conflict behavior
- isolated Windows smoke tests

No drawtext code belongs in this slice.

### C009C — Goal delivery selection

Separate after C009 artifact stability:

- add a master-first Goal delivery selector/coordinator
- prefer exact C009 master when post-production is required
- use C004 fallback only when narration and overlays are both not required
- do not modify C004 assembly semantics
- no publishing

### C010 handoff

After C009:

- consume `FinalDeliveryCandidateV1`
- implement deterministic ffprobe/media QA
- issue immutable delivery receipt
- do not add AI visual quality gating to deterministic v1

---

## AGENT RECOMMENDATION

### Primary C009 implementation

Use a strong code-oriented agent such as Codex/GPT for C009A because this slice is dominated by:

- strict invariants
- digest design
- path/security validation
- immutable artifact state
- failure/restart test matrices

### Windows media acceptance

Use the Windows-capable implementation agent that is already handling C007B/C008B for C009B real-machine
acceptance, because it can verify:

- actual FFmpeg process behavior
- AAC encoder availability
- Windows path/reparse behavior
- cancellation
- output playback/ffprobe facts

The agents should not work on the same C009 files concurrently.

Recommended sequence:

```text
C008B artifact contract lands
        ->
C009A contract/source layer
        ->
C009B Windows mux + real-machine acceptance
        ->
C009C Goal selector
        ->
C010 QA/receipt
```

---

## READY_TO_IMPLEMENT

**READY_TO_IMPLEMENT: yes**

The v1 architecture decision is frozen:

**C009 consumes C008B's verified derived visual artifact when overlays exist and uses H.264 stream-copy
while muxing narration. It does not reuse drawtext directly.**

This preserves visual quality, maximizes restart reuse and avoids duplicate overlay/security
implementation.

---

## BLOCKERS

No architecture blocker remains.

Implementation sequencing blockers:

1. **C008B concrete artifact type/manifest must land first.**
   At audited HEAD `0a853d03ab5dbcf32e62a318c87beed45107680d`, the C008B branch still contains only
   its implementation task contract; C009 should not guess the final C008B C# type names.

2. **C007B and C008B must be present together in the C009 integration base.**
   C007B implementation is currently on its own branch and C008B is being implemented independently.

3. **C007B's +250 ms synthesis tolerance needs an explicit C009 integration test.**
   C009 intentionally rejects any actual WAV duration beyond its C007A window rather than trimming
   speech. This is not an architecture ambiguity, but it may surface real TTS segments that C007B
   alone considers acceptable.

4. **Real Windows AAC/mux acceptance is still required.**
   S004 proves drawtext/H.264; it does not prove the complete C009 multi-WAV timing + AAC stream-copy
   mux path.

These are implementation/acceptance sequencing constraints, not reasons to reopen the v1 decision.
