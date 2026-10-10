# C009B — Fixed Windows FFmpeg Master Mux v1

## Objective

Implement the real Windows media composer behind the C009A-frozen interface:

```csharp
Task ComposeAsync(
    MasterVideoCompositionRequest request,
    CancellationToken cancellationToken);
```

C009B owns only:
- fixed FFmpeg/ffprobe process execution
- narration audio timeline construction
- H.264 video stream-copy
- AAC-LC / 48 kHz / mono / 128 kbps
- timeout/cancel/partial cleanup
- media-level validation
- real Windows smoke acceptance

Do NOT redesign C009A master identity/catalog/manifest/lineage.

## Branch

feature/postproduction-master-ffmpeg-mux-v1

Base:
de0c0f379ce696ff724d0077fa7fe4f4b9e9f086

This base contains the frozen C009A contracts and both C007B/C008B implementations.

## Authorities

Read and obey:
- docs/architecture/video/G004_POSTPRODUCTION_COMPOSITOR_V1.md
- docs/architecture/video/S005_WINDOWS_AUDIO_MUX_RESULT.md
- windows/desktop/src/PicotooPet.Desktop/Services/IMasterVideoComposer.cs
- windows/desktop/src/PicotooPet.Desktop/Services/PostProductionMasterContracts.cs

S005 is now real-Windows PASS and frozen:
RECOMMEND_STREAM_COPY_AAC_MUX

Real S005 proof:
- Windows NT 10.0.26200
- .NET SDK 10.0.302
- ffmpeg 9.0 full_build
- native AAC present
- H.264 packet MD5 input == output
- AAC LC / 48 kHz / mono
- exact silence/tone timing checks PASS
- overlong narration rejected before ffmpeg
- cancellation ~347 ms
- timeout ~1034 ms
- failure leaves no output

## Frozen C009A interface

Do not change this interface unless compilation proves an actual defect:

```csharp
public sealed record MasterVideoCompositionRequest(
    VerifiedMasterVisual Visual,
    IReadOnlyList<VerifiedMasterNarrationSegment> NarrationSegments,
    long TargetRuntimeMs,
    string OutputPath);

public interface IMasterVideoComposer
{
    Task ComposeAsync(
        MasterVideoCompositionRequest request,
        CancellationToken cancellationToken);
}
```

C009B must not add caller-controlled:
- executable
- codec
- bitrate
- sample rate
- channel count
- filter graph
- shell
- arbitrary output path
- provider/model/network authority

The request paths are internal verified paths selected by C009A.

## Product implementation

Add a concrete composer, recommended names:
- FixedFfmpegMasterVideoComposer.cs
- MasterVideoProcessRunner.cs
- MasterVideoMediaProbe.cs

Keep new files separate from C007B/C008B producers.

Do not modify:
- PostProductionMasterContracts.cs
- PostProductionMasterArtifactCatalog.cs
- PostProductionMasterSourceVerifier.cs
- master digest/manifest schema
unless a real compilation-level defect makes a tiny compatibility change unavoidable.

Prefer zero changes to C009A files.

## Defense-in-depth revalidation at use time

Before invoking ffmpeg:
- Visual.Path must exist as an ordinary file
- size must equal Visual.Bytes
- recompute SHA-256 and require Visual.Sha256
- each narration WAV must:
  - exist as ordinary file
  - match Bytes
  - match SHA-256
  - be PCM16 WAV
  - sample rate/channels facts match request
  - sample-frame duration must not exceed exact [StartMs, EndMs) window

C009A already verified these; C009B repeats content checks immediately before process use to close TOCTOU.

Do not create a new durable asset registry.

## Visual-only master case

If NarrationSegments.Count == 0:
- do NOT invoke ffmpeg
- byte-copy the verified visual to request.OutputPath
- no audio may be introduced
- output bytes/SHA must equal visual bytes/SHA
- cancellation must remain observable during copy
- no metadata rewrite/remux

This is the overlay-only C009 path and avoids pointless container mutation.

## Narrated master case

If NarrationSegments.Count > 0:

### Fixed input order
- input 0 = selected visual MP4
- inputs 1..N = ordered narration WAV files by Order

Require:
- contiguous Order starting at 1
- strictly non-overlapping windows
- StartMs >= 0
- EndMs > StartMs
- EndMs <= TargetRuntimeMs

### Audio normalization / gain policy

S005 identified stereo-to-mono gain as the remaining policy to pin.

Freeze v1 policy:

- mono source:
  - preserve mono amplitude
  - resample to 48 kHz as needed

- stereo source:
  - explicit average downmix:
    `pan=mono|c0=0.5*c0+0.5*c1`
  - then resample/format to 48 kHz mono float

Do NOT rely on FFmpeg's implicit downmix.

### Timing graph

For each segment:
- normalize to 48 kHz mono
- delay by exact integer StartMs
- no trim
- no speed change

Mix all delayed segments with:
- `amix=inputs=N:duration=longest:normalize=0`
- then `apad=whole_dur=<TargetRuntimeMs seconds>`

No:
- atempo
- atrim
- -shortest
- video filters
- scale
- fps conversion
- pixel format conversion
- caller filter text

All filter text is generated internally from validated integer timing facts only.

## Fixed FFmpeg output

Use a single fixed mux command equivalent to the proven S005 path:

- `-hide_banner`
- `-loglevel error`
- `-nostdin`
- input visual + ordered WAV inputs
- fixed internally-authored `-filter_complex`
- `-map 0:v:0`
- `-map [aout]`
- `-c:v copy`
- `-c:a aac`
- `-profile:a aac_low`
- `-b:a 128k`
- `-ar 48000`
- `-ac 1`
- `-map_metadata -1`
- bitexact flags consistent with S005
- `-movflags +faststart`
- MP4 output

Do not use libx264/h264_nvenc/any video encoder.

Do not use shell execution.

Use ProcessStartInfo.ArgumentList.

## Executable policy

Only:
- ffmpeg.exe
- ffprobe.exe

No PATH argument from caller.
No PowerShell/cmd.
No external provider/runtime.

If executable unavailable, fail through bounded C009 composer error; never leak stderr/path.

## Timeout / cancellation

Use bounded process runner:
- normal mux timeout: choose a fixed product constant, recommended 10 minutes
- ffprobe timeout: fixed short bound, recommended 30 seconds
- cancellation kills entire process tree
- timeout kills entire process tree
- drain stdout/stderr without unbounded memory
- stderr must not escape into exception/UI/manifest
- no orphan process

Temporary output belongs only to C009A work directory.
On any failure/cancel/timeout:
- delete output if created
- leave no extra files

Do not delete C004/C007B/C008B sources.

## Input media probe

Before narrated mux, ffprobe visual with fixed fields.

Require exactly:
- one video stream
- zero audio streams
- zero subtitle/data/attachment/other streams
- codec h264
- pixel format yuv420p
- positive width/height
- positive fps
- readable positive duration

C004/C008B are visual-only sources by design.
If audio or unexpected streams exist, fail closed.

## Output media probe

After mux require exactly:
- 1 video
- 1 audio
- 0 other streams

Video:
- codec h264
- pix_fmt yuv420p
- width == input width
- height == input height
- fps == input fps
- packet count == input packet count

Audio:
- codec aac
- profile LC
- sample_rate 48000
- channels 1

Duration:
- positive
- within a fixed product tolerance of selected visual duration / target timeline
- do not hide mismatch by truncation

Use an explicit constant and tests.
C010 owns final delivery QA tolerance; C009B only rejects obviously invalid mux output.

## Stream-copy proof

Product implementation must be structurally incapable of video encoding:
- generated args contain exactly `-c:v copy`
- no video filter
- no video encoder

Real-Windows smoke must additionally prove stream-copy by comparing input/output video packet MD5 exactly, as S005 did.

Do not necessarily compute packet MD5 on every production render if it materially increases normal runtime; it is mandatory in acceptance smoke.

## Media probe implementation

Use ffprobe JSON with a closed field set, e.g.:
- codec_type
- codec_name
- profile
- width/height
- r_frame_rate
- pix_fmt
- sample_rate
- channels
- nb_read_packets
- format duration

Reject malformed/unknown shape safely.

No raw ffprobe JSON persisted.

## Error mapping

Keep C009A public boundary:
- composer failures surface to C009A as MASTER_COMPOSER_FAILED
- invalid/missing final output surfaces as MASTER_OUTPUT_INVALID where C009A owns it

Inside C009B use closed internal codes/statuses only.

Never put:
- stderr
- raw paths
- raw narration text
into user-visible errors.

## Tests

Create an isolated harness, recommended:
windows/desktop/tests/PicotooPet.PostProductionMasterMux.SmokeTests/

Do not modify shared SmokeTests/Program.cs.

### Pure/unit tests
- zero narration => byte copy, no ffmpeg
- input tamper SHA mismatch => no process
- WAV tamper => no process
- invalid timing/order/overlap => no process
- exact-window segment allowed
- overlong by one sample frame rejected
- mono graph has no implicit stereo policy
- stereo graph contains explicit 0.5/0.5 pan
- generated args contain -c:v copy
- generated args contain AAC LC/48k/mono/128k
- no libx264/nvenc/video filter/scale/fps/pix_fmt conversion
- no atempo/atrim/-shortest
- filter graph derives only integer timings
- timeout/cancel delete partial output
- stderr not surfaced

### Real Windows acceptance
Generate deterministic synthetic H.264/yuv420p visual + WAVs or reuse the S005 fixture helper semantics.

Must prove:
- ffmpeg/ffprobe available
- native AAC available
- narrated mux exits 0
- exactly 1 video + 1 audio
- video packet MD5 input == output
- video dimensions/fps/pix_fmt/packet count unchanged
- AAC LC / 48000 / mono
- placement windows correct
- silence gaps correct
- stereo averaging policy does not clip/amplify unexpectedly
- cancellation bounded
- timeout bounded
- failure leaves no output

Also test the actual C005 24 fps profile behavior, not only S005's 25 fps synthetic fixture:
- at least one 832x480 @24 fixture
- ideally cover 480x832 and 640x640 metadata preservation through parameterized logic

If environment lacks ffmpeg/fonts/etc:
- report UNVERIFIED, not PASS

## Regression

Run:
- C009A isolated smokes
- C007B focused smokes
- C008B focused smokes
- Windows Release build
- contract/security tests

Do not fix unrelated full-repo failures unless they are caused by C009B.

## Explicit exclusions

No:
- C009C Goal delivery selector
- C010 QA/receipt
- Goal Center/UI
- C004 modifications
- C007B producer modifications
- C008B producer modifications
- Production/C006
- Creative/Core schema
- publishing
- Maotai/Natural Motion
- deploy/macos

## Delivery requirements

- commit all changes
- push to origin/feature/postproduction-master-ffmpeg-mux-v1
- working tree clean
- do not merge/rebase/tag/release

Final response only:
remote branch
remote HEAD SHA
files changed
tests
real Windows status
FFmpeg command policy
stream-copy evidence
audio policy
architecture notes
residual risk
git status --short
