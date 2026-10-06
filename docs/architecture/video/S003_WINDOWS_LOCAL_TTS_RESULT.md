# S003 — Windows Local TTS Compatibility Result

**Decision: RECOMMEND_WINDOWS_MEDIA_SPEECH**

**Validation status: PASS on real Windows hardware.**

Native validation environment:
- Windows: Microsoft Windows NT 10.0.26200.0
- .NET SDK: 10.0.302
- Runtime: .NET 10.0.10
- Architecture: win-x64
- Probe exit: 0

The isolated probe built with 0 warnings / 0 errors and its self-test passed.

## Decision

Use `Windows.Media.SpeechSynthesis` / OneCore voices for PicotooPet C007B local narration v1.

Do not use `System.Speech` / SAPI5 for v1 on the validated machine.

### System.Speech result

- status: `ENGINE_UNAVAILABLE`
- installed compatible SAPI5 voices: none
- offline/no credentials: yes
- synthesis: not run

This is an environment/runtime compatibility result for the validated machine, not a claim that System.Speech can never work on any Windows host.

### Windows.Media.SpeechSynthesis result

- status: `PASS`
- offline/no credentials: yes
- dependency: Windows SDK TFM + installed OneCore voices
- selected test voice: Microsoft David, en-US
- synthesis elapsed: 158 ms
- cancellation:
  - status: CANCELLED
  - elapsed: 154 ms
  - bounded: true

Detected OneCore voices included:
- Microsoft David — en-US
- Microsoft Zira — en-US
- Microsoft Mark — en-US
- Microsoft Huihui — zh-CN
- Microsoft Yaoyao — zh-CN
- Microsoft Kangkang — zh-CN

Validated WAV:
- PCM format 1
- mono
- 16000 Hz
- 16-bit
- data bytes: 106560
- file bytes: 106606
- duration: 3330 ms

## Probe deliverable

`windows/tools/PicotooPet.TtsCompatibilityProbe/`

The probe remains isolated from the Desktop shipping solution and adds no cloud/provider dependency.

Native run command is compatible with Windows PowerShell 5.1:

```powershell
powershell.exe -ExecutionPolicy Bypass -File ".\windows\tools\PicotooPet.TtsCompatibilityProbe\Run-TtsCompatibilityProbe.ps1"
```

## Security/authority result

The validated path requires:
- no API key
- no account
- no cloud provider
- no arbitrary model path
- no external executable
- no network TTS
- no arbitrary output path supplied by the narration plan

C007B should preserve these boundaries.

## C007B recommendation

Freeze:
- `tts_profile_id = narration.local.windows.v1`
- backend = `Windows.Media.SpeechSynthesis`
- `voice_profile_id = voice.windows.default.v1`

The product implementation should expose only logical voice profiles. It must never expose OneCore registry IDs/names as caller authority.

Voice selection should be deterministic and closed. Runtime absence of a compatible installed voice must fail with a bounded local error; it must not fall back to cloud TTS or arbitrary voices.

C007B should produce managed WAV/PCM narration artifacts with:
- narration plan digest binding
- segment text SHA binding
- WAV validation
- output SHA-256/bytes/duration
- restart-safe reuse
- bounded cancellation/timeout
- no Production lifecycle mutation

Audio/video mux remains a later post-production/compositor slice.

## Residual risk

- OneCore voice inventory varies by Windows installation.
- The validated machine proves English and Chinese OneCore voices are present, but other machines may lack required language voices.
- C007B still needs product-level tests for deterministic profile-to-installed-voice selection, artifact reuse, segment timing fit, and missing-voice handling.
- Real-machine validation covered the probe phrase and cancellation path; it did not yet validate full multi-segment narration for a real PicotooPet video.
