# Maotai v2 art staging continuity

This directory is non-runtime staging only. Runtime assets live under `windows/desktop/src/PicotooPet.Desktop/Assets/Maotai/V2` and must stay manifest-only.

## Current source of truth

- Repository: `jerryjwres-hue/picotoopet-v2.0`
- Branch: `feature/maotai-natural-motion-v2`
- Draft PR: `#36` — keep Draft, do not merge/Ready.
- Software/motion gates are green up to the formal raster asset gate.
- Continuity rule: every useful art candidate is committed here before runtime promotion so a new chat can resume without regenerating prior work.
- Windows Prebuilt #2353 proved `torso_neutral.png` valid.
- Windows Prebuilt #2362 proved `torso_crouch.png` valid with 0 build warnings and 0 build errors.
- Windows Prebuilt #2372 proved `torso_stretch.png` valid with 0 build warnings and 0 build errors, then stopped only because `chest_fur.png` was absent.
- Windows Prebuilt #2378 proved `chest_fur.png` valid with 0 build warnings and 0 build errors, then stopped only because `head.png` was absent.

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
- source: deformation of the valid independent torso-only neutral asset
- promotion commit: `6477f8de4fb9dad4ee8da23904f2aa827b44c31d`

## `torso_stretch.png` — CI-confirmed

- logical contract: `90 x 86`
- pivot: `(45, 45)`
- joint overlap: `20 px` logical
- runtime pixels: `180 x 172`, RGBA
- visible alpha bbox: `x=35..149, y=5..164`
- source: affine deformation of the valid independent torso-only neutral asset
- verified Git blob SHA: `a796f6ca7d81c6f187befc0b67458a408ea4f442`
- promotion commit: `56229745b813751cd4640348f5bee838d5209065`
- CI evidence: Prebuilt #2372 advanced the hard blocker to `chest_fur.png`.

## `chest_fur.png` — CI-confirmed

- logical contract: `62 x 52`
- pivot: `(31, 18)`
- joint overlap: `16 px` logical
- runtime pixels: `124 x 104`, RGBA
- visible alpha bbox: `x=38..86, y=10..100`
- all four outer alpha borders are zero
- visual role: independent central white chest/ruff overlay attached to the Chest bone; no head, legs, paws, tail, props, text or complete-character pixels
- source: reconstructed only from the central white chest/ruff region of the already-valid independent torso-only source; never cropped from a full-character render
- transport policy: 8 representative RGB levels with binary alpha to fit the connector safe binary-transfer size; geometry and manifest alignment stay unchanged
- Git blob SHA verified locally and remotely: `63f8d0ed08f69c9687b5b75865e4e1303100579f`
- promotion commit: `b43d5bfacc72178bd9e7a474fa6aa597329a4487`
- CI evidence: Prebuilt #2378 passed chest and advanced the hard blocker to `head.png`.

## `head.png` — current production target

- logical contract: `98 x 84`
- pivot: `(49, 48)`
- joint overlap: `18 px` logical
- required runtime pixels: at least `196 x 168`, RGBA
- role: independent head shell / forehead / cheek-fur base only; do not bake in separate ears, pupils, expression mouths or props.
- existing independent ear/eye/pupil/mouth layers remain separate and must continue to drive expression and animation.
- Canva rig reference design `DAHSZ9UjHCw` contains native head/face source assets (`MAHSZ73u7SM` 230x209 and `MAHSZ3uLUf0` 248x323), but they are reference/source only; they include face/ear features and must not be copied directly as the final runtime `head.png`.

## Rejected paths preserved to prevent repetition

- `torso_candidate_v1_preview.png`: rejected — too tall/narrow, alpha edge issue, hollow socket geometry.
- Canva Magic Layers design `DAHSm6Tmcyc`: rejected — single-layer non-uniform resize could not repaint sockets; transaction cancelled.
- atlas/reference boards are reference only; never crop atlas/full-character renders into runtime parts.
- generation ids `89bf9df4-8313-41cc-bfb4-615e7a5b8e60`, `b926d3f5-3039-40ea-88eb-bc23b9f46616`, `ca81c0bd-bcab-45fd-b254-0b8632d0e6e6`, `c6e98715-95a5-4346-959d-c007c2b53159`: rejected because the generator drifted to atlas/concept-board/full-character output instead of a valid independent part.
- long-Base64 orphan blobs are never attached when GitHub returned blob SHA does not exactly match the locally computed Git blob SHA. Chest orphan blob `6747ed2e80a12a2b86843e9d0fb09b33544589a0` is rejected.
- `head_candidate_v1.png`: rejected before GitHub mutation — torso-only texture was deformed into a head-like silhouette, but the result still read visually as a distorted torso and retained a socket-like artifact. Do not promote or reuse it as formal `head.png`.

## Exact next action

1. Produce a true independent `head.png` at the frozen `98 x 84` logical / `196 x 168` @2x contract with transparent safe borders and 18 px logical neck overlap.
2. Validate RGBA decode, transparent edges, nonempty alpha bbox, no crop, dimensions, and pivot-compatible composition before any branch mutation.
3. Verify Git blob SHA locally vs remotely before attaching the PNG; never attach a truncated binary blob.
4. Promote staging + formal runtime copy in one fast-forward commit, then let Windows/Prebuilt expose the next missing manifest asset.
5. Continue in manifest order and keep PR #36 Draft until the full formal rig and real-Windows visual acceptance are complete.
