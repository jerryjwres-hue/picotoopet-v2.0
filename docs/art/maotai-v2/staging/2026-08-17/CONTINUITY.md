# Maotai v2 art staging continuity

This directory is non-runtime staging only. Runtime assets live under `windows/desktop/src/PicotooPet.Desktop/Assets/Maotai/V2` and must stay manifest-only.

## Current source of truth

- Repository: `jerryjwres-hue/picotoopet-v2.0`
- Branch: `feature/maotai-natural-motion-v2`
- Draft PR: `#36` — keep Draft, do not merge/Ready.
- Software/motion gates are green up to the formal raster asset gate.
- Continuity rule: every useful art candidate is committed here before runtime promotion so a new chat can resume without regenerating prior work.
- Neutral torso binary promotion commit: `ad34a7cce205913b72fa4f0c1f2f5c6c737c79b8`.

## `torso_neutral.png` — promoted

- logical contract: `92 x 78`
- pivot: `(46, 41)`
- joint overlap: `20 px` logical
- runtime pixels: `184 x 156` RGBA
- visible alpha bbox: `x=33..156, y=10..144`
- outer border alpha: zero on all four edges
- source: independent torso-only generation, never cropped from a full character
- repair: hollow neck/limb sockets were replaced with continuous fluffy overlap roots using texture sampled only from the torso-only source
- PNG SHA-256: `5c76347d2d1a43f19d4d21b4d1b414a334b6558f5a8899e6a40c82ad71fbbbd5`
- staging copy: `torso_candidate_v2.png`
- formal runtime path: `windows/desktop/src/PicotooPet.Desktop/Assets/Maotai/V2/torso_neutral.png`

## Rejected paths preserved to prevent repetition

- `torso_candidate_v1_preview.png`: rejected — too tall/narrow, alpha edge issue, hollow socket geometry.
- Canva Magic Layers design `DAHSm6Tmcyc`: rejected — single-layer non-uniform resize could not repaint sockets; transaction cancelled.
- `rig_atlas_reference_v1_preview.jpg`, `rig_atlas_reference_v2_preview.jpg`, v3/reference boards: reference only; never crop atlas/full-character renders into runtime parts.
- generation ids `89bf9df4-8313-41cc-bfb4-615e7a5b8e60`, `b926d3f5-3039-40ea-88eb-bc23b9f46616`, `ca81c0bd-bcab-45fd-b254-0b8632d0e6e6`: rejected because generator drifted to atlas/concept-board output instead of torso-only edits.

## Exact next action

1. Ensure branch head includes `ad34a7cce205913b72fa4f0c1f2f5c6c737c79b8` (or a descendant) before any further work.
2. Run Windows/Prebuilt on the promoted `torso_neutral.png`.
3. Confirm the formal asset gate advances past `torso_neutral.png`; the next missing manifest asset becomes the new hard blocker.
4. Produce that next asset as a true independent transparent part using the same charcoal-gray/white high-quality chibi 3D-CG Maotai visual language.
5. Save every accepted/rejected meaningful candidate in GitHub staging/continuity before proceeding.
6. Do not weaken the asset gate and do not add full-character state frames to the formal V2 directory.
