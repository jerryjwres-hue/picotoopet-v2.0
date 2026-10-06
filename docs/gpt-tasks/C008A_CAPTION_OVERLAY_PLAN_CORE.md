# C008A — Core CaptionOverlayPlan v1

Architecture source:
origin/design/captions-overlay-v1:docs/architecture/video/G002_CAPTIONS_OVERLAY_V1.md

## Objective
Implement only the deterministic Core plan compiler/digest/tests for post-production captions/text overlays.

No API. No Windows renderer. No C004 changes.

## Branch
feature/caption-overlay-plan-core-v1
Base includes C007A postproduction package and C005 ProductionPlan.

## Semantic boundary
Keep these distinct:
- TEXT_CARD = full Production shot
- caption = narration/speech subtitle
- overlay/title = authored on-screen text over existing video

V1 source authority:
- overlay/title only from ScriptBeat.on_screen_text
- ShotPlan.text_reference alone is NOT post-production authority
- captions require a future explicit trusted transcript source; do not derive captions from voiceover text alone in C008A
- no AI invention

## Add only
- src/picotoopet_core/postproduction/captions_overlay.py
- tests/postproduction/test_captions_overlay_plan.py

Do not edit __init__, narration.py, routes, app.py, Production files, Windows files.

## Contract
Create strict frozen CaptionOverlayPlanV1 with bounded closed fields sufficient for:
- production_job_id
- creative_package_id/digest
- production_plan_digest
- target_runtime_ms
- output_profile_id
- caption_style_profile_id = caption.lower-third.v1
- overlay_style_profile_id = overlay.title-safe.v1
- font_profile_id = font.windows-system-sans.v1
- captions_required default false
- overlays_required derived from explicit authored overlays
- captions[]
- overlays[]

Cue identity should include:
- cue_id
- beat_id
- order
- text
- text_sha256
- start_ms
- end_ms
- cue kind where useful

No provider/model/path/font-path/filter/command/URL/executable/raw renderer parameters.

## Timing
C005 ProductionPlan is sole render timing authority.
Reconstruct beat windows deterministically from ordered tasks + ShotPlan beat mapping.

Validate:
- consecutive task order
- exact shot identity match
- known beats
- no beat reopening
- no backward beat order
- accumulated duration == target_runtime_ms
- positive bounded windows

Do not import C007A private _beat_windows.
Equivalent local helper is acceptable.

## Overlay
For each nonblank ScriptBeat.on_screen_text:
- one overlay cue spanning that beat's contiguous window
- preserve authored text exactly after bounded whitespace policy
- digest it
- no word timing inference

If the beat contains any Production task with render_intent == TEXT_CARD:
raise bounded TEXT_OVERLAY_TEXT_CARD_AMBIGUOUS.
Do not silently duplicate/suppress/reinterpret.

## Caption
C008A does not yet have a trusted transcript contract.
Therefore captions=[] and captions_required=false are valid.
Do not turn voiceover or text_reference into captions.

Design models so a later versioned trusted caption source can be added without changing overlay semantics.

## Digest
Canonical SHA-256 over complete validated plan.
Same inputs => identical plan + digest.
Changing Production plan/source/style facts => different digest.
No timestamp in digest.

## Bounded errors
Use closed codes, including:
- TEXT_PRESENTATION_NOT_READY
- TEXT_PRESENTATION_SOURCE_MISMATCH
- TEXT_PRESENTATION_TIMELINE_AMBIGUOUS
- TEXT_OVERLAY_TEXT_CARD_AMBIGUOUS
- TEXT_PRESENTATION_PROFILE_UNSUPPORTED
Errors must not leak text.

## Required tests
At minimum:
- no on_screen_text => valid empty plan
- one overlay => exact window
- multi-shot beat => spanning window
- multi-beat cumulative timing
- on_screen_text never becomes caption
- voiceover never becomes overlay
- text_reference alone produces nothing
- TEXT_CARD + on_screen_text => ambiguity
- caption-over-TEXT_CARD semantics remain conceptually allowed (no overlay false positive)
- unknown shot/beat rejected
- reopened/noncontiguous beat rejected
- task order/runtime mismatch rejected
- source identity/digest mismatch rejected
- unknown style/font profile rejected
- extra provider/model/path/filter/font-path/command fields impossible
- same inputs => same plan/digest
- changed ProductionPlan digest => changed digest
- errors do not leak text
- required overlay cannot silently disappear
- optional caption absence non-fatal

Ruff touched Python.

## Forbidden
Do not modify:
- C006A Production/TEXT_CARD files/tests
- C007A narration.py/routes/tests
- C004 final assembly/Goal files
- Windows
- S002 files
- Maotai/UI
- deploy/macos
- Natural Motion

## Acceptance
PASS when explicit authored on-screen text can be deterministically converted into a strict post-production overlay plan bound to C005 timing, with captions still empty absent a trusted transcript and TEXT_CARD collision failing closed.

## Delivery requirements
- commit all C008A changes
- push to origin/feature/caption-overlay-plan-core-v1
- do not rebase/merge/tag/release
- working tree clean

Final response only:
remote branch
remote HEAD SHA
files changed
tests
architecture notes
residual risk
git status --short
