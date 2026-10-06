# Maotai v2 design-fidelity root cause

Status: active visual rework. PR #36 stays Draft until the real Windows WPF pet passes visual acceptance.

## What went wrong

The current visual gap is not an installer problem and not one bad pivot. It is a production-chain mismatch across art references, generated structural sprites, renderer composition, and acceptance gates.

### 1. Identity reference and rig geometry reference were mixed

The production plan previously selected different primary references for different part families. That allowed torso, limbs, tail, face, and accessories to inherit different camera/material cues.

The rig design sheet also carries construction information. Treating it as character identity can leak socket/stump/exploded-rig semantics into visible art.

Correction:

- `03_working_happy.png` is the completed-character identity/material/camera anchor.
- `01_maotai_rig_design_sheet.png` is geometry guidance only.
- Rig geometry may guide pivot, attachment location, overlap, and component extent, but never visible socket/stump/ring/cuff geometry.
- All organic components share one camera, coat palette, fur strand scale, lighting direction, and material response.

### 2. Structural outputs were technically valid but semantically wrong

Several current structural PNGs are valid transparent files but visually behave like texture plates or construction pieces:

- torso variants contain visible limb socket/stump geometry;
- upper/lower leg art reads as long rectangular or column-like patches;
- tail segments do not share the same soft fur-edge/material quality as the torso;
- the assembled result therefore exposes the rig instead of hiding the rig inside continuous fur.

The existing PNG gate checks decode, density, alpha, border padding, and manifest membership. Those checks cannot prove anatomical silhouette, fur continuity, or design identity.

Correction:

- structural generation prompts explicitly forbid sockets, stumps, rings, cuffs, mechanical connectors, and hard rectangular plates;
- structural output needs a silhouette/organic-quality gate before promotion;
- generated families are accepted only after assembly preview, not as isolated PNGs alone.

### 3. Runtime renderer currently hides the designed two-bone anatomy

The design specifies `Upper -> Lower -> Paw` for every leg. The current renderer stretches the upper sprite from shoulder toward the paw and forces every lower segment invisible. Locomotion also hides complete rear-leg layers and narrows moving paws to avoid overlaps.

Those are emergency visual workarounds. They convert a two-bone natural-motion rig into a one-column paper-puppet silhouette.

Correction after structural art replacement:

- render Upper, Lower, and Paw from the actual IK pose;
- hide joints using authored fur overlap and Z-order, not by deleting the lower leg;
- keep rear-leg depth through three-quarter-view occlusion rather than hiding whole limbs;
- remove large anisotropic width compression used to compensate for bad sprites.

### 4. Display calibration drifted too far from manifest proportions

Some runtime display boxes are substantially enlarged or compressed relative to manifest proportions. That can hide a seam locally while increasing global head/body/leg proportion drift.

Correction:

- manifest dimensions/pivots remain the authoritative art-space contract;
- structural display calibration must preserve native aspect ratio;
- large one-axis corrections are treated as an asset defect, not a renderer tuning tool.

### 5. “Visual snapshot success” was not a design-fidelity pass

The current snapshot smoke verifies state, visibility, prop placement, and several workaround-specific invariants. It does not compare against a canonical character design, and some assertions explicitly require hidden lower legs and narrowed paws.

Therefore a green snapshot can coexist with a visually unacceptable pet.

Correction:

- retain deterministic WPF snapshots as evidence generation;
- stop treating smoke success as final visual approval;
- add design-fidelity contracts at art-plan and structural-asset layers;
- final acceptance is the actual WPF assembled pet in Idle, Work, Sleep, and locomotion, followed by continuous real-Windows animation inspection.

## Correction order

1. Lock identity/material reference separately from rig geometry reference. **Implemented and contract-tested.**
2. Add structural silhouette/organic-quality rejection before staging.
3. Replace structural asset families, starting with torso + front legs, and verify each family in real WPF assembly.
4. Restore the real `Upper -> Lower -> Paw` renderer path and remove hide/compression workarounds.
5. Re-run WPF smoke, warnings-as-errors, published self-test, installer lifecycle if runtime binaries changed, and deterministic visual snapshots.
6. Keep PR #36 Draft until the actual assembled pet is visually accepted.

## Test evidence

The first design-fidelity RED run intentionally produced exactly three failures while the existing suite otherwise remained healthy:

- missing explicit identity anchor;
- missing structural no-socket/stump prompt contract;
- missing per-job design-fidelity metadata.

The refined RED run then proved the second root cause: the rig sheet was still acting as identity anchor. It failed exactly on the identity/geometry split while the remaining regression suite continued to pass.

The production art-plan builder has now been changed so the completed-character reference owns identity/material/camera and the rig sheet is geometry guidance only. Subsequent Windows contract/security CI is the gate for this correction.
