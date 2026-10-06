# Maotai v2 recovered visual identity references

Status: **REFERENCE ONLY — NOT RUNTIME ART**

Recovered on 2026-10-06 from the PicotooPet Project Library after the original Maotai handoff archive was no longer directly available.

## Canonical identity family

The following six source images are the strongest recovered identity/style family. They share the same premium chibi Alaskan Malamute language, charcoal/white coat, warm face treatment, and blue headphone design.

| Role | Recovered Library source | Use |
| --- | --- | --- |
| Idle / greeting | `image-gen-1(6).png` | face, ears, coat, paw and headphone identity |
| Working / happy | `image-gen-2(2).png` | canonical work pose and happy expression |
| Working / tired | `image-gen-3(2).png` | tired eyes, ears, head weight and work posture |
| Working / annoyed | `image-gen-4(2).png` | annoyed facial tension and forceful typing intent |
| Rest / bath | `image-gen-5(1).png` | relaxed expression, paw pads and plush coat material |
| Offline / sleep | `image-gen-6(1).png` | curled sleeping silhouette and closed-eye expression |

These files remain in the Project Library. Current Library permissions allow visual retrieval but do not expose an authorized raw-byte materialization path, so this recovery commit intentionally does **not** fabricate or re-encode copies of those binaries.

## Secondary motion-composition family

The later 2026-08-20 set is useful for pose/composition only and must not replace the canonical identity above:

- `image-gen-2(3).png` — simplified working front pose.
- `image-gen-3(3).png` — simplified curled sleep pose.
- `image-gen-4(3).png` — simplified front-running pose.

The later set is visibly rounder and flatter than the canonical identity family.

## Production rules

1. Complete-character references are **never** runtime skeleton parts.
2. Do not crop a head, torso, leg, paw, tail, mouth, or headphone from a complete-character reference.
3. New runtime parts must be independently generated/painted/exported while matching the canonical identity family.
4. Torso and limb connection zones must be continuous fur overlap regions. Hollow sockets, circular rings, exposed tubes, or mechanical joint openings are rejected.
5. Head art must read as an Alaskan Malamute head, not a circular mascot shell.
6. Muzzle and mouth overlays must preserve real fur/skin integration. Flat rectangular muzzle patches and sticker-like mouths are rejected.
7. Limb upper/lower/paw assets must preserve a continuous furry silhouette under articulation. Narrow rectangular bars plus detached paw balls are rejected.
8. Candidate art must first enter `docs/art/maotai-v2/staging/` and be reviewed through the preview-only WPF snapshot overlay before formal promotion.
9. Passing alpha/density/manifest tests does not constitute visual acceptance. Real WPF snapshots remain mandatory.
10. Formal runtime assets remain fail-closed while their exact rejected Git blob fingerprints are present.

## Recovered-source interpretation

The recovered canonical images restore the visual target that was lost when later structural placeholder assets became the dominant repository evidence. They are provenance-safe visual references, not evidence that any current runtime PNG is approved.

The 2026-08-18 MTR1 structural checkpoints were also audited during this recovery. Their torso/head/limb components retain the same hollow-socket, round-shell and narrow-strip construction visible in the rejected runtime family, so they must not be promoted merely because they are independently encoded.
