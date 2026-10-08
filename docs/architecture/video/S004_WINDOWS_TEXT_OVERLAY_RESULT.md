# S004 — Windows Text Overlay Compatibility Result

**Decision: RECOMMEND_DRAWTEXT**

**Validation status: PASS on real Windows hardware.**

Native validation environment:
- Windows: Microsoft Windows NT 10.0.26200.0
- FFmpeg: 9.0-full_build-www.gyan.dev
- ffprobe: available
- libass: enabled
- libfreetype: enabled
- libx264: available
- Probe exit: 0

The isolated probe built and ran successfully on the real Windows host. Its pure-logic self-test passed.

## Decision

Use FFmpeg `drawtext` for PicotooPet C008B/C009 text-overlay v1.

`subtitles/libass` is also proven viable and remains a validated fallback/possible future multi-cue engine, but v1 should prefer drawtext because it has fewer moving parts and avoids ASS/font-directory resolution.

## Real Windows evidence

### Font policy

Detected closed-list candidates:
- msyh.ttc
- Deng.ttf
- simhei.ttf
- simsun.ttc
- arial.ttf
- segoeui.ttf

Resolved:
- English: arial.ttf
- Chinese: msyh.ttc

Negative controls:
- missing font: FONT_UNAVAILABLE_DETECTED
- missing Chinese glyph coverage in Latin-only font: GLYPH_MISSING_DETECTED

### drawtext

Status: PASS

English render:
- valid H.264 MP4
- 640x360
- 100 frames
- cue ink frames 25..75
- centered within 1 px
- ffprobe-readable

Chinese render:
- valid H.264 MP4
- 640x360
- 100 frames
- cue ink frames 25..75
- centered within 1 px
- ffprobe-readable
- distinct Chinese glyph rendering confirmed

Determinism: true

Cancellation:
- status: CANCELLED
- elapsed: 344 ms
- bounded: true

Timeout:
- status: TIMEOUT
- elapsed: 1041 ms
- bounded: true

### subtitles/libass

Status: PASS

English/Chinese rendering both passed.
Cue window rendered frames 25..74 because ASS end-time semantics are exclusive; this remains within the probe's ±1 frame tolerance.

Determinism: true
Chinese glyph distinction: true
Cancellation: bounded
Timeout: bounded

## Architecture recommendation

Freeze C008B v1 to:
- backend: ffmpeg drawtext
- fonts: closed internal Windows system-font candidates only
- English preference: arial.ttf
- Chinese preference: msyh.ttc
- no caller-provided font path
- no arbitrary FFmpeg filter string
- no shell
- no downloaded fonts
- no external rendering runtime
- local-only execution

C008B may keep libass out of the shipping path for v1. It can remain documented as a proven fallback if drawtext is unavailable on a future supported Windows host.

## Timing semantics

For drawtext, the validated cue window was exactly frames 25..75 of 100 for a 1–3 second cue in the probe.

C008B should derive all timing expressions internally from Core-authored start_ms/end_ms and the frozen output profile. Caller-provided FFmpeg expressions are forbidden.

## Text/glyph policy

Before invoking ffmpeg:
- select font from the closed candidate list
- verify the font file is ordinary and under the Windows Fonts directory
- verify glyph coverage using the bounded cmap reader
- if no approved font covers the text, fail with a bounded local error
- do not fall back silently to another arbitrary font

## Security result

The proven path requires:
- no network
- no credentials
- no provider
- no model
- no shell
- no arbitrary executable
- no arbitrary font path
- no arbitrary filter string
- no caller-chosen output path

## C008B recommendation

Implement a Windows post-production overlay renderer that:
- consumes authenticated C008A2 CaptionOverlayPlan
- consumes only a verified C004-derived managed MP4 input
- uses the S004-proven drawtext path
- uses closed style/font profiles
- produces a verified managed derived MP4
- records immutable local manifest/provenance
- supports restart-safe reuse
- never mutates C004's source artifact
- does not yet mux narration audio

C009 should later combine the visual post-production artifact with C007B narration and final mastered output.

## Residual risk

- Font inventory varies by Windows installation; C008B must retain bounded FONT_UNAVAILABLE/GLYPH_MISSING failures.
- The probe validates single-cue lower-third/title behavior. Very long text/wrapping and many overlapping cues need product-level C008B tests.
- S004 exercised H.264/MP4, not WebM. This is appropriate for post-production after C004, but not a statement about Production WebM rendering.
- Real-machine validation did not yet run a full PicotooPet C008A2 plan against a real C004 final video.

## Final decision

RECOMMEND_DRAWTEXT
