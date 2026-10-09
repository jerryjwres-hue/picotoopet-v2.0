# S005 — Windows Post-production Audio Mux Result

**Decision: RECOMMEND_STREAM_COPY_AAC_MUX**

**Validation status: PASS on real Windows hardware.**

Native validation environment:
- Windows: Microsoft Windows NT 10.0.26200.0
- .NET SDK: 10.0.302
- .NET runtime: 10.0.10
- FFmpeg: 9.0-full_build-www.gyan.dev
- ffprobe: available
- native AAC encoder: available
- Probe exit: 0

The isolated probe built with 0 warnings / 0 errors, its self-test passed, and the real mux proof passed on the Windows host.

## Decision

Use the fixed FFmpeg stream-copy + AAC mux path for C009B v1:

- H.264 video: stream-copy only
- narration audio: fixed internally-authored placement/mix graph
- final audio: AAC-LC / 48 kHz / mono / 128 kbps
- final container: MP4 + faststart
- no video re-encode
- no shell
- no arbitrary caller filter/path/codec authority

## Real Windows evidence

### Input video

- codec: h264
- size: 640x360
- frame rate: 25/1
- pixel format: yuv420p
- packet count: 200

### Input narration fixtures

1. seg1
   - 24 kHz
   - mono
   - 2000 ms
   - starts at 0 ms
   - window end 2500 ms
2. seg2
   - 44.1 kHz
   - stereo
   - 1500 ms
   - starts at 2500 ms
   - window end 5000 ms
3. seg3
   - 48 kHz
   - mono
   - 2500 ms
   - starts at 5000 ms
   - window end 8000 ms

The fixtures deliberately exercise resampling, stereo-to-mono normalization, delayed placement and silence gaps.

## Fixed mux shape

The validated command shape uses:

- `-c:v copy`
- `-c:a aac`
- `-profile:a aac_low`
- `-b:a 128k`
- `-ar 48000`
- `-ac 1`
- `-map_metadata -1`
- bitexact flags
- `+faststart`

The generated `filter_complex` is internally authored only from validated integer `start_ms` values. It normalizes each WAV to mono 48 kHz, applies `adelay`, mixes with `amix=normalize=0`, and pads silence to the exact timeline.

It contains no:
- `atempo`
- `atrim`
- `-shortest`
- video filter
- caller-provided filter text

## Final mastered stream facts

The real Windows output contained exactly:

- 1 video stream
- 1 audio stream
- 0 other streams

Video:
- h264
- 640x360
- 25/1
- yuv420p
- 200 packets

Audio:
- aac
- profile: LC
- sample rate: 48000 Hz
- channels: 1

Final duration:
- 8.000 s

## Video stream-copy proof

Input video packet MD5:

`8ae2b1d944fd3f9fca6fac2dd3358571`

Final video packet MD5:

`8ae2b1d944fd3f9fca6fac2dd3358571`

They are identical.

Together with matching codec, size, frame rate, pixel format and packet count, this proves the C009B candidate path does not transcode the video stream.

`video_stream_copy_proven = true`

## Audio timeline proof

All timeline checks passed.

- seg1: expected 440 Hz tone present
- gap before seg2: RMS 0
- seg2: expected 660 Hz tone present
- gap before seg3: RMS 0
- seg3: expected 880 Hz tone present
- gap after last: RMS 0

The shorter-than-window narration segment leaves silence in the remainder of its assigned window as required.

## Overlong narration negative control

A 3000 ms WAV assigned to a 2000 ms window was rejected before FFmpeg invocation.

Result:
- status: NARRATION_SEGMENT_TOO_LONG
- ffmpeg_invoked: false
- output_exists: false
- rejected: true

Therefore C009B must preserve this rule:
- never silently truncate narration
- never speed it up
- never rely on FFmpeg to detect overlong narration

## Cancellation / timeout

Cancellation:
- CANCELLED
- 347 ms
- bounded: true

Timeout:
- TIMEOUT
- 1034 ms
- bounded: true

Failure cleanup:
- failure_leaves_no_output: true

## Architecture recommendation

Freeze C009B v1 to:
- verified H.264/yuv420p visual input
- verified C007B WAV segment artifacts
- pre-mux segment/window validation
- fixed `adelay + amix + apad` audio graph
- AAC-LC / 48 kHz / mono / 128 kbps
- video stream-copy only
- one final MP4
- fixed ffmpeg.exe / ffprobe.exe
- ProcessStartInfo.ArgumentList
- no shell
- no external renderer/provider/model
- temp output + atomic durable promotion

C009B should explicitly pin its intended stereo-to-mono gain policy rather than depend on an undocumented default downmix.

## QA implications for C010

C010 can deterministically require, when narration is required:
- exactly 1 H.264/yuv420p video stream
- exactly 1 AAC-LC audio stream
- 48000 Hz
- mono
- no subtitle/data/attachment streams
- duration within the frozen frame/container tolerance
- SHA/bytes and full lineage match

When narration is not required, final delivery must contain no audio stream.

## Residual risk

- AAC encoder delay remains a container/audio timing property; C010 should retain an explicit fixed tolerance rather than require sample-perfect container duration.
- Stereo-to-mono gain must be pinned in product code.
- The spike used 25 fps synthetic video while PicotooPet C005 profiles use 24 fps; stream-copy behavior is codec/container-based, but C009B real integration tests must include the actual C005 24 fps profiles.
- Real C009B must test actual C007B WAV artifacts and C008B/C004 visual artifacts, not only synthetic fixtures.

## Final decision

RECOMMEND_STREAM_COPY_AAC_MUX
