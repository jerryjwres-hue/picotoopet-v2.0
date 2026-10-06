# G002 — Captions & Text Overlay v1 Architecture

Docs-only architecture task. Do not implement code.

Goal:
Prepare C008 implementation-ready design for deterministic captions/text overlays after C005 timeline and C007 narration planning, without changing C006A TEXT_CARD semantics or C004 assembly.

Audit real repository:
- CreativeScriptResult / ScriptBeat.on_screen_text / voiceover
- ShotPlan text_reference
- C005 ProductionPlan timing
- C004 FinalVideoAssemblyService
- new C007A NarrationPlan
- current Windows FFmpeg/media helpers and security boundaries

Must distinguish:
- TEXT_CARD render intent = full visual shot/card
- captions = timed lower-third/subtitle track over existing video
- text overlay/title = deterministic overlay on existing timeline
Do not merge these concepts.

Design:
1. CaptionPlanV1 / TextOverlayPlanV1 or one minimal bounded contract.
2. Timing source and beat/shot mapping.
3. Source priority: explicit on_screen_text, later narration transcript, no AI invention in v1.
4. Closed style_profile_id allowlist.
5. font policy with no arbitrary font path.
6. Windows deterministic rendering boundary.
7. sidecar subtitle option vs burned-in overlay; choose v1 and explain.
8. provenance/digest/restart reuse.
9. interaction with future C009 compositor; do not mutate C004.
10. failure behavior: captions required vs optional.
11. accessibility/export implications without overdesign.
12. likely modules/files.
13. forbidden files.
14. tests and acceptance criteria.
15. implementation slices and agent recommendation.

Constraints:
- no code implementation
- do not touch C006A files
- do not touch C007A files
- do not modify C004
- no arbitrary FFmpeg filter/string authority
- no arbitrary font/path/provider/model authority
- local-first, deterministic

Deliver:
docs/architecture/video/G002_CAPTIONS_OVERLAY_V1.md

End with:
READY_TO_IMPLEMENT: yes/no
NEXT IMPLEMENTATION SLICE
BLOCKERS
FILES OWNERSHIP
