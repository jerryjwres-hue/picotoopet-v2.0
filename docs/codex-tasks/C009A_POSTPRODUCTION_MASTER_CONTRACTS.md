# C009A — Post-production Master Contracts, Lineage & Artifact Catalog v1

## Objective

Implement the non-FFmpeg half of the G004 C009 master compositor:

- combine the actual C004 / C007B / C008B artifact contracts in one Windows integration base
- validate exact cross-stage lineage
- independently reverify all durable source bytes and manifests
- define deterministic master identity/digest
- define immutable master manifest/artifact/catalog
- implement restart-safe reuse/conflict semantics around an injected composer boundary

Do NOT implement the actual audio mux command in C009A.
C009B will provide the real FFmpeg composer after this contract is frozen.

## Branch

feature/postproduction-master-contracts-v1

Current base:
40141bf6ce1f1b9fb23485221ed202c5615eccf2

This base already contains:
- C007A
- C008A / C008A2
- latest C008B implementation/fixes

It does NOT contain C007B implementation.

## Required dependency composition

Before implementing C009A, first bring the C008B base to its latest reviewed fix, then cherry-pick C007B.

First cherry-pick this exact C008B follow-up commit:

0. 933b5822a1a3b20e9608390c285737773d0d423f

Then cherry-pick these exact C007B commits in order:

1. 37dc969626883c8a69f3659befaa236b187cb29b
2. 5d6150b1787118035a01b4ffdbdd24e28c7bd57c
3. 5766eca4b08f3b8525ea2a26c1044f8155e159d6
4. f731b4e9b41ee5d7dc57f5fece96769dc864ac5f
5. 01d7b3255d8a8ee2124ecdc0e182d595541085da
6. accb2919fb4709201fad24b38f48ce35810ffff8
7. f83c18e16c7c1e3ae50d0bf7a8caf7536e109cf6
8. 3079c6e7dbfb216b65ae7d502833145ba544e85c
9. 856b99fbc7c3c775b892528cef356a6f474f6b24
10. 2da47106a2fea798c460ec2bc0042d60116aa8e1
11. f51d093de16ee9fdcd8e18b02c24cbdb40c47de1
12. 1948c6c20aec4849dd17a13bf3f402a11543d067
13. 864305b8282de8a4865765c2384ac31ed091a47d
14. 96db125b842a5c6107850aee9ec64cab37162301
15. 32b1645b6e675bb4a603c7451c5162f2732479df

Do not merge or rebase.

If there is a semantic conflict between C007B and C008B contracts, stop and report.
Ordinary non-overlapping cherry-pick conflicts may be resolved only if semantics are unchanged.

After composition:
- Windows Release build must compile
- C007B focused smokes remain green
- C008B focused smokes remain green

If current PR #58 or #62 later reveals a semantic blocker, stop and report before continuing C009A.

## Architecture authority

Read and obey:
- docs/architecture/video/G004_POSTPRODUCTION_COMPOSITOR_V1.md
- docs/architecture/video/S005_WINDOWS_AUDIO_MUX_RESULT.md

G004 decision is frozen:
- if overlays_required=true, visual source = verified C008B derived MP4
- otherwise visual source = verified C004 FinalVideoArtifact
- narration_required=true requires verified C007B narration artifact
- narration_required=false creates no audio stream
- C009 video must later be stream-copied, not re-encoded

S005 decision is frozen:
RECOMMEND_STREAM_COPY_AAC_MUX

C009A does NOT implement that FFmpeg path yet.

## New product boundary

Create an injected composer interface, e.g.:

IMasterVideoComposer

It receives only already-verified internal composition facts:
- selected verified visual file/path
- ordered verified narration segment files + integer start/end/window facts
- target runtime
- internally chosen temp output path

It must NOT receive caller-selected codec/filter/bitrate/executable options.

C009A tests use a deterministic fake composer.
C009B later provides the fixed FFmpeg implementation.

## Master input

Use the actual landed types; do not invent replacements:

- C004 FinalVideoArtifact
- C007A NarrationPlanResponseRecord
- C007B NarrationArtifact
- C008A2 CaptionOverlayPlanResponseRecord
- C008B TextOverlayArtifact

Conceptually:

MasterCompositionInputV1
- FinalVideoArtifact c004
- NarrationPlanResponseRecord narration_plan
- NarrationArtifact? narration_artifact
- CaptionOverlayPlanResponseRecord overlay_plan
- TextOverlayArtifact? overlay_artifact

Caller must not provide:
- arbitrary input path
- arbitrary output path
- executable
- codec
- filter
- bitrate
- sample rate
- channels
- shell args

## Cross-stage identity validation

Before creating any work/output directory, require:

1. C004 ProductionJobId == C007 plan ProductionJobId == C008 plan ProductionJobId.
2. C007 / C008 CreativePackageId match.
3. C007 / C008 CreativePackageDigest match.
4. C007 / C008 ProductionPlanDigest match.
5. C007 / C008 TargetRuntimeMs match.
6. C008 OutputProfileId is one of closed C005 IDs.
7. Captions remain unsupported in v1:
   - CaptionsRequired=false
   - Captions=[]
8. if overlays_required:
   - overlay artifact required
   - Passthrough=false
   - ProductionJobId matches
   - SourceFinalSha256 matches reverified C004 source SHA
   - CaptionOverlayPlanDigest matches plan response
   - OutputProfileId matches plan
9. if overlays not required:
   - selected visual source is C004
   - overlay artifact is not master authority
10. if narration_required:
   - narration artifact required
   - narration durable manifest must bind exact NarrationPlanDigest
   - every C007 segment has exactly one WAV manifest entry
11. if narration not required:
   - narration artifact not required
   - no audio composition inputs

No stale artifact may be silently substituted.

## Independent durable verification

C009A must not trust previous Ready flags alone.

### C004
Reverify:
- exact managed FinalVideos root
- ordinary file
- no reparse escape
- manifest ordinary/no reparse
- production package id/digest lineage
- bytes
- SHA-256

Use the existing C004 file naming/manifest contract.
Do not modify FinalVideoAssemblyService.cs.

### C008B
When overlays_required:
reverify:
- exact managed TextOverlay/v1 root
- ordinary file/manifest
- no reparse escape
- source C004 SHA
- plan digest
- output profile
- renderer profile
- output bytes/SHA
- Passthrough=false

Do not modify WindowsCaptionOverlayService.cs.

### C007B
When narration_required:
reverify:
- managed Narration/v1/<safe-job> contract
- narration manifest ordinary/no reparse
- plan digest
- creative/package/production-plan lineage
- segment count/order/IDs/text SHA/start/end
- every WAV ordinary/no reparse
- SHA/bytes
- PCM16
- mono/stereo
- sample rate 8–48 kHz
- actual WAV duration >0
- IMPORTANT: C009 must enforce actual WAV duration <= exact C007A window
  with NO +250 ms tolerance.
  If longer, fail NARRATION_SEGMENT_TOO_LONG.
- no truncation/rate alteration here

C009A may define its own strict read-only manifest mirror for consuming C007B/C008B durable manifests.
Do not modify their producer schemas unless an actual incompatibility is proven.

## Verified internal facts

After validation expose internal records only, e.g.:

VerifiedMasterVisual
- path
- sha256
- bytes
- source_kind: c004 | c008b

VerifiedMasterNarrationSegment
- segment_id
- order
- wav_path
- sha256
- bytes
- start_ms
- end_ms
- actual_duration_ms
- sample_rate
- channels

No public/caller path authority.

## Master identity

Define a canonical MasterInputDigest / artifact identity that binds at minimum:

- schema/profile version
- production_job_id
- production_package_id/digest from C004
- production_plan_digest
- creative_package_id/digest
- target_runtime_ms
- output_profile_id
- narration_required
- narration_plan_digest
- ordered narration segment:
  - id/order/start/end/text_sha256/wav_sha256/bytes/actual_duration
- overlays_required
- caption_overlay_plan_digest
- selected visual source kind
- selected visual SHA/bytes
- C004 source SHA
- C008B artifact SHA/bytes when used
- fixed master profile id
- fixed audio profile id

Use deterministic canonical JSON + SHA-256.

Suggested closed IDs:
- master profile: postproduction.master.v1
- audio profile: audio.aac-lc.48k.mono.128k.v1

Do not bind absolute paths or timestamps into identity.

## Managed output

Root:
%LOCALAPPDATA%\PicotooPet\PostProduction\Master\v1\

Use identity-scoped durable path, e.g.:
<safe-job>/<master-input-digest>/

Inside:
- master.mp4
- master-manifest.json

Exact final filenames may differ if deterministic and tested.

Do not recursively search for latest MP4.

## Master artifact / manifest

Create public C009 artifact record, e.g. MasterVideoArtifact:
- ProductionJobId
- MasterInputDigest
- FilePath
- ManifestPath
- Sha256
- Bytes
- HasAudio
- Reused

Manifest must contain lineage sufficient for C010/G007:
- schema_version
- master_profile_id
- audio_profile_id
- production_job_id
- production_package_id/digest
- creative_package_id/digest
- production_plan_digest
- target_runtime_ms
- output_profile_id
- narration_required
- narration_plan_digest
- ordered narration segment provenance, no raw text
- overlays_required
- caption_overlay_plan_digest
- C004 source SHA
- selected_visual_kind
- selected_visual_sha/bytes
- C008B SHA when applicable
- output filename only
- output SHA/bytes
- has_audio
- master_input_digest
- created_at

Never persist:
- raw narration text
- raw overlay text
- absolute source/output/font paths
- FFmpeg command/filter
- credentials

## Service / catalog

Implement:
- PostProductionMasterCompositorService
- PostProductionMasterArtifactCatalog (or equally narrow names)

Service:
1. validate/reverify exact inputs
2. derive master input digest
3. query exact expected durable path only
4. if exact verified manifest/output exists => reuse
5. if partial/conflicting durable entries => MASTER_ARTIFACT_CONFLICT
6. if absent => invoke IMasterVideoComposer into temp/work area
7. verify returned ordinary output exists/nonzero
8. SHA/bytes
9. atomically promote output
10. atomically write/promote manifest last as commit marker
11. return MasterVideoArtifact

Catalog:
FindVerifiedExact(...)
- requires expected job + master digest/lineage
- never recursive/latest search
- revalidates manifest/path/hash/bytes
- returns null only for clean absence
- conflicts/tamper fail closed

C009A fake composer may copy/write deterministic fixture bytes in focused tests.
Do not pretend fake output is real MP4 QA.
Real media verification belongs C009B/C010.

## Restart / idempotency

- exact same verified lineage => same master input digest
- exact same existing durable artifact => reuse
- output without manifest => conflict
- manifest without output => conflict
- mismatched manifest => conflict
- tampered output => conflict
- different digest => different identity-scoped directory, not overwrite
- temp/work leftovers may be safely removed/ignored if outside committed artifact path

## Error model

Closed local errors, e.g.:
- MASTER_INPUT_INVALID
- MASTER_LINEAGE_MISMATCH
- MASTER_VISUAL_INVALID
- MASTER_NARRATION_INVALID
- NARRATION_SEGMENT_TOO_LONG
- MASTER_ARTIFACT_CONFLICT
- MASTER_COMPOSER_FAILED
- MASTER_OUTPUT_INVALID

Never leak:
- absolute paths
- raw text
- raw manifest body
- process stderr

## File ownership

Prefer new files under:
windows/desktop/src/PicotooPet.Desktop/Services/
- PostProductionMasterContracts.cs
- PostProductionMasterCompositorService.cs
- PostProductionMasterArtifactCatalog.cs
- IMasterVideoComposer.cs
- focused helpers

Tests:
create an isolated harness, e.g.
windows/desktop/tests/PicotooPet.PostProductionMaster.SmokeTests/

Do NOT modify shared SmokeTests/Program.cs.

Forbidden:
- C004 FinalVideoAssemblyService.cs
- GoalFinalVideoCoordinator.cs
- C007B producer files/contracts
- C008B producer files/contracts
- Production/C006 files
- Goal Center/UI
- Maotai/Natural Motion
- deploy/macos
- publishing

Minimal project/assembly metadata changes are allowed only if required to compile new shipping files.

## Tests

Dependency composition:
- C007B focused tests
- C008B focused tests
- Windows Release build

Lineage:
- all IDs/digests match => pass
- any job/package/plan/runtime/profile mismatch => fail closed
- overlay required but missing/passthrough/wrong digest => fail
- narration required but missing/wrong manifest => fail
- captions populated => fail

Durable verification:
- source path escape/reparse => fail
- tampered C004 => fail
- tampered C008B => fail
- tampered narration WAV => fail
- narration manifest mismatch => fail
- exact WAV duration > exact plan window => NARRATION_SEGMENT_TOO_LONG

Identity:
- stable canonical digest
- changes when any meaningful lineage/source hash/segment fact changes
- does not change from timestamp/absolute root differences

Artifact lifecycle:
- first fake-compose commits output + manifest
- exact restart reuses
- output-only conflict
- manifest-only conflict
- tampered output conflict
- stale wrong digest not selected
- FindVerifiedExact returns exact artifact only

Security:
- no caller command/filter/codec/path authority
- no raw narration/overlay text in master manifest/errors

## C009B handoff

At the end, clearly report the frozen interface C009B must implement:
IMasterVideoComposer

C009B is responsible only for:
- fixed FFmpeg audio graph
- video stream-copy
- AAC-LC 48k mono 128k
- process timeout/cancel
- media-level output validation

C009B must not redesign master identity/catalog/manifest.

## Delivery requirements

- commit all changes
- push to origin/feature/postproduction-master-contracts-v1
- do not merge/rebase/tag/release
- working tree clean

Final response only:
remote branch
remote HEAD SHA
dependency composition
files changed
tests
frozen C009B interface
architecture notes
residual risk
git status --short
