# Maotai v2 art staging continuity

This directory is non-runtime staging only. Runtime assets live under `windows/desktop/src/PicotooPet.Desktop/Assets/Maotai/V2` and must stay manifest-only.

## Current source of truth

- Repository: `jerryjwres-hue/picotoopet-v2.0`
- Branch: `feature/maotai-natural-motion-v2`
- Draft PR: `#36` — keep Draft, do not merge/Ready.
- Software/motion gates are green up to the formal raster asset gate.
- Continuity rule: every useful art candidate is committed here before runtime promotion so a new chat can resume without regenerating prior work.

## `torso_neutral.png` — promoted, binary transport repaired

- logical contract: `92 x 78`
- pivot: `(46, 41)`
- joint overlap: `20 px` logical
- runtime pixels: `184 x 156`, PNG color type RGBA
- outer border alpha: zero on all four edges in the local validated candidate
- source: independent torso-only generation, never cropped from a full character
- repair: hollow neck/limb sockets replaced with continuous fluffy overlap roots using texture sampled only from the torso-only source
- first GitHub promotion at `3401ac0e...` had a malformed binary caused by long Base64 transfer; Windows Prebuilt #2347 correctly failed `v2 资产不是有效 PNG：torso_neutral.png`
- replacement Git blob: `c846728421457c726741513c4f0339aef2039eb8`; connector binary read fails on byte `0x89`, confirming the PNG signature byte is present before branch update
- compact replacement local SHA-256: `4e807ca617533859853f40f8452b4112a31cd907188ba18c93b22ab0056e586b`
- staging copy: `torso_candidate_v2.png`
- formal runtime path: `windows/desktop/src/PicotooPet.Desktop/Assets/Maotai/V2/torso_neutral.png`

## Rejected paths preserved to prevent repetition

- `torso_candidate_v1_preview.png`: rejected — too tall/narrow, alpha edge issue, hollow socket geometry.
- Canva Magic Layers design `DAHSm6Tmcyc`: rejected — single-layer non-uniform resize could not repaint sockets; transaction cancelled.
- atlas/reference boards are reference only; never crop atlas/full-character renders into runtime parts.
- generation ids `89bf9df4-8313-41cc-bfb4-615e7a5b8e60`, `b926d3f5-3039-40ea-88eb-bc23b9f46616`, `ca81c0bd-bcab-45fd-b254-0b8632d0e6e6`: rejected because generator drifted to atlas/concept-board output instead of torso-only edits.

## Exact next action

1. Replace both staging and formal torso blobs with verified `c8467284...` and fast-forward the branch.
2. Run Windows/Prebuilt and confirm the Gate advances beyond `torso_neutral.png`.
3. The next missing manifest asset becomes the new hard blocker; produce it independently with the same Maotai visual language.
4. Save every meaningful candidate/decision in GitHub staging/continuity before proceeding.
5. Do not weaken the asset gate and do not add full-character state frames to the formal V2 directory.
