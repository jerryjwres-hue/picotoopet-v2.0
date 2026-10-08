# G004 — Post-production Master Compositor v1

Docs-only architecture task. Do not implement code.

## Goal
Design the C009 implementation-ready post-production master compositor using the actual current architecture:

- C004 produces verified visual-only MP4
- C007A Core NarrationPlan exists
- C007B Windows local narration WAV artifacts are being implemented
- C008A/A2 Core CaptionOverlayPlan/API exists
- C008B Windows drawtext overlay renderer is being implemented
- C005 owns frozen timeline/output profiles
- ProductionPackage remains visual Production truth and must not be polluted

## Must decide

1. What is the exact C009 input graph?
   - C004 source MP4
   - C008B derived overlay MP4 when overlays exist
   - C007B narration segment WAV artifacts
   - C005/C007/C008 digests
2. Should C009 consume C008B's derived MP4, or should it reuse the same drawtext primitive in one final FFmpeg pass to avoid double re-encoding?
   - choose one v1 architecture based on quality, restart safety and minimal duplication
3. How narration segments become one aligned audio timeline:
   - silence gaps
   - start_ms/end_ms
   - segment duration shorter than window
   - no silent truncation if longer
4. Fixed audio format / sample rate / channels
5. Fixed mux/mix policy
6. What happens when narration_required=false
7. Captions are currently empty absent a trusted transcript; overlays are authored on-screen text
8. Closed FFmpeg command/filter authority
9. Managed artifact root + immutable manifest
10. digest identity / restart reuse / conflict behavior
11. source SHA re-verification
12. timeout/cancel/partial cleanup
13. how C009 output becomes the actual "mastered final video" without modifying C004
14. how Goal Center should later prefer mastered artifact when present without breaking C004 fallback
15. what C010 QA/receipt should validate

## Explicit boundaries
- no code implementation
- no second Production lifecycle
- no ProductionPackage mutation
- no arbitrary FFmpeg filter/path/command
- no C004 modification
- no C007B modification
- no C008B modification
- no UI implementation
- no publishing

## Deliver
docs/architecture/video/G004_POSTPRODUCTION_COMPOSITOR_V1.md

Must include:
- CURRENT FACTS
- ARCHITECTURE DECISION
- MASTER INPUT CONTRACT
- MASTER ARTIFACT CONTRACT
- DATA FLOW
- FFmpeg BOUNDARY
- AUDIO TIMELINE RULES
- OVERLAY INTEGRATION RULES
- RESTART/IDEMPOTENCY
- SECURITY
- ERROR MODEL
- FILE OWNERSHIP
- TEST MATRIX
- IMPLEMENTATION SLICES
- AGENT RECOMMENDATION
- READY_TO_IMPLEMENT
- BLOCKERS
