# Maotai v2 visual rework checkpoint

Current visual acceptance is no longer blocked by the face/body placeholder-material pass. The remaining highest-impact asset-family defect is the segmented tail material/continuity.

## Confirmed

- PR #36 remains Draft on `feature/maotai-natural-motion-v2`.
- Motion architecture and interruption continuity remain under deterministic WPF smoke coverage.
- The limb placeholders were upgraded from flat fills to anti-aliased furry textures.
- `chest_fur.png` remains packaged for manifest compatibility but is hidden at runtime because `torso_neutral.png` already owns the higher-quality chest coat.
- `head.png` was replaced with a transparent charcoal/white fur shell while eyes, pupils, muzzle, mouth, ears, and headphones remain independent layers.
- The head silhouette now satisfies the canine-jaw contract: the 85% jaw sample is visibly narrower than the 55% mid-head sample.
- `muzzle.png` was replaced with a textured neutral muzzle that keeps the nose while mouth expression remains independent.
- Deterministic visual snapshot 257 rendered Idle / Work / Sleep / Run successfully with no duplicated chest bib or duplicated face layer.
- Maotai Motion Contract CI run 29 passed after the face/body correction.

## Current visual decision

The face/body pass is accepted as a structural/material correction, not as final production polish. It resolves the previous placeholder-shell blocker and is stable enough to expose the next asset-family defect without masking it with renderer workarounds.

PR #36 still must not merge until the assembled pet passes real-Windows continuous-animation acceptance.

## Next focused pass

1. Replace `tail_base.png`, `tail_mid.png`, and `tail_tip.png` as one matched fur family.
2. Keep the existing manifest dimensions, pivots, overlap margins, and independent three-bone motion.
3. Use one charcoal/cream palette, strand scale, light direction, and alpha softness across all three pieces.
4. Author generous hidden overlap so Base -> Mid -> Tip rotation does not expose hard seams.
5. Re-render deterministic Idle / Work / Sleep / Run snapshots and reject the pass if the tail reads as three separate crescents/plates.
6. After tail acceptance, re-run the full Windows WPF gate, warnings-as-errors build, published self-test, release lifecycle, and real-Windows visual inspection.

This checkpoint does not change Core/Worker/task state or business-write behavior.
