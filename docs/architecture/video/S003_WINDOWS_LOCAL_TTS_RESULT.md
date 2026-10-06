# S003 — Windows Local TTS Compatibility Result

**Decision: NO_COMPATIBLE_LOCAL_ENGINE_PROVEN**

**Validation status: UNVERIFIED.** The authoring container had no .NET SDK and no Windows host, so
the probe was not compiled or run. No engine has been proven or disproven. This token is the only
decision supportable from evidence so far; it is **not** a finding that both engines are unusable.
The orchestrator must run the command below on native Windows and replace this decision with
`RECOMMEND_SYSTEM_SPEECH`, `RECOMMEND_WINDOWS_MEDIA_SPEECH`, or a conclusive
`NO_COMPATIBLE_LOCAL_ENGINE_PROVEN`, attaching the JSON report.

## Deliverable

Isolated probe: `windows/tools/PicotooPet.TtsCompatibilityProbe/` (not in `PicotooPet.Desktop.sln`,
no change to Desktop dependencies, C006A-owned `Program.cs`, workflows, or app behavior).

Run on native Windows (SDK per `windows/desktop/global.json`):

```powershell
pwsh -File windows/tools/PicotooPet.TtsCompatibilityProbe/Run-TtsCompatibilityProbe.ps1
```

Exit codes: 10 forbidden-authority scan, 11 build, 12 exe missing, 13 self-test, 14 missing-voice
path, otherwise the probe's own code (0 = at least one engine PASS, 1 = none).

## Candidates and what the probe measures

| Question | System.Speech (SAPI) | Windows.Media.SpeechSynthesis |
| --- | --- | --- |
| Compiles on `net10.0-windows` | Via probe-scoped NuGet `System.Speech` 9.0.0 | Needs Windows SDK TFM `net10.0-windows10.0.19041.0` (no package) |
| Offline, no key/account | In-process SAPI5; no network API used | In-process OneCore voices; no network API used |
| Deterministic logical voice | Enumerate installed voices → `en-US` first, then name ordinal | Same rule over `AllVoices` |
| WAV/PCM without shell-out | `SetOutputToWaveFile` 22.05 kHz/16-bit/mono | `SynthesizeTextToStreamAsync` stream copied to file |
| Bounded cancel/timeout | `SpeakAsyncCancelAll` + token + hard `WaitAsync` | `IAsyncOperation` cancel via token + hard `WaitAsync` |
| No compatible voice | `NO_COMPATIBLE_VOICE` | `NO_COMPATIBLE_VOICE` |
| Runtime dependency | `System.Speech` package + installed SAPI voices | None beyond Windows 10 1903+ voices |

The right-hand column entries above for compilation and behavior are **design expectations, not
evidence**. Evidence is the report fields below once the probe has run.

## Probe behavior (by construction)

- Fixed phrase `PicotooPet narration compatibility check.`; output only under a per-run temp
  directory (`%TEMP%\PicotooPetTtsProbe\<guid>`) that is always deleted.
- Closed CLI: `--engine`, `--timeout-seconds 1..60`, `--simulate-no-voice`, `--self-test`. No voice,
  model, executable, URL, or output-path argument exists.
- Voice enumeration is reported for compatibility only; selection is the deterministic rule above.
- WAV validation: RIFF/WAVE, PCM (format 1), 1–2 channels, 8–48 kHz, 16-bit, nonzero data, total
  size 45 B – 16 MiB.
- Cancellation check: a fixed long phrase (the fixed phrase repeated) is cancelled after 150 ms;
  `bounded=true` requires status `CANCELLED` within 5 s. `NOT_RUN` means synthesis finished before
  the cancel landed and cancellation was **not** demonstrated.
- The script statically rejects sources containing network, process-launch, environment,
  credential, or model-file tokens.
- Statuses are a closed set; no raw exception text or paths are emitted.

## Evidence to attach (all currently absent)

Per engine in the JSON report: `status`, `installed_voices`, `selected_voice`, `wav`
(`audio_format`, `channels`, `sample_rate`, `bits_per_sample`, `data_bytes`, `duration_ms`),
`synthesis_elapsed_ms`, `cancellation.{status,elapsed_ms,bounded}`; plus script exit code and
`dotnet --info`, OS version, and whether the runner had any `en` voice installed.

Decision rule for the orchestrator: an engine is viable only when `status=PASS`, WAV fields valid,
and `cancellation.bounded=true`; with both viable prefer System.Speech (smaller moving parts,
matches the ordered candidate list) unless it shows a defect; if both report `NO_COMPATIBLE_VOICE`
on a real Windows host, record whether that is a runner image limitation before concluding.

## Residual risk

- Probe code has never been compiled; first Windows build may need small fixes. Warnings are not
  errors for this spike only.
- `System.Speech` package version 9.0.0 was chosen as a known-published version; confirm restore
  works against the repo's NuGet sources, and whether a 10.x package is preferred.
- CI runner images may lack `en` voices, which would be an environment limitation, not an engine verdict.
