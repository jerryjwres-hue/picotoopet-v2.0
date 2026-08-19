# Maotai v2 art staging continuity

This directory is non-runtime staging only. Runtime assets live under `windows/desktop/src/PicotooPet.Desktop/Assets/Maotai/V2` and must stay manifest-only.

## Source of truth

- Repository: `jerryjwres-hue/picotoopet-v2.0`
- Branch: `feature/maotai-natural-motion-v2`
- Draft PR: `#36` — keep Draft; do not merge or mark Ready.
- `MaotaiAssetManifest.cs` is authoritative for file names, logical dimensions, pivots and overlap values.
- Every useful art candidate/checkpoint must be committed to staging before runtime promotion so a new chat can resume without regenerating work.
- Formal PNGs are promoted only after RGBA/alpha/border/dimension checks and exact Git blob SHA verification.

## CI-confirmed formal assets added in this art pass

- `torso_neutral.png`: logical `92 x 78`, pivot `(46,41)`, overlap `20`; Prebuilt #2353 passed it.
- `torso_crouch.png`: logical `96 x 72`, pivot `(48,39)`, overlap `20`; Prebuilt #2362 passed it.
- `torso_stretch.png`: logical `90 x 86`, pivot `(45,45)`, overlap `20`; Prebuilt #2372 passed it.
- `chest_fur.png`: logical `62 x 52`, pivot `(31,18)`, overlap `16`; Prebuilt #2378 passed it.

Current formal raster blocker after those CI runs: `head.png`.

## 2026-08-18 batch checkpoint — restart safe

A generated **modular asset board** contained independently rendered cells for 16 of the 17 remaining files. Only those independent cells were used; complete-character preview poses and sprite examples were explicitly excluded.

The following 16 candidates are now preserved in GitHub as a compact reversible checkpoint:

- `muzzle.png`
- `front_left_upper.png`, `front_left_lower.png`, `front_right_upper.png`, `front_right_lower.png`
- `hind_left_upper.png`, `hind_left_lower.png`, `hind_right_upper.png`, `hind_right_lower.png`
- `tail_base.png`, `tail_mid.png`, `tail_tip.png`
- `headphone_band.png`, `headphone_left.png`, `headphone_right.png`
- `laptop.png`

Checkpoint files:

- `docs/art/maotai-v2/staging/2026-08-18/batch1_missing16.mtr.b85`
- `docs/art/maotai-v2/staging/2026-08-18/restore_batch1_missing16.py`
- checkpoint commit: `3d542cb6e4ac1ecace9be2127f81291f787caead`
- decoder commit: `a6024306064ce36cd5fbfb9912591510fcd281ce`

The MTR1 checkpoint stores logical-resolution RGBA/palette/index data and is designed only to prevent regeneration after a chat restart. Restored candidates still need @2x manifest sizing, pivot/overlap placement, RGBA outer-border validation and formal runtime promotion.

Batch processing decisions already made:

- limb source cells contain paw-like ends; formal upper/lower segments must remove those ends because the four paw PNGs already exist independently.
- tail cells are mirrored horizontally before formal promotion so their root sits on the right-side pivot specified by the manifest.
- headset-only source is allowed to produce band/left/right pieces because it is not a complete-character render.
- modular independent-part cells may be used as production sources; complete-character preview/state images remain forbidden as cut sources.

## Remaining formal PNGs

17 files were missing before the checkpoint. The 16 above now have restart-safe candidate data, but are not yet all promoted to runtime. `head.png` remains the only asset that still needs a satisfactory independent visual master before the whole batch can be promoted and CI-walked.

Existing ears, eyes, pupils, brows, five mouth states, all four paws, drink and shadow remain separate and should not be redrawn unless final visual assembly proves a mismatch.

## `head.png` — current production target

Authoritative manifest contract:

- logical size: `78 x 70`
- pivot: `(39,42)`
- joint overlap: `20 px` logical
- minimum @2x runtime size: `156 x 140` RGBA
- role: independent head shell / forehead / cheek-fur / neck-overlap base only
- do not bake in separate ears, pupils, brows, expression mouths, props, headphones or complete-character pixels

Reference/source notes:

- Canva rig reference `DAHSZ9UjHCw` includes native head/face assets `MAHSZ73u7SM` (230x209) and `MAHSZ3uLUf0` (248x323).
- They are head-only references/sources, not final runtime assets; features that already have independent layers must not be baked into final `head.png`.

## Rejected paths — do not repeat

- `torso_candidate_v1_preview.png`: rejected for tall/narrow proportions, edge issue and hollow socket geometry.
- Canva Magic Layers single-layer torso resize: rejected because it could not repaint socket geometry.
- complete-character renders are reference only; never crop them into runtime parts.
- `head_candidate_v1.png`: rejected; torso texture deformed into a head silhouette still read as a distorted torso.
- image generation repeatedly drifted to promotional/asset boards when asked for one isolated part. Do not spend repeated turns retrying that same free-generation path; use head-only source reconstruction/editing instead.
- never attach a GitHub PNG blob unless GitHub's returned blob SHA exactly matches the locally computed Git blob SHA.

## Exact next action

1. Finish a satisfactory independent `head.png` at `78 x 70` logical / `156 x 140` @2x.
2. Restore the batch checkpoint and promote the head + 16 candidates in grouped fast-forward commits.
3. Run the formal pixel/manifest gate and Windows/Prebuilt; fix only assets that the gate or visual assembly actually rejects.
4. Keep PR #36 Draft until the full formal rig and real-Windows visual acceptance are complete.
