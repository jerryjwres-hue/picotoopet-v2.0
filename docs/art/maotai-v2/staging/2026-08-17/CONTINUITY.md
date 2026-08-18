# Maotai v2 art staging continuity

This directory is non-runtime staging only. Runtime assets live under `windows/desktop/src/PicotooPet.Desktop/Assets/Maotai/V2` and must stay manifest-only.

## Current source of truth

- Repository: `jerryjwres-hue/picotoopet-v2.0`
- Branch: `feature/maotai-natural-motion-v2`
- Draft PR: `#36` — keep Draft, do not merge/Ready.
- Software/motion gates are green up to the formal raster asset gate.
- Continuity rule: every useful art candidate is committed here before runtime promotion so a new chat can resume without regenerating prior work.
- Windows Prebuilt #2353 proved `torso_neutral.png` is now a valid PNG and passed the formal asset check; the hard blocker advanced to `torso_crouch.png`.

## `torso_neutral.png` — promoted, CI-confirmed

- logical contract: `92 x 78`
- pivot: `(46, 41)`
- joint overlap: `20 px` logical
- runtime pixels: `184 x 156`, RGBA
- source: independent torso-only generation, never cropped from a full character
- hollow neck/limb sockets were repaired into continuous fluffy overlap roots using only torso-only source texture
- formal runtime path: `windows/desktop/src/PicotooPet.Desktop/Assets/Maotai/V2/torso_neutral.png`
- transport repair commit: `ba79c343d4b8edd745288b77cbd73f44b7b668b2`
- CI evidence: Prebuilt #2353 reached the next missing asset and failed only on `torso_crouch.png`.

## `torso_crouch.png` — promoted candidate, pending CI

- logical contract: `96 x 72`
- pivot: `(48, 39)`
- joint overlap: `20 px` logical
- runtime pixels: `192 x 144`, RGBA
- visible alpha bbox: `x=36..160, y=9..133`
- all four outer alpha borders are zero
- source: deformation of the already-valid independent torso-only neutral asset; never cropped from a full-character render
- visual intent: lower, wider crouch silhouette while preserving the same charcoal-gray/white Maotai fur language and hidden connection roots
- local SHA-256: `8e7fb4d59186e0ffdcf183721f34fdfba93dd1f2d5cc57c5fbe8b3c9fbffd18`
- Git blob: `aee53156ab98977dfc0c5ac95a102379f2bab79c`; connector read fails at byte `0x89`, confirming PNG signature byte presence before promotion
- staging copy: `torso_crouch_candidate.png`
- formal runtime path: `windows/desktop/src/PicotooPet.Desktop/Assets/Maotai/V2/torso_crouch.png`

## Rejected paths preserved to prevent repetition

- `torso_candidate_v1_preview.png`: rejected — too tall/narrow, alpha edge issue, hollow socket geometry.
- Canva Magic Layers design `DAHSm6Tmcyc`: rejected — single-layer non-uniform resize could not repaint sockets; transaction cancelled.
- atlas/reference boards are reference only; never crop atlas/full-character renders into runtime parts.
- generation ids `89bf9df4-8313-41cc-bfb4-615e7a5b8e60`, `b926d3f5-3039-40ea-88eb-bc23b9f46616`, `ca81c0bd-bcab-45fd-b254-0b8632d0e6e6`, `c6e98715-95a5-4346-959d-c007c2b53159`: rejected because the generator drifted to atlas/concept-board/full-character output instead of a valid torso-only part.

## Exact next action

1. Fast-forward the branch with the `torso_crouch.png` promotion commit.
2. Run Windows/Prebuilt and verify the formal raster gate passes crouch and advances to `torso_stretch.png`.
3. Produce `torso_stretch.png` independently at `180 x 172` (2x the `90 x 86` logical contract), pivot `(45,45)`, preserving transparent safe border and the same hidden fur overlaps.
4. Continue in manifest order, committing every meaningful accepted/rejected art candidate to staging before moving on.
5. Do not weaken the asset gate, do not introduce full-character state frames, and keep PR #36 Draft until the full formal rig and real-Windows visual acceptance are complete.
