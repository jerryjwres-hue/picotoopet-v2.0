# Issue #78 — torso neutral acceptance and Windows release reproduction

## Current verdict

**BLOCKED — DO NOT RELEASE.** This file intentionally does not replace any official PNG.

- Frozen G007 Full builder evidence: [run 38665576012](https://github.com/jerryjwres-hue/picotoopet-v2.0/actions/runs/38665576012).
- Frozen G007 source pin: `ec468b9975a3b1cd706e6e74223bfb05f7733a86`; the old pin cannot observe this visual branch automatically.
- Visual work stays on `fix/maotai-visual-fidelity-isolated`; it must not modify C011, G005, C012, or G007 owner refs.
- Official runtime path: `windows/desktop/src/PicotooPet.Desktop/Assets/Maotai/V2/torso_neutral.png`.
- Staged study: `docs/art/maotai-v2/staging/issue-78/torso_neutral.png`.
- Existing `MaotaiAssetPixelValidationSmokeTests` rejects the production torso Git blob and 19 additional reviewed placeholder-quality blobs; keep all these gates intact.

## Required visual contract

1. Independently authored one-piece RGBA torso, without complete-character cropping or hidden snapshots.
2. Manifest `TorsoNeutral`: 92 × 78 logical, 184 × 156 native pixels minimum, pivot (46, 41), overlap 20.
3. Natural, continuous, furry neck/shoulder/hip silhouettes. No circular rings, tubes, mechanical joint sockets, rectangular white patches, or cut edges.
4. Outer transparent boundary, nonempty alpha, no full-background fill, at least 2× pixel density and sufficient visible bounding box.
5. Rig and atlas semantics must preserve correct Z-order and overlap without modifying the Natural Motion engine.
6. After promotion, verify app resource link to `ui-assets/maotai/v2`, `CopyToPublishDirectory=Always`, source/publish hash parity and install-package extraction.
7. Capture and independently review Idle, Work, Sleep and Run WPF renders against the August 15 canonical identity references.
8. Re-run the exact C011 Full release builder on a **new, composed, immutable source SHA**. A G007 workflow success cannot be substituted for an FV-033 published-app PASS.

## Reproducibility limitation

The currently checked-out historical visual branch builder has no `-ValidationScope` parameter. Its native `windows-phase2-release.yml` runs the original Windows release script and formal smoke, but that run is **not equivalent** to the later C011 `-ValidationScope Full` implementation.

The snapshot CI overlays the staged PNG **in runner LOCALAPPDATA only** and uploads WPF visual evidence. That overlay is never copied into formal runtime source or the official release package.

No release acceptance is asserted unless the exact Full builder returns PASS for an immutable source including all approved assets.
