# Maotai v2 art staging continuity

This directory is **non-runtime staging only**. Nothing here is loaded by the desktop pet at runtime, and these preview files must not be copied into `windows/desktop/src/PicotooPet.Desktop/Assets/Maotai/V2` unless the corresponding independent asset has passed the formal V2 asset gate.

## Current source of truth

- Repository: `jerryjwres-hue/picotoopet-v2.0`
- Development branch: `feature/maotai-natural-motion-v2`
- Draft PR: `#36`
- Runtime/software gates are green up to the formal raster asset gate.
- Current hard blocker remains: `torso_neutral.png` is not yet present in the formal V2 asset directory.
- Durable art staging snapshot commit: `937c152af585267d6309b62247dc1e8285d05c3a`.

## Formal `torso_neutral.png` contract

From `MaotaiAssetManifest`:

- logical size: `92 x 78`
- pivot: `(46, 41)`
- joint overlap: `20 px` logical
- target production density for the first formal candidate: `184 x 156` (2x logical density)
- transparent RGBA/grayscale+alpha PNG
- safe transparent border; visible fur must not touch the canvas edge
- torso only: no head, ears, complete legs, paws, tail, headphones, collar, props, text, UI or background
- canonical Maotai look: high-quality chibi / 3D-CG Alaskan Malamute, charcoal-gray + white coat, soft consistent lighting
- neck, shoulder/foreleg roots, hip/hind-leg roots and tail-root connection zones use continuous fluffy hidden overlap; **no hollow toy-like sockets**
- never crop a torso out of a completed full-character render

## Preserved visual references

These are reduced-size continuity previews committed only so a future conversation can recover the exact visual direction without starting over.

### `torso_candidate_v1_preview.png`

- provenance: image generation id `8a03492f-4599-432c-9eca-7a14bcf5b439`
- useful for: coat colors, fur material, chest/belly pattern, overall CG rendering direction
- status: **REJECTED as formal runtime asset**
- rejection reasons: original alpha bbox touched the source canvas edge; body proportion was too tall/narrow for the 92x78 logical torso; limb roots read as hollow sleeve/socket openings rather than continuous fur overlap

### `rig_atlas_reference_v1_preview.jpg`

- provenance: image generation id `5ea4d510-e5d5-4515-afae-a5f648a7d5d3`
- useful for: face/limb/tail/accessory style coherence and blue accessory palette
- status: **REFERENCE ONLY**
- not valid for formal V2 assets because it is an atlas/full-character composition and may not be cropped into the raster skeleton

### `rig_atlas_reference_v2_preview.jpg`

- provenance: image generation id `d9e1ed06-b322-4e0f-b413-54a1eb715a94`
- useful for: broader rig visual vocabulary, fur consistency, paw/ear/tail segmentation ideas
- status: **REFERENCE ONLY**
- not valid for formal V2 assets because it is an atlas/full-character composition and contains extra non-manifest props

## Rejected editing path

A Canva Magic Layers working design was created from `torso_candidate_v1` and tested with a non-uniform resize to the manifest aspect ratio. The edit was **cancelled** and must not be retried as the main solution.

- Canva working design: `DAHSm6Tmcyc`
- test: resize single detected image layer to the 92:78 torso aspect ratio and center it
- outcome: proportion improved, but hollow limb-root/socket geometry remained because Magic Layers exposed only one image fill and could not genuinely repaint the fur connections
- decision: do not promote or commit this stretched edit; regenerate/repaint a true torso-only source instead

## Exact next action

1. Generate a second **torso-only** candidate following the formal contract above.
2. Reject any result containing a collar, headset, full limbs, tail, head, scenery, checkerboard baked into RGB, hollow limb sockets or edge-cropped fur.
3. Inspect visual proportion before engineering normalization.
4. Normalize an accepted candidate to `184 x 156` while preserving alpha and safe border.
5. Validate PNG signature/IHDR/alpha/nonempty bbox/border clearance against the existing smoke gate.
6. Only after visual + pixel validation, commit it as `windows/desktop/src/PicotooPet.Desktop/Assets/Maotai/V2/torso_neutral.png` and run the Windows WPF / Prebuilt gates.
7. Keep PR #36 Draft; do not merge or mark Ready until the full formal raster rig and real-Windows visual acceptance are complete.

The preview images in this staging directory are intentionally not production-resolution deliverables. Their purpose is durable visual and decision continuity while avoiding repository bloat from rejected generated originals.
