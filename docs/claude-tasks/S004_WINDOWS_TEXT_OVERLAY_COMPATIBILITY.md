# S004 — Windows Text Overlay Compatibility Spike

## Objective
Prove the exact local Windows/FFmpeg path for deterministic captions/text overlays before C008B/C009 product integration.

This is an isolated compatibility spike, not product integration.

## Branch
spike/windows-text-overlay-compatibility

## Context
Already frozen:
- C005 owns timing/output profile
- C006A owns TEXT_CARD as a full Production shot
- C008A owns Core CaptionOverlayPlan
- C004 final assembly must remain unchanged

This spike answers only:
which local FFmpeg/text rendering path is actually viable on the current Windows environment.

## Candidates to evaluate
1. FFmpeg drawtext with one frozen Windows system font path selected internally
2. FFmpeg subtitles/libass with generated temporary ASS/SRT and one frozen font policy

Do not add ImageMagick, browser/HTML rendering, cloud APIs, external font downloads, Python rendering runtimes, or arbitrary filter strings.

## Required proof
On real Windows, determine for each viable candidate:
- filter exists in installed ffmpeg
- can render UTF-8 English
- can render Chinese glyphs with an installed system font
- output WebM/MP4 is valid
- timing windows are honored
- fixed safe-area/lower-third geometry is deterministic
- no shell
- no arbitrary font/filter/path/command authority
- cancellation/timeout can be bounded
- missing glyph/font fails in a bounded way

## Implementation
Create isolated probe only, preferably:
windows/tools/PicotooPet.TextOverlayCompatibilityProbe/

Do NOT add to shipping Desktop solution.

Probe must:
- use one generated synthetic input video or fixed color source; do not need Production assets
- render an English overlay and a Chinese overlay
- exercise one timed cue window
- use fixed internally-authored filters only
- validate output exists, nonzero, ffprobe/ffmpeg-readable when available
- produce JSON report
- clean temp directory

If using a Windows system font, resolve it from a closed internal candidate list only.
Do not accept a caller-provided font path.

## Preferred result decision
Result document must end in exactly one:
- RECOMMEND_DRAWTEXT
- RECOMMEND_LIBASS
- NO_COMPATIBLE_TEXT_OVERLAY_PATH_PROVEN

Add:
docs/architecture/video/S004_WINDOWS_TEXT_OVERLAY_RESULT.md

## Explicitly forbidden
Do not modify:
- ProductionExecutionService.cs
- ProductionLocalMediaRenderer.cs
- ProductionContracts.cs
- C006A files/tests
- C006B asset files
- C007 narration files
- C008A/A2 Core files
- C004 final assembly
- Goal Center
- Maotai/UI
- deploy/macos
- Natural Motion

## Validation
If Claude's environment cannot run Windows/ffmpeg:
- still implement and push the isolated probe
- mark runtime validation UNVERIFIED
- do not fake PASS
- orchestrator will run it on real Windows

## Delivery requirements
- commit all S004 changes
- push to origin/spike/windows-text-overlay-compatibility
- do not merge/rebase/tag/release
- working tree clean

Final response only:
remote branch
remote HEAD SHA
files changed
local validation
recommended path
evidence
residual risk
git status --short
