# S004 — Windows Text Overlay Compatibility Result

**Validation status: UNVERIFIED on Windows.** The authoring container is Linux with no .NET SDK, no
Windows host and no Windows system fonts, so the probe was **not compiled and not run on Windows**.
No Windows evidence exists yet. Per the spike rules this document does not fake a PASS.

## Deliverable

Isolated probe: `windows/tools/PicotooPet.TextOverlayCompatibilityProbe/` (not in
`PicotooPet.Desktop.sln`; no NuGet packages; no change to Production, C006/C007/C008 Core or C004).

Run on native Windows with `ffmpeg.exe` / `ffprobe.exe` on PATH (SDK per `windows/desktop/global.json`):

```powershell
pwsh -File windows/tools/PicotooPet.TextOverlayCompatibilityProbe/Run-TextOverlayCompatibilityProbe.ps1
```

Exit codes: 10 forbidden-authority scan, 11 build, 12 exe missing, 13 self-test, 14 missing-font path,
otherwise the probe's own code (0 = at least one path PASS, 1 = none).

## What the probe proves (per path, when run on Windows)

| Requirement | drawtext | subtitles/libass |
| --- | --- | --- |
| Filter exists in installed ffmpeg | `-filters` has `drawtext` + libfreetype | `-filters` has `subtitles` + libass |
| UTF-8 English | `textfile=` (UTF-8, no escaping) | UTF-8 ASS file |
| Chinese glyphs, installed font | cmap preflight, then render | cmap preflight, then render |
| Fixed font policy | closed list under the Windows Fonts folder, copied into the temp dir, referenced by relative name | same font copied into a per-label `fontsdir`, ASS family from the closed list |
| Valid MP4 | `ffprobe` h264 640x360 (if present) + full decode via ffmpeg | same |
| Timing window honored | ink frames ≈ 25..75 (±1), contiguous, 100 frames | same |
| Fixed safe-area/lower-third | ink box inside x 32..608, y 240..342, centre within 10 px | same |
| Deterministic | two identical renders → identical decoded-region SHA-256 | same |
| Real glyphs, not tofu | two different Chinese strings → different frames | same |
| No shell / arbitrary authority | `ArgumentList`, fixed `ffmpeg.exe`/`ffprobe.exe`, fixed filter builders, regex-guarded relative names | same |
| Cancellation bounded | 7200 s render cancelled after 300 ms; killed process tree; ≤ 8 s | same |
| Timeout bounded | same render with 1 s timeout; ≤ 8 s | same |
| Missing font | `--simulate-no-font` → `FONT_UNAVAILABLE` | same |
| Missing glyph | Chinese text against Latin-only `arial.ttf` → `GLYPH_MISSING_DETECTED` (preflight, no ffmpeg run) | same |

Evidence fields in the JSON report: `ffmpeg_version`, `libass_enabled`, `libfreetype_enabled`,
`x264_available`, `ffprobe_available`, `font_policy.*`, and per path `status`, `filter_present`,
`english_font`, `chinese_font`, `renders[]` (`first_ink_frame`, `last_ink_frame`, `mid_cue_ink_box`,
`center_offset_px`, `video_codec`, `output_bytes`), `deterministic`, `chinese_glyphs_distinct`,
`cancellation`, `timeout`; plus `suggested_decision`.

## Local (non-Windows) evidence — filter-syntax sanity only

On the Linux container (ffmpeg 6.1.1, libass + libfreetype, WenQuanYi Zen Hei copy) the *same* filter
forms the probe emits were run by hand with relative file names and the working directory set to the
staging directory:

- `drawtext=fontfile=font.ttc:textfile=zh.txt:fontsize=26:fontcolor=white:box=1:boxcolor=black@0.5:boxborderw=10:x=(w-text_w)/2:y=h*0.78:enable='between(t,1,3)'` → exit 0; ink frames 25..75 of 100.
- `subtitles=filename=cue.ass:fontsdir=fonts` (opaque-box ASS, bottom-centre, MarginV 43) → exit 0; ink frames 25..74 of 100 (ASS end time is exclusive; within the ±1 tolerance).
- The probe's cmap reader algorithm (formats 4 and 12, TTC first face) was prototyped and checked against
  Linux fonts: WenQuanYi covers `Aa字幕测试あ`, DejaVu rejects the CJK characters.

This shows the command shape is accepted by ffmpeg and that the two paths differ by about one frame at
the cue end. It says **nothing** about Windows ffmpeg builds, DirectWrite/fontconfig font resolution in
the Windows libass build, or Windows font coverage.

## Decision rule for the orchestrator

A path is viable only when its `status` is `PASS` (filter present, valid output, timing and geometry in
tolerance, deterministic, distinct glyphs, bounded cancel and timeout). If both are viable prefer
drawtext (no ASS/font-directory resolution, no libass dependency) unless it shows a defect; choose libass
when drawtext is missing from the build or when C008B needs multi-cue/wrapping that ASS gives for free.
If libass reports `GLYPH_NOT_DISTINCT`, the Windows libass build is falling back to a default font and
must not be used for Chinese. The probe's `suggested_decision` field applies this rule mechanically.
After a real Windows run, replace the final decision line below with the supported outcome and attach
the JSON report.

## Residual risk

- The C# probe has never been compiled; the first Windows build may need small fixes (warnings are not
  errors for this spike only).
- Windows libass font lookup (`fontsdir` + family name) is the main unknown; family names in
  `FontPolicy.cs` are the conventional Microsoft names and may differ on localized installs.
- `GLYPH_MISSING` preflight reads only the first face of a TTC and cmap formats 4/12.
- Byte-for-byte determinism relies on `-threads 1` and bit-exact flags of the installed libx264; a build
  that differs between runs would show as `NOT_DETERMINISTIC` rather than a path defect.
- Only MP4/H.264 is exercised (matches C004); WebM/VP9 overlay output (C006A format) is not.
- CI runner images may lack the preferred CJK fonts; that is an environment limitation, not a verdict.

## Decision

Nothing is proven on real Windows, so no path can be recommended yet. This is not a finding that either
path is non-viable.

NO_COMPATIBLE_TEXT_OVERLAY_PATH_PROVEN
