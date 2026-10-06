# Maotai v2 visual rework checkpoint

The placeholder-material and segmented-tail blockers are now resolved in deterministic WPF evidence. Automated build, packaging, installer, and lifecycle gates are green on the accepted visual head.

## Confirmed

- PR #36 remains Draft on `feature/maotai-natural-motion-v2`.
- Accepted automated-validation head: `06eac7256b1bdceef53e3aa254ba1e5a506cbc60`.
- Motion architecture and interruption continuity remain under deterministic WPF smoke coverage.
- The limb placeholders use anti-aliased furry textures instead of flat fills.
- `chest_fur.png` remains packaged for manifest compatibility but is hidden at runtime because `torso_neutral.png` already owns the higher-quality chest coat.
- `head.png` uses a transparent charcoal/white fur shell while eyes, pupils, muzzle, mouth, ears, and headphones remain independent layers.
- The head silhouette satisfies the canine-jaw contract: the 85% jaw sample is narrower than the 55% mid-head sample.
- `muzzle.png` uses a textured neutral muzzle while mouth expression remains independent.
- TailBase -> TailMid -> TailTip remains a real local hierarchy with independent spring headings.
- Tail draw order is Base -> Mid -> Tip, while all tail art remains behind the torso.
- Tail display links are visually tucked to 60% of the logical local connector distance; the Motion Engine offsets and canonical hierarchy resolver remain unchanged.
- The final tail assets use one charcoal/cream material family with soft alpha edges and hidden overlap.
- Deterministic Visual Snapshot #271 rendered Idle / Work / Sleep / Run successfully with no duplicated chest bib, duplicated face layer, or open black tail seams.
- Maotai Motion Contract CI #46 passed, including the visual-overlap regression contract.
- Windows Control Center Slice D CI #3120 passed:
  - contract/security tests
  - legacy Task Center binding reproduction
  - WPF diagnostic smoke
  - warnings-as-errors WPF build
  - published Control Center self-test
- Windows Prebuilt Release #3113 passed:
  - release analyzer and goal-integrity contracts
  - build/analyze/publish/self-test
  - approved native WPF delivery invariants
  - actual installer goal contract
  - packaged install / upgrade / recovery / rollback lifecycle
  - formal installer and lifecycle evidence upload
- Mac Core and Mac Worker gates also pass on the same head.

## Current visual decision

The face/body/tail structural-material pass is accepted for automated validation. Tail no longer reads as three disconnected plates in the deterministic Work frame: adjacent pieces overlap as one continuous fur mass while preserving independent spring headings.

This is still not permission to merge PR #36. Deterministic snapshots prove composition and regression constraints, but they do not replace human inspection of continuous animation on a real Windows desktop.

## Remaining acceptance

Perform one real-Windows continuous-animation pass on the exact accepted head and reject the build for any visible snap, seam, floating layer, clipping, or prop collision.

Minimum sequence:

1. Idle -> Look -> Idle, including breathing and ear/tail micro-motion.
2. Work settle -> typing -> tired -> yawn -> recover.
3. Pat/Paw interaction during normal work and during mid-yawn interruption.
4. Offline -> sit -> lie down -> sleep, then wake/recover.
5. Walk/Run transitions in both facing directions, including paw contact and rear-leg depth.
6. Observe the three-piece tail continuously during work, locomotion, and state transitions; no black seam may open between Base/Mid/Tip.
7. Verify laptop, drink, headphones, mouth/eyes, and tail keep correct depth ordering during motion.
8. If the real-Windows pass is clean, record that evidence before changing PR #36 out of Draft or merging it.

This checkpoint does not change Core/Worker/task state or business-write behavior.
