# Maotai v2 art staging continuity

This directory is non-runtime staging only. Runtime assets live under `windows/desktop/src/PicotooPet.Desktop/Assets/Maotai/V2` and must stay manifest-only.

## Source of truth

- Repository: `jerryjwres-hue/picotoopet-v2.0`
- Branch: `feature/maotai-natural-motion-v2`
- Draft PR: `#36` — keep Draft; do not merge or mark Ready.
- `MaotaiAssetManifest.cs` is authoritative for file names, logical dimensions, pivots and overlap values.
- Every useful art candidate must be committed to this staging area before runtime promotion so a new chat can resume without regenerating work.
- Formal PNGs are promoted only after RGBA/alpha/border/dimension checks and exact Git blob SHA verification.

## CI-confirmed formal assets added in this art pass

- `torso_neutral.png`: logical `92 x 78`, pivot `(46,41)`, overlap `20`; Prebuilt #2353 passed it.
- `torso_crouch.png`: logical `96 x 72`, pivot `(48,39)`, overlap `20`; Prebuilt #2362 passed it.
- `torso_stretch.png`: logical `90 x 86`, pivot `(45,45)`, overlap `20`; Prebuilt #2372 passed it.
- `chest_fur.png`: logical `62 x 52`, pivot `(31,18)`, overlap `16`; Prebuilt #2378 passed it.

Current formal raster blocker after those CI runs: `head.png`.

## Current missing formal PNGs

17 files remain:

- head/face base: `head.png`, `muzzle.png`
- limb segments: `front_left_upper.png`, `front_left_lower.png`, `front_right_upper.png`, `front_right_lower.png`, `hind_left_upper.png`, `hind_left_lower.png`, `hind_right_upper.png`, `hind_right_lower.png`
- tail: `tail_base.png`, `tail_mid.png`, `tail_tip.png`
- headphones: `headphone_band.png`, `headphone_left.png`, `headphone_right.png`
- prop: `laptop.png`

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
- atlas/reference boards and complete-character renders are reference only; never crop them into runtime parts.
- `head_candidate_v1.png`: rejected; torso texture deformed into a head silhouette still read as a distorted torso.
- generation ids `17741133-9c6a-4434-8413-59dde9964f8f`, `dd15985b-9272-4377-a1fb-5ec232d604e3`, `de41edc5-3327-4b0b-b8d3-35bf9ad85647`: rejected because image generation drifted to promotional boards/full-character collages instead of a single formal part.
- never attach a GitHub PNG blob unless GitHub's returned blob SHA exactly matches the locally computed Git blob SHA.

## Exact next action

1. Produce one true independent `head.png` at the manifest contract above.
2. Validate RGBA decode, transparent outer borders, nonempty alpha bbox, dimensions and pivot-compatible composition.
3. Verify local vs remote Git blob SHA exactly.
4. Commit staging + formal runtime copy together, fast-forward only.
5. Run Windows/Prebuilt and let the hard gate expose the next missing asset.
6. Continue in manifest order; keep PR #36 Draft until the full formal rig and real-Windows visual acceptance are complete.
