# G006 — Final Video QA & Delivery Receipt v1

Docs-only architecture task. Do not implement code.

## Goal
Design C010 deterministic final-video QA and immutable delivery receipt after C009 mastered output.

Audit actual current contracts and design:
1. What artifact is QA'd: C009 master, or C004 fallback when no post-production needed.
2. Deterministic checks:
   - file exists / ordinary / managed root
   - SHA/bytes
   - MP4 readability
   - codec/pixel format
   - width/height/fps
   - duration vs C005 target runtime with explicit tolerance
   - audio track presence/absence consistent with narration_required
   - audio sample rate/channels
   - no unexpected extra streams
3. What can be checked for overlay/caption presence without fragile visual AI.
4. Whether AI quality evaluation belongs later and must not gate deterministic v1.
5. FinalArtifactReceiptV1 fields and digests.
6. source lineage:
   Goal -> Creative -> Production -> C004/C008/C007 -> C009 -> receipt
7. restart/idempotency/conflict
8. Goal Center projection:
   ready/open artifact
   QA failure
   fallback behavior
9. local catalog/artifact lookup
10. export/publishing boundary remains future work.

## Boundaries
- docs only
- no publishing
- no cloud
- no arbitrary ffprobe/ffmpeg commands
- no C004/C009 implementation changes
- no UI code
- no ProductionPackage mutation

## Deliver
docs/architecture/video/G006_FINAL_VIDEO_QA_RECEIPT_V1.md

Must end with:
READY_TO_IMPLEMENT
NEXT IMPLEMENTATION SLICE
FILES OWNERSHIP
TESTS
BLOCKERS
