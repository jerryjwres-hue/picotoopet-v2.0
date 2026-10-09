# S005 — Windows Post-production Audio Mux Result

**Validation status: UNVERIFIED on Windows.** The authoring container is Linux with no .NET SDK and no
Windows host, so the probe was **not compiled and not run on Windows**. No Windows evidence exists yet.
Per the spike rules this document does not fake a PASS.

## Deliverable

Isolated probe: `windows/tools/PicotooPet.PostProductionAudioMuxProbe/` (not in `PicotooPet.Desktop.sln`;
no NuGet packages; no C007B/C008B/C004/Production/Goal Center/shared-SmokeTests change; no product
integration). Run on native Windows with `ffmpeg.exe` / `ffprobe.exe` on PATH (SDK per
`windows/desktop/global.json`):

```powershell
pwsh -File windows/tools/PicotooPet.PostProductionAudioMuxProbe/Run-PostProductionAudioMuxProbe.ps1
```

Exit codes: 10 forbidden-authority scan, 11 build, 12 exe missing, 13 self-test, otherwise the probe's own
code (0 = every proof passed, 1 = otherwise).

## The candidate command (one fixed shape)

Inputs are probe-generated: an 8 s 640×360@25 H.264/yuv420p MP4 and three PCM16 WAVs with deliberately
different formats (24 kHz mono 2000 ms @0, 44.1 kHz stereo 1500 ms @2500, 48 kHz mono 2500 ms @5000),
leaving silence gaps 2000–2500, 4000–5000 and 7500–8000 ms and a segment shorter than its window.

```
ffmpeg -hide_banner -loglevel error -nostdin -y -i input.mp4 -i seg1.wav -i seg2.wav -i seg3.wav
  -filter_complex "<generated>" -map 0:v:0 -map [aout]
  -c:v copy -c:a aac -profile:a aac_low -b:a 128k -ar 48000 -ac 1
  -map_metadata -1 -fflags +bitexact -flags:a +bitexact -movflags +faststart -f mp4 mastered.partial.mp4
```

`<generated>` (only from integer `start_ms`, relative internal names, no caller text):

```
[1:a]aformat=sample_rates=48000:channel_layouts=mono:sample_fmts=fltp,adelay=0:all=1[a0];
[2:a]aformat=...,adelay=2500:all=1[a1];[3:a]aformat=...,adelay=5000:all=1[a2];
[a0][a1][a2]amix=inputs=3:duration=longest:normalize=0,apad=whole_dur=8.000[aout]
```

No `atempo`, no `atrim`, no `-shortest`, no video filter, no `-c:v` other than `copy`. `amix normalize=0`
requires FFmpeg ≥ 4.4. Output is promoted from `mastered.partial.mp4` only after ffmpeg exits 0.

## What the probe proves (per row, when run on Windows)

| Requirement | Evidence field |
| --- | --- |
| ffmpeg/ffprobe + AAC encoder present | `ffmpeg_version`, `aac_encoder_present`, `ffprobe_available` |
| Video is stream-copied, not re-encoded | `video_stream_copy_proven` — `ffmpeg -map 0:v:0 -c copy -f md5 -` over input and final gives equal `MD5=` (`input_video_packet_md5`, `final_video_packet_md5`), plus equal codec/size/fps/pix_fmt/packet count |
| Readable MP4, exactly 1 video + 1 audio | `final.video_streams=1`, `audio_streams=1`, `other_streams=0` |
| Video h264, original width/height/fps | `final.video` equals `input_video` |
| Audio AAC-LC 48 kHz mono | `final.audio` = `aac`/`LC`/48000/1 |
| Duration matches timeline (±0.15 s) | `duration_within_tolerance` |
| Placement, gaps, shorter segment | `audio_timeline_checks[]`: RMS + Goertzel strongest tone (440/660/880 Hz) inside each tone window, RMS ≤ 200 in each gap window (150 ms edge margins) |
| Overlong narration never truncated/sped up | `overlong_narration`: validator returns `NARRATION_SEGMENT_TOO_LONG` before ffmpeg runs, no output created |
| Timeout / cancel bounded | `cancellation`, `timeout`: loop-copy + AAC encode of a 7200 s timeline killed by the process-tree kill; ≤ 8 s |
| No partial durable output after failure | `failure_leaves_no_output` |
| No shell / network / provider / model | `ArgumentList` with fixed `ffmpeg.exe`/`ffprobe.exe`; regex-guarded relative names; script-level source scan |

The segment validator also rejects `NARRATION_SEGMENT_OUTSIDE_TIMELINE`, `NARRATION_SEGMENT_OVERLAP`
and `NARRATION_SEGMENT_INVALID` (non-PCM16 / malformed WAV).

## Local (non-Windows) evidence — command-shape sanity only

On the Linux container (ffmpeg 6.1.1) the *same* generated filter graph and arguments were run by hand
with synthetic inputs matching the fixtures above:

- Mux exit 0; ffprobe: one `h264` (640×360, `25/1`, yuv420p) and one `aac` LC, 48000 Hz, 1 channel; duration `8.000000`.
- Video packet md5 of input and final both `fc660f2f2f94e92c76e900064b0aff95` — no video transcode.
- Decoded audio: segment windows were non-silent at exactly 440 / 660 / 880 Hz (RMS ≈ 11.6k / 16.4k / 11.6k;
  the stereo segment is summed to mono without attenuation); the three gap windows measured RMS 0.
- The stress variant (`-stream_loop -1 … -t 7200`) ran until `timeout 1` killed it (exit 124 after 1.02 s).
- Plain ffmpeg **accepted** a 3 s WAV with no error when only 2 s were allotted (exit 0), which is why the
  window check is a mandatory pre-mux validation and not left to ffmpeg.

This shows the command shape and analysis logic are sound on one ffmpeg build. It says **nothing** about
the Windows ffmpeg build, its AAC encoder, or the C# probe, none of which has been compiled or run.

## Decision rule for the orchestrator

The stream-copy AAC mux path may be recommended only when the real Windows report has `status=PASS`
(copy proven, 1 video + 1 audio, AAC LC 48 kHz mono, timeline checks all `ok`, overlong negative
`rejected`, cancellation and timeout `bounded`, `failure_leaves_no_output`). Otherwise record the failing
field and keep the other decision. After a real Windows run, replace the final decision line below with
the supported outcome and attach the JSON report.

## Residual risk

- The C# probe has never been compiled; the first Windows build may need small fixes (warnings are not
  errors for this spike only).
- Windows ffmpeg builds without the native `aac` encoder or with FFmpeg < 4.4 (`amix normalize`) would fail
  fast with `AAC_ENCODER_MISSING` / `MUX_FAILED`.
- MD5 over the copied packet stream proves bit-identical video packets; it does not by itself detect a
  changed container-level timebase, which the fps/packet-count equality covers.
- Stereo-to-mono uses FFmpeg's default downmix (no attenuation); C009B should pin the intended gain.
- AAC encoder delay is absorbed by the 150 ms window margins and 0.15 s duration tolerance.

## Decision

No path is proven on real Windows, so none can be recommended yet. This is not a finding that the
path is non-viable.

NO_COMPATIBLE_AUDIO_MUX_PATH_PROVEN
