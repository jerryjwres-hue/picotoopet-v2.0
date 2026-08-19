# Maotai v2 art staging continuity

This directory is the non-runtime continuity/staging record for the Maotai v2 raster rig. Runtime assets live under `windows/desktop/src/PicotooPet.Desktop/Assets/Maotai/V2` and remain manifest-only.

## Source of truth

- Repository: `jerryjwres-hue/picotoopet-v2.0`
- Branch: `feature/maotai-natural-motion-v2`
- Draft PR: `#36` — keep Draft; do not merge or mark Ready.
- `MaotaiAssetManifest.cs` is authoritative for file names, logical dimensions, pivots and overlap values.
- Every useful candidate/checkpoint is kept in GitHub before runtime promotion so a new chat can resume without regenerating prior work.
- Complete-character preview/state images are never used as runtime cut sources. Modular independently rendered part cells may be used as production sources after isolation and validation.

## Formal raster status — 44/44 present and Windows gate green

The 44-file formal Maotai v2 raster set is now complete in:

`windows/desktop/src/PicotooPet.Desktop/Assets/Maotai/V2`

Earlier CI-confirmed assets from this pass:

- `torso_neutral.png`: Prebuilt #2353
- `torso_crouch.png`: Prebuilt #2362
- `torso_stretch.png`: Prebuilt #2372
- `chest_fur.png`: Prebuilt #2378

The remaining 17 missing files were promoted together in commit:

- `2b84f3d2e764e58bee594166eb109c044685434f`

Those 17 are:

- `head.png`, `muzzle.png`
- `front_left_upper.png`, `front_left_lower.png`, `front_right_upper.png`, `front_right_lower.png`
- `hind_left_upper.png`, `hind_left_lower.png`, `hind_right_upper.png`, `hind_right_lower.png`
- `tail_base.png`, `tail_mid.png`, `tail_tip.png`
- `headphone_band.png`, `headphone_left.png`, `headphone_right.png`
- `laptop.png`

A subsequent one-shot normalization pass rewrote the formal PNG streams cleanly and enforced the exact 2px inner transparent margin used by `MaotaiAssetPixelValidationSmokeTests` across all 44 assets. The resulting asset commit is:

- `5560c114b5af65e70b15d92bd25151668732a6d6`

The temporary promotion/normalization workflows were removed after use; they are not part of the final runtime architecture.

## Windows verification — current authoritative evidence

Commit `cea3b23077c752216177f0c9c2563862c3e5dc3f` (temporary normalization workflow removed) produced the current full validation evidence:

- Windows Control Center Slice D CI #2481: **success**
  - 325 contract/security checks passed
  - WPF build passed with warnings-as-errors
  - published `--self-test` passed
  - this means the full 44-file raster asset gate passed: PNG decode, >=2x density, alpha, nonempty visible bbox, 2px safety margin, manifest/publish mapping, plus existing motion/behavior smoke tests
- Phase 2.3 Slice D Windows Prebuilt Release #2474: **success**
  - 49 release contract checks passed
  - formal WPF build + self-test passed
  - delivery invariants passed
  - installer goal contract passed
  - Windows PowerShell 5.1 install / upgrade / recovery / rollback lifecycle passed
  - formal installer artifact upload passed

Therefore the project is no longer blocked on missing/corrupt raster assets or the Windows installer lifecycle.

## Restart-safe art checkpoints

The candidate data that produced the batch is still preserved in GitHub:

- `docs/art/maotai-v2/staging/2026-08-18/batch1_missing16.mtr.b85`
- `docs/art/maotai-v2/staging/2026-08-18/restore_batch1_missing16.py`
- `docs/art/maotai-v2/staging/2026-08-18/batch1_missing17.mtr.b85`
- `docs/art/maotai-v2/staging/2026-08-18/restore_batch1_missing17.py`

The 17-file checkpoint includes the independent `head.png` candidate at its frozen `156 x 140` @2x contract. The other batch pieces can be restored from the same pack without regenerating art after a chat restart.

## Important production decisions already made

- `head.png` authoritative manifest contract is logical `78 x 70`, pivot `(39,42)`, overlap `20`, minimum @2x `156 x 140`.
- upper/lower limb pieces do not include the already-separate paw sprites in the formal rig.
- tail source pieces were horizontally aligned so the root side matches the manifest's right-side tail pivots.
- headset source is headset-only, then split to band/left/right; no complete-character cutting.
- existing ears, eyes, pupils, brows, five mouth states, four paws, drink and shadow remain separate layers.
- early long-Base64 manual PNG uploads are not used as the preferred transport path because they proved vulnerable to truncated streams; GitHub-side checkpoint restoration + clean PNG rewrite is the proven path.

## Rejected paths — do not repeat

- `torso_candidate_v1_preview.png`: rejected for tall/narrow proportions, edge issue and hollow socket geometry.
- Canva single-layer torso resize: rejected because it could not repaint socket geometry.
- `head_candidate_v1.png`: rejected because a torso texture deformed into a head still read as a distorted torso.
- repeated free image-generation attempts that drift into promotional/asset boards should not be repeated as the primary path for isolated runtime parts.
- do not crop complete-character preview/state renders into runtime parts.

## Exact next action — visual acceptance, not more missing-file work

1. Do **not** restart raster production or repeat the 44-file gate; it is green.
2. Produce a real Windows-rendered visual snapshot/capture of the assembled Maotai v2 component for at least `Idle`, `Work`, `Sleep`, and one locomotion state (`Walk`/`Run`).
3. Judge assembled visual quality: head/ear/eye/muzzle alignment, limb overlap, tail chain, headset/laptop placement, silhouette, fur continuity and state-to-state pose readability.
4. If a visual defect is found, adjust only the offending asset/transform and rerun the existing Windows gates.
5. Keep PR #36 Draft until real-Windows visual acceptance is complete.
