# C008B — Windows Caption/Text Overlay Rendering v1

## Objective

Consume the authenticated C008A2 CaptionOverlayPlan on Windows and apply deterministic authored text overlays to a verified C004 FinalVideoArtifact using the S004-proven FFmpeg drawtext path.

This is post-production. Do not modify Production/C006 or C004 assembly.

## Branch

feature/windows-caption-overlay-render-v1

Base:
e4f1d5a7a518441bd9dcb2bb76314f81eea795a8

## Proven renderer path

S004 real Windows result:
- RECOMMEND_DRAWTEXT
- FFmpeg 9.0 full build
- drawtext PASS
- libfreetype PASS
- English Arial PASS
- Chinese Microsoft YaHei (msyh.ttc) PASS
- deterministic PASS
- bounded cancel/timeout PASS

Use drawtext only for C008B v1.
Do not add libass fallback in product code.

## Architecture

C008A2 Core remains plan authority.

Windows flow:
C004 FinalVideoArtifact
+ authenticated CaptionOverlayPlan
-> verify source final MP4
-> closed font/glyph preflight
-> internally authored drawtext filter chain
-> verified derived MP4
-> immutable local manifest
-> restart-safe reuse

No narration mux here.
C009 will later combine visual post-production + C007B narration.

## Core API client

Add strict Windows records matching C008A2 response.

Preferred new files:
- windows/desktop/src/PicotooPet.Desktop.Core/Contracts/CaptionOverlayContracts.cs
- windows/desktop/src/PicotooPet.Desktop.Core/Networking/MacCoreClient.CaptionOverlay.cs
- windows/desktop/src/PicotooPet.Desktop/Services/ControlCenterSession.CaptionOverlay.cs

GET:
 /api/v1/postproduction/production/{production_job_id}/caption-overlay-plan

Requirements:
- authenticated
- trace header preserved
- production_job_id URL-escaped
- bounded response size
- strict JSON
- typed bounded API errors
- never log overlay text/raw response

Do not modify Production networking/session files.

## Renderer/service

Preferred new files:
- WindowsCaptionOverlayService.cs
- WindowsCaptionOverlayRenderer.cs
- WindowsTextOverlayFontPolicy.cs
- WindowsSfntCmap.cs
- local manifest records if useful

Do not modify FinalVideoAssemblyService.cs.

Service input must be:
- a verified C004 FinalVideoArtifact object
- a verified C008A2 plan response

Caller must not supply arbitrary source/output/font/filter paths.

## Source verification

Before rendering:
- production_job_id must match
- FinalVideoArtifact must be ordinary file
- source MP4 path must be under the C004 managed FinalVideos root
- reject symlink/reparse escape
- recompute bytes and SHA-256 and match artifact
- plan production_job_id must match
- plan output_profile_id must be one of closed C005 IDs

No arbitrary user path becomes authority.

## Font policy

Freeze closed candidates based on S004 evidence.

English:
1. arial.ttf
2. segoeui.ttf
3. msyh.ttc

Chinese/Han:
1. msyh.ttc
2. Deng.ttf
3. simhei.ttf
4. simsun.ttc

Resolve only under Windows Fonts.
Reject reparse files.
Bound size.
Verify glyph coverage with a bounded SFNT cmap reader (formats 4/12; TTC first face is acceptable for v1 if tests cover it).

Per cue:
- if text contains Han ideograph => Chinese policy
- otherwise English policy

No caller font choice.
No font download.

## Drawtext policy

Never place authored text directly inside FFmpeg filter syntax.

For each overlay cue:
- write UTF-8 cue text to a probe-managed temporary text file
- copy/prepare the approved font into the same isolated working directory using a generated safe filename, or otherwise use a fixed safe internal reference
- generate only internally-authored relative names
- generate start/end timing from integer Core start_ms/end_ms
- closed style profile:
  overlay.title-safe.v1
- closed font profile:
  font.windows-system-sans.v1

Use fixed layout based on S004:
- lower/title-safe region
- centered
- white text
- fixed semi-transparent black box
- deterministic font size derived only from closed output profile
- no caller styling values

Multiple overlay cues:
- build one internally generated drawtext filter chain
- no overlapping same-plan overlay ambiguity should reach Windows; nevertheless reject invalid overlapping/unsorted cues

No shell.
Use ProcessStartInfo.ArgumentList.
Fixed ffmpeg.exe only.

## Output

Managed root:
%LOCALAPPDATA%\PicotooPet\PostProduction\TextOverlay\v1\

Derived output:
- H.264 MP4
- yuv420p
- preserve source video duration
- no audio
- +faststart
- metadata stripped/fixed where practical
- deterministic single-thread/bitexact policy if the installed FFmpeg supports the proven S004 flags

C008B output is a derived local visual artifact, not C004 replacement.

## Empty plan

If overlays_required=false and overlays=[]:
- do not invoke ffmpeg
- return a valid passthrough artifact referencing the verified C004 source in memory
- local manifest may record passthrough=true
- do not copy/re-encode unnecessarily

## Manifest / provenance

Persist a local immutable manifest under the managed post-production root with:
- schema_version
- production_job_id
- source production_package_id/digest
- source_final_sha256
- caption_overlay_plan_digest
- output_profile_id
- overlay style/font profile IDs
- ordered cue identities:
  - cue_id
  - beat_id
  - order
  - text_sha256
  - start_ms
  - end_ms
  - resolved font name
  - resolved font identity SHA-256
- output file name only
- output sha256
- output bytes
- passthrough flag
- created_at

Do NOT persist raw overlay text.
Do NOT persist absolute font/source/output paths.

## Restart/reuse

Artifact identity binds:
- C004 source final SHA
- CaptionOverlayPlan digest
- closed renderer version/profile
- resolved bounded font identities

Matching manifest/output:
- reverify source and output hashes
- reuse

Partial/mismatch/tamper:
- fail closed TEXT_OVERLAY_ARTIFACT_CONFLICT
- do not silently overwrite durable conflicting output

Temporary files/output use atomic promotion.

## Errors

Closed local codes:
- TEXT_OVERLAY_PLAN_INVALID
- TEXT_OVERLAY_SOURCE_INVALID
- TEXT_OVERLAY_FONT_UNAVAILABLE
- TEXT_OVERLAY_GLYPH_MISSING
- TEXT_OVERLAY_FFMPEG_UNAVAILABLE
- TEXT_OVERLAY_FFMPEG_FAILED
- TEXT_OVERLAY_FFMPEG_TIMEOUT
- TEXT_OVERLAY_OUTPUT_INVALID
- TEXT_OVERLAY_ARTIFACT_CONFLICT

Never include:
- authored text
- absolute path
- raw filter string
- raw FFmpeg stderr
- raw Core response

## Parallel-development ownership

C006B2B Codex owns Production files.

C008B MUST NOT modify:
- ProductionExecutionService.cs
- ProductionLocalMediaRenderer.cs
- ProductionContracts.cs
- any src/picotoopet_core/production/**
- any C006 asset/Creative files
- C007 narration files
- FinalVideoAssemblyService.cs
- GoalFinalVideoCoordinator.cs
- existing shared SmokeTests/Program.cs
- Maotai/UI
- deploy/macos
- Natural Motion

For tests, create an isolated smoke harness instead of modifying shared Program.cs, e.g.:
windows/desktop/tests/PicotooPet.CaptionOverlay.SmokeTests/

Do not add it to the main solution if that would create shared-file overlap. Main Desktop solution must still build because shipping source files are auto-included.

## Tests

Contracts/client:
- exact GET path, escaping, auth/trace, bounded response
- strict extra-field rejection
- no raw text leak on API error
- plan digest/shape validation

Font/glyph:
- Han -> Chinese closed policy
- Latin -> English closed policy
- deterministic candidate order
- missing font/glyph bounded
- arbitrary font input impossible

Renderer:
- source final file path under managed root only
- source SHA/bytes reverified
- one English cue render
- one Chinese cue render
- multiple sequential cues
- exact cue timing builder
- no raw text in filter syntax
- fixed drawtext/font/textfile authority
- cancel/timeout cleans partials
- output valid H.264 MP4
- empty plan passthrough

Artifact:
- same source + plan + font identities reuses
- changed plan digest does not reuse
- changed/tampered source fails
- tampered output fails
- manifest has no text/absolute paths
- partial conflict fails closed

Regression:
- Windows Release build 0 errors
- C004 assembly tests remain green
- C008A/A2 Core tests remain green
- no Production regression

## Real Windows acceptance

Before final PASS:
- use actual ffmpeg and installed Windows fonts
- process one English and one Chinese overlay plan
- verify derived MP4 playback/readability
- verify restart reuse

## Acceptance

PASS when Windows can deterministically apply C008A2-authored overlays to a verified C004 final MP4 through the S004-proven drawtext path, producing a verified restart-safe local derived MP4 without changing Production or C004.

## Delivery requirements

- commit all C008B changes
- push to origin/feature/windows-caption-overlay-render-v1
- do not merge/rebase/tag/release
- working tree clean

Final response only:
remote branch
remote HEAD SHA
files changed
tests
architecture notes
residual risk
git status --short
