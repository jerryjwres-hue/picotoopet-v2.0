# Maotai v2 visual rework checkpoint

Current visual acceptance remains blocked by a material-consistency problem, not by packaging or motion-state correctness.

## Confirmed

- PR #36 remains Draft on `feature/maotai-natural-motion-v2`.
- The limb placeholders were upgraded from 3–4-color flat fills to anti-aliased furry textures.
- Visual snapshot 52 rendered successfully after that change.
- The remaining highest-impact visual defects are the low-detail head shell, redundant flat chest overlay, flat muzzle base, and segmented tail material.

## Next focused pass

1. Replace `head.png` with a high-detail neutral fur shell while retaining independent eyes, pupils, muzzle, mouth, ears, and headphones.
2. Make `chest_fur.png` transparent because `torso_neutral.png` already contains the higher-quality chest coat.
3. Replace `muzzle.png` with a textured neutral muzzle that keeps the nose but leaves mouth expression to the independent mouth layers.
4. Re-render deterministic idle/work/sleep/run snapshots and reject the pass if face layers duplicate or the head/torso seam becomes more obvious.
5. Only after the face/body material pass succeeds, rework the 3-piece tail with overlapping furry segments.

This checkpoint intentionally does not change runtime behavior, Core/Worker/task state, or release packaging.
