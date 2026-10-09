# S005 — Windows Post-production Audio Mux Compatibility Spike

## Objective
Prove the exact local Windows FFmpeg path required by C009B:
- one verified H.264 MP4 video input
- multiple narration WAV segments with start_ms placement and silence gaps
- one final AAC-LC 48 kHz mono audio track
- video stream-copy (-c:v copy)
- valid mastered MP4
- bounded timeout/cancel
- no shell/arbitrary filter/path authority

This is an isolated compatibility spike. Do not integrate into product code.

## Branch
spike/windows-postproduction-audio-mux

## Required real-path proof

Build an isolated probe under:
windows/tools/PicotooPet.PostProductionAudioMuxProbe/

The probe must generate its own synthetic inputs:
- H.264/yuv420p MP4, fixed duration
- at least 3 WAV segments
- intentional silence gaps
- one segment shorter than its allotted window

Use fixed timestamps such as:
- segment 1 at 0 ms
- segment 2 at 2500 ms
- segment 3 at 5000 ms

Do not require C007B artifact files for the spike.

## FFmpeg policy to evaluate

Preferred v1 candidate:
- input video: H.264 MP4
- audio:
  - normalize each WAV to mono 48 kHz
  - delay each segment to its Core-authored start_ms
  - mix with silence for the full timeline
  - no truncation of narration
- output audio: AAC-LC, 48 kHz, mono, 128 kbps
- output video: stream-copy only (-c:v copy)
- +faststart
- no extra streams

Use one internally authored filter_complex only.
No caller-supplied filter text.

## Must verify

1. ffmpeg/ffprobe availability
2. AAC encoder available
3. H.264 input packet/video stream is copied, not re-encoded
   - compare codec
   - use packet/frame evidence or hashable stream facts sufficient to prove no video transcode
4. final MP4 readable
5. exactly one video + one audio stream
6. final video:
   - h264
   - original width/height/fps
7. final audio:
   - AAC
   - 48000 Hz
   - mono
8. duration matches video timeline within explicit tolerance
9. audio placement:
   - silence before delayed segments
   - segments audible/non-silent only in expected windows
   - shorter narration leaves silence in remainder
10. deterministic command shape
11. cancellation bounded
12. timeout bounded
13. no partial durable output after failure
14. no shell/network/provider/model/external runtime

## Overlong narration negative control

Include one negative fixture where a WAV duration exceeds its allowed Core window.

The probe/product rule must be:
- detect/reject before final mux OR prove a bounded validation step catches it
- never silently truncate narration
- never speed it up

Result code:
NARRATION_SEGMENT_TOO_LONG or spike equivalent.

## Output/report

Write JSON report with:
- ffmpeg version
- AAC encoder presence
- input video facts
- input WAV facts
- final stream facts
- video_stream_copy_proven
- audio_timeline_checks
- timeout/cancel
- negative overlong check
- suggested_decision

Final decision document:
docs/architecture/video/S005_WINDOWS_AUDIO_MUX_RESULT.md

It must end with exactly one:
- RECOMMEND_STREAM_COPY_AAC_MUX
- NO_COMPATIBLE_AUDIO_MUX_PATH_PROVEN

## Explicitly forbidden

Do not modify:
- C007B product files
- C008B product files
- C004
- C006/Production
- Goal Center
- shared SmokeTests/Program.cs
- Maotai/UI
- deploy/macos
- Natural Motion

No product integration in S005.

## Validation

If Claude environment is not Windows:
- implement and push isolated probe
- Linux ffmpeg syntax sanity is optional evidence only
- mark real Windows UNVERIFIED
- do not fake PASS
- orchestrator/user will run it on real Windows

## Delivery requirements
- commit all S005 changes
- push to origin/spike/windows-postproduction-audio-mux
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
