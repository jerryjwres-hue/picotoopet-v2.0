# C006B2B — EXISTING_ASSET Production Integration v1

## Objective

Make Creative `EXISTING_ASSET` shots automatically executable through the existing Production lifecycle, using only C006B1 trusted image identities and the C006A local-media executor.

No second Production pipeline. No arbitrary paths. No C004 changes.

## Branch

feature/existing-asset-production-v1

Base:
f1a688d4ff8c70f7155aa1194b358af825265e59

This base already contains:
- C006B1 trusted asset registry/Windows ingress
- C006B2A Creative trusted asset binding

It does NOT yet contain C006A TEXT_CARD/local_media implementation.

## Required dependency composition

Before implementing C006B2B, cherry-pick these exact C006A implementation/fix/test commits in this order:

1. f43c6e8638016f7382358a35ea333933d1aab5d8
2. e48b4a2ee07783d4e9c2bd5aafec0e883e8d623d
3. 6783fa916c3691e683b4c099b6e791eb33d1d002
4. 7ac2caa2d4cbd7597da0f6fa025adfea4c49e653
5. 4978bcfba7d79ba28044a9854b8558c4f386a521
6. 69f100e2b35b74ee55c472c611cd5fb7495588bc
7. 4c4669dec9bd39874d746714e6bc17408ae30ddc
8. bdbdffb0dbc0e64012680c7e9f03ce583e0bfbc2
9. a828ca277091d0ae4f5345e11fffd6f9545f3e50

Do NOT merge or rebase.
If cherry-pick has a semantic conflict, stop and report it before implementing.

After cherry-pick, verify C006A tests/build remain green.

## Core ownership

### Frozen trusted asset snapshot

Add a strict frozen model, e.g. `ProductionTrustedAssetSnapshotV1`, containing only:

- asset_id
- scope_kind
- scope_id
- managed_root_id
- managed_relpath
- sha256
- size_bytes
- media_type
- width
- height

No source_path / absolute path / URL / endpoint / executable / model / workflow authority.

`managed_root_id` must be exactly:
`windows.comfy-input.v1`

media type:
- image/png
- image/jpeg

### ProductionTaskPlan

Add closed execution profile:
`production.local.existing-image.v1`

For an executable EXISTING_ASSET task:
- execution_backend = local_media
- execution_profile_id = production.local.existing-image.v1
- workflow_id = null
- local_media text payload = null
- trusted asset snapshot = required

TEXT_CARD semantics remain exactly as C006A.

GENERATIVE_VIDEO / IMAGE_TO_VIDEO remain Comfy.

GENERATIVE_IMAGE / PRODUCT_ASSET_COMPOSITE remain NeedsHuman.

Keep legacy `trusted_input_asset_ref` backward-compatible if required for old persisted plans, but it must NOT be the authority for new EXISTING_ASSET tasks.

### Asset resolution

Production compiler itself should remain deterministic and not query Windows paths.

Preferred flow:
1. ProductionService reads the immutable Creative Package.
2. Collect `existing_asset_ref` from validated ShotPlan.
3. Resolve each ref through C006B1 `TrustedAssetService`.
4. Enforce exact scope binding:
   - v1 Goal video package project_key `autonomous-goal:<goal_id>`
   - asset must be `scope_kind=autonomous_goal`, `scope_id=<goal_id>`
5. Pass a closed asset-record mapping to compiler.
6. Compiler freezes the exact snapshot into ProductionTaskPlan.
7. Missing/changed/cross-scope asset => fail closed.

Do not allow caller request fields to provide asset facts.

ProductionService may gain a TrustedAssetService dependency.
Wire it from existing app services without adding a second registry.

### Determinism

Plan digest must include the frozen trusted asset snapshot.

Same Creative Package + same immutable asset record => same plan digest.

Asset identity/facts mismatch => bounded failure, never silently substitute another file.

## Windows execution

Reuse `ProductionLocalMediaRenderer`.

Extend it to dispatch two closed profiles:
- production.local.text-card.v1
- production.local.existing-image.v1

Do not build a second renderer service.

For EXISTING_ASSET:
1. derive the trusted input absolute path only from:
   - the configured Comfy input root
   - Core-frozen managed_relpath
2. resolve under root with existing path-safety primitives
3. reject reparse/link escape
4. require ordinary existing file
5. recompute size + SHA-256
6. decode bytes again and verify:
   - PNG/JPEG media type
   - width
   - height
7. compare all facts with frozen snapshot
8. only then invoke fixed FFmpeg normalization

Do not trust extension alone.

### Image -> WebM normalization

Use the exact C005 frozen:
- width
- height
- fps
- frame_count

Use a fixed internally-authored normalization policy:
- preserve aspect ratio
- fit entire source image inside target canvas
- deterministic centered padding
- fixed background color
- no animation/pan/zoom in v1

Recommended fixed FFmpeg semantics:
- loop still image
- scale with force_original_aspect_ratio=decrease
- centered pad to exact output profile
- exact frame_count/fps
- libvpx-vp9
- yuv420p
- no audio
- bitexact/metadata stripping consistent with TEXT_CARD

All filter text must be constructed internally from frozen integer dimensions.
No caller-supplied filter string.

Output:
- video/webm
- exact task width/height/fps/frame_count
- commit through existing ProductionTaskCommitRequest

## Root plumbing

C006B1 ingress and C006B2B execution MUST refer to the same trusted Comfy input root.

Do not expose an arbitrary input-root parameter through Goal/GPT/Core APIs.

If `ProductionLocalMediaRenderer.RenderAsync` needs the input root, evolve its internal service interface minimally:
- output root remains managed Production output root
- trusted input root comes from the existing Comfy data-root resolver/preflight
- tests may inject fixed roots

No source absolute path enters ProductionPlan or Core.

## Attempt/retry/restart

Reuse C006A semantics exactly:
- reserve attempt before FFmpeg
- duplicate ambiguous HTTP reservation does not burn second attempt
- explicit local retry may use second attempt
- max two attempts
- partial output never durable success
- restart skips Succeeded task
- existing verified output/package remains immutable

No new lifecycle table.

## Production Package provenance

ProductionPackage remains the only Production package.

For each EXISTING_ASSET output add bounded source provenance:
- asset_id
- sha256
- media_type
- width
- height
- managed_root_id
- managed_relpath

Do not include:
- source absolute path
- original filename
- user path

Pure local-media package must not claim Comfy workflow/model provenance.

Mixed Comfy + TEXT_CARD + EXISTING_ASSET package must report only actually-used workflows/models.

C004 must remain unchanged; it consumes normalized ordered WebM outputs.

## IMAGE_TO_VIDEO

Do NOT migrate IMAGE_TO_VIDEO to trusted asset identity in this slice.

However:
- do not worsen its current contract
- document a residual migration point
- no new arbitrary path authority

## Explicit exclusions

Do not implement:
- GENERATIVE_IMAGE
- PRODUCT_ASSET_COMPOSITE
- video-file trusted asset ingress
- image animation
- pan/zoom
- captions
- narration
- C004 changes
- Goal Center UI
- Maotai/UI
- deploy/macos
- Natural Motion

Do not touch:
- C007 narration files
- C008 caption-overlay files
- S002 Production HTTP lifecycle files

## Expected files

Core likely:
- src/picotoopet_core/production/models.py
- production/compiler.py
- production/service.py
- production/package.py
- src/picotoopet_core/services.py only for TrustedAssetService injection
- focused production tests

Windows likely:
- ProductionContracts.cs
- ProductionExecutionService.cs
- ProductionLocalMediaRenderer.cs
- focused smoke tests

Use existing C006B1 TrustedAsset contracts/services.
Do not duplicate them.

## Required tests

### Core
- EXISTING_ASSET with same-goal registered asset => Executable/local_media/existing-image profile
- frozen snapshot matches registry facts exactly
- plan digest changes if trusted asset facts change
- unknown asset => fail closed
- cross-goal/scope asset => fail closed
- wrong MIME/root/duration facts => fail closed
- non-EXISTING_ASSET cannot carry trusted asset snapshot
- old plans remain loadable
- TEXT_CARD unchanged
- GENERATIVE_VIDEO/I2V unchanged
- GENERATIVE_IMAGE/PRODUCT_ASSET_COMPOSITE remain NeedsHuman

### Windows
- exact managed_relpath resolves only under trusted input root
- traversal/reparse/ancestor-link rejected
- missing file rejected
- size mismatch rejected
- SHA mismatch rejected
- renamed/wrong MIME rejected
- decoded dimension mismatch rejected
- valid PNG and JPEG render
- fixed scale+pad policy
- exact C005 width/height/fps/frame_count
- output video/webm
- no shell/arbitrary filter/font/model/path authority
- timeout/cancel cleans partials
- restart/retry semantics match C006A
- mixed TEXT_CARD + EXISTING_ASSET + Comfy execution succeeds under one Production lifecycle

### Package
- asset provenance present for EXISTING_ASSET
- no absolute/source paths
- local-only package has no fake workflow/model provenance
- mixed package reports only actual Comfy workflow/model usage

### Regression
- C001-C006B2A relevant Python tests
- C006A smokes
- Windows Release build
- Control Center self-test
- C004 assembly compatibility
- Ruff touched Python

## Acceptance

PASS when a Goal/Web-GPT-selected C006B1 PNG/JPEG:
- is referenced only by trusted asset_id,
- is frozen into ProductionPlan with immutable facts,
- is reverified on Windows under the trusted Comfy input root,
- is deterministically normalized to C005-compatible WebM,
- commits through the existing Production lifecycle,
- packages provenance correctly,
- and requires zero C004 changes.

## Delivery requirements

After implementation/testing:
- commit all changes
- push to origin/feature/existing-asset-production-v1
- do not merge
- do not rebase
- do not tag
- do not release
- working tree clean

Final response only:
remote branch
remote HEAD SHA
files changed
tests
architecture notes
residual risk
git status --short
