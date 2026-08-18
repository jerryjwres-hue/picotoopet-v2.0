# Maotai v2 art staging continuity

This directory is non-runtime staging only. Runtime assets live under `windows/desktop/src/PicotooPet.Desktop/Assets/Maotai/V2` and must stay manifest-only.

## Current source of truth

- Repository: `jerryjwres-hue/picotoopet-v2.0`
- Branch: `feature/maotai-natural-motion-v2`
- Draft PR: `#36` — keep Draft, do not merge/Ready.
- Software/motion gates are green up to the formal raster asset gate.
- Continuity rule: every useful art candidate is committed here before runtime promotion so a new chat can resume without regenerating prior work.
- Windows Prebuilt #2353 proved `torso_neutral.png` valid and advanced the hard blocker to `torso_crouch.png`.
- Windows Prebuilt #2362 proved `torso_crouch.png` valid and advanced the hard blocker to `torso_stretch.png` with 0 build warnings and 0 build errors.

## `torso_neutral.png` — CI-confirmed

- logical contract: `92 x 78`
- pivot: `(46, 41)`
- joint overlap: `20 px` logical
- runtime pixels: `184 x 156`, RGBA
- source: independent torso-only generation, never cropped from a full character
- formal runtime path: `windows/desktop/src/PicotooPet.Desktop/Assets/Maotai/V2/torso_neutral.png`
- binary repair commit: `ba79c343d4b8edd745288b77cbd73f44b7b668b2`

## `torso_crouch.png` — CI-confirmed

- logical contract: `96 x 72`
- pivot: `(48, 39)`
- joint overlap: `20 px` logical
- runtime pixels: `192 x 144`, RGBA
- source: deformation of the already-valid independent torso-only neutral asset; never cropped from a full-character render
- promotion commit: `6477f8de4fb9dad4ee8da23904f2aa827b44c31d`
- CI evidence: Windows Prebuilt #2362 passed crouch and failed only because the next required asset, `torso_stretch.png`, was absent.

## `torso_stretch.png` — promoted candidate, pending CI

- logical contract: `90 x 86`
- pivot: `(45, 45)`
- joint overlap: `20 px` logical
- runtime pixels: `180 x 172`, RGBA
- visible alpha bbox: `x=35..149, y=5..164`
- all four outer alpha borders are zero
- source: affine deformation of the already-valid independent torso-only neutral asset; never cropped from a full-character render
- pose policy: narrowed and lengthened around the manifest pivot while preserving the same charcoal-gray/white Maotai torso pattern and hidden fur overlap roots
- transport policy: reduced to 7 representative RGB colors with binary alpha only to fit the GitHub connector safe binary-transfer size; geometry, pivot and formal RGBA container stay unchanged
- local SHA-256: `9d3cc6a0c5a52976f9b1308c2788684b4b054e612d47409536cf57e15aff1d7d`
- Git blob SHA verified locally and remotely: `a796f6ca7d81c6f187befc0b67458a408ea4f442`
- staging copy: `torso_stretch_candidate.png`
- formal runtime path: `windows/desktop/src/PicotooPet.Desktop/Assets/Maotai/V2/torso_stretch.png`

## Rejected paths preserved to prevent repetition

- `torso_candidate_v1_preview.png`: rejected — too tall/narrow, alpha edge issue, hollow socket geometry.
- Canva Magic Layers design `DAHSm6Tmcyc`: rejected — single-layer non-uniform resize could not repaint sockets; transaction cancelled.
- atlas/reference boards are reference only; never crop atlas/full-character renders into runtime parts.
- generation ids `89bf9df4-8313-41cc-bfb4-615e7a5b8e60`, `b926d3f5-3039-40ea-88eb-bc23b9f46616`, `ca81c0bd-bcab-45fd-b254-0b8632d0e6e6`, `c6e98715-95a5-4346-959d-c007c2b53159`: rejected because the generator drifted to atlas/concept-board/full-character output instead of a valid torso-only part.
- two long-Base64 stretch upload attempts were rejected before branch mutation because returned Git blob SHA did not match the locally computed Git blob SHA. Do not reuse those orphan blobs.

## Exact next action

1. Fast-forward the branch with the verified `torso_stretch.png` promotion commit.
2. Run Windows/Prebuilt and verify the formal raster gate passes stretch; expected next blocker is `chest_fur.png`.
3. Produce `chest_fur.png` at `124 x 104` (2x the `62 x 52` logical contract), pivot `(31,18)`, joint overlap `16`, using only the independent torso visual source rather than a full-character crop.
4. Continue in manifest order, staging every meaningful accepted/rejected candidate before runtime promotion.
5. Do not weaken the asset gate, do not introduce full-character state frames, and keep PR #36 Draft until the full formal rig and real-Windows visual acceptance are complete.
