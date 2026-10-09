# C007B — Windows Local Narration Synthesis v1

## Objective

Consume the authenticated C007A NarrationPlanV1 on Windows and synthesize bounded local WAV narration artifacts using the engine proven by S003.

This slice does NOT mux audio into video. C009 will compose audio later.

## Branch

feature/windows-local-narration-synthesis-v1

Base:
4f7d6e075ff88e1e939b62ef29994c2b5a0de8bf

## Proven engine

S003 native Windows validation proved:

- backend: Windows.Media.SpeechSynthesis
- offline/no credentials: PASS
- OneCore voices available
- WAV synthesis: PASS
- bounded cancellation: PASS
- System.Speech on the validated host: ENGINE_UNAVAILABLE

Therefore C007B MUST use Windows.Media.SpeechSynthesis.
Do not add System.Speech fallback.
Do not add cloud TTS.
Do not add Piper/Coqui/model runtimes.

Logical IDs remain:
- tts_profile_id = narration.local.windows.v1
- voice_profile_id = voice.windows.default.v1

## Architecture

Mac Core C007A remains the narration-plan authority.

Windows:
GET NarrationPlanV1
-> validate closed plan contract
-> deterministically resolve one installed OneCore voice
-> synthesize each narration segment locally
-> validate WAV
-> write immutable managed narration artifact manifest
-> restart-safe reuse

No Production lifecycle mutation.
No C004 mutation.
No video/audio mux in C007B.

## Windows API contract

Add strongly typed NarrationPlan records matching C007A.

Add a narrow authenticated GET client for:
GET /api/v1/postproduction/production/{production_job_id}/narration-plan

Preferred new files/partials:
- MacCoreClient.Narration.cs
- ControlCenterSession.Narration.cs
- Narration contracts file

Do not modify:
- MacCoreClient.Production.cs
- ControlCenterSession.Production.cs
- ProductionClientHolder.cs

The client must:
- URL-escape production job ID
- preserve auth/trace/bounded response handling patterns
- reject oversized response
- expose bounded typed API errors
- never log narration text

## TTS backend

Use Windows.Media.SpeechSynthesis directly in-process.

If the Desktop target framework must become versioned
(net10.0-windows10.0.19041.0) for WinRT projection, make only the minimal project change required and prove the full Windows build remains green.

No external executable.
No shell.
No network.
No provider/API key/account.
No caller-supplied voice name/registry ID/model/path.

## Deterministic voice selection

voice.windows.default.v1 is a logical profile, not an OS voice identity.

For v1 choose one voice for the entire narration plan:

1. Determine a closed language family from all segment text:
   - if any segment contains a CJK Unified Ideograph, choose zh-CN family
   - otherwise choose en-US family
2. Enumerate installed OneCore voices.
3. Keep only voices matching the selected family.
4. Deterministically order:
   - exact culture match first
   - DisplayName ordinal
   - Id ordinal
5. choose first.

Do not expose the selected OneCore registry ID as caller authority.

If no compatible voice exists:
NARRATION_VOICE_UNAVAILABLE

Do not fall back to cloud or another language family.

Persist only bounded resolved voice facts in the local manifest:
- resolved_voice_name
- resolved_voice_culture
- resolved_voice_identity_sha256
Do not persist the raw registry ID/path.

## Managed artifact layout

Use a PicotooPet-managed local root, e.g.:

%LOCALAPPDATA%\PicotooPet\Narration\v1\<production-job-id-safe>\

For each segment:
- deterministic filename derived from segment_id/text_sha256
- .wav output

Add one immutable local manifest containing:
- schema_version
- production_job_id
- creative_package_id/digest
- production_plan_digest
- narration_plan_digest
- tts_profile_id
- voice_profile_id
- resolved bounded voice facts
- ordered segment records:
  - segment_id
  - beat_id
  - order
  - text_sha256
  - start_ms
  - end_ms
  - wav filename only
  - wav sha256
  - wav bytes
  - wav sample rate/channels/bits
  - synthesized_duration_ms
- created_at

Do not persist raw narration text in the local artifact manifest.
Do not persist absolute paths.
Do not persist raw API response.

## WAV validation

Validate every synthesized output before promotion:
- RIFF/WAVE
- PCM
- mono or stereo
- 8–48 kHz
- 16-bit
- nonzero bounded data
- bounded total bytes

Prefer the actual S003-proven stream format, but do not assume all hosts return exactly 16 kHz unless product code verifies it.

If invalid:
NARRATION_WAV_INVALID

## Timing fit

C007A start_ms/end_ms are authoritative placement windows.

Synthesis must not modify those windows.

For every segment:
- synthesized duration must be > 0
- synthesized duration must be <= segment window duration + small fixed tolerance

Define one explicit small tolerance in code/tests.

If narration is too long:
NARRATION_SEGMENT_TOO_LONG

Do not silently truncate.
Do not change speaking rate in v1.
Do not rewrite text.

Shorter narration is valid; C009 may leave silence in the remaining window.

## Cancellation / timeout

Use CancellationToken with the WinRT async operation.
Set a bounded per-segment timeout.
On timeout:
NARRATION_TTS_TIMEOUT

Cancellation/timeout must not promote a partial WAV to durable success.

## Restart/idempotency

Artifact identity is bound to:
- narration_plan_digest
- logical profiles
- resolved bounded voice identity

If matching manifest + WAV files already exist:
- verify manifest identity
- verify every WAV hash/size/header
- reuse without synthesis

If manifest/output is partial or mismatched:
- fail closed with NARRATION_ARTIFACT_CONFLICT
- do not silently overwrite a conflicting durable artifact

Use temporary files then atomic promotion.

## Narration not required

If NarrationPlanV1 has narration_required=false and segments=[]:
- return a valid empty NarrationArtifact
- do not invoke SpeechSynthesizer
- persist/reuse a bounded empty manifest if useful
- do not treat as failure

## Error/status codes

Closed local errors:
- NARRATION_VOICE_UNAVAILABLE
- NARRATION_TTS_TIMEOUT
- NARRATION_TTS_FAILED
- NARRATION_WAV_INVALID
- NARRATION_SEGMENT_TOO_LONG
- NARRATION_ARTIFACT_CONFLICT
- NARRATION_PLAN_INVALID

Never include:
- narration text
- absolute path
- raw OneCore registry ID
- raw WinRT exception
- raw API body

## Suggested implementation files

New preferred files:
- windows/desktop/src/PicotooPet.Desktop.Core/Contracts/NarrationContracts.cs
- windows/desktop/src/PicotooPet.Desktop.Core/Networking/MacCoreClient.Narration.cs
- windows/desktop/src/PicotooPet.Desktop/Services/ControlCenterSession.Narration.cs
- windows/desktop/src/PicotooPet.Desktop/Services/WindowsNarrationSynthesisService.cs
- optional small internal WAV validator/voice selector files
- focused smoke tests

Minimal PicotooPet.Desktop.csproj target-framework change is allowed only if required for Windows.Media.SpeechSynthesis.

## Forbidden

Do not modify:
- C006A Production models/compiler/package/executor/local-media files
- C006B1 asset files
- C004 FinalVideoAssemblyService / Goal final-video coordinator
- C007A Core narration module/routes/tests
- C008A captions overlay files
- Production HTTP connection lifecycle files
- Goal Center UI/ViewModel
- Maotai/UI
- deploy/macos
- Natural Motion gate

Do not implement:
- audio/video mux
- background music/SFX
- captions
- speaking-rate controls
- arbitrary voice selection
- voice cloning
- SSML input
- publishing

## Required tests

Contracts/client:
- exact narration-plan GET path and URL escaping
- auth/trace headers
- bounded response
- no text logged on API failure
- malformed/extra fields rejected

Voice:
- Han text -> zh-CN family
- otherwise -> en-US
- deterministic sort
- one voice for full plan
- no compatible voice -> bounded failure
- caller cannot provide OS voice identity

Synthesis:
- fixed engine Windows.Media.SpeechSynthesis only
- valid WAV accepted
- bad/truncated/empty WAV rejected
- timeout/cancel leaves no durable partial
- segment-too-long fails closed
- no narration text in errors/manifest
- no absolute paths/raw registry IDs in manifest

Artifact:
- same verified plan + same resolved voice reuses artifact
- changed narration_plan_digest does not reuse
- tampered WAV fails closed
- partial manifest/output fails closed
- empty narration plan is valid and does not synthesize
- source text SHA remains bound to segment artifact

Regression:
- Windows Release build 0 errors
- existing C002–C006A relevant smokes
- Control Center self-test
- no Production/C004 regression

## Real-machine acceptance

CI/fakes cannot replace one real Windows acceptance:
- fetch/create one real NarrationPlan
- synthesize multiple segments using OneCore
- verify managed WAV files
- verify restart reuse
- verify Chinese and English selection when corresponding voices exist

## Acceptance

PASS when Windows can deterministically synthesize C007A narration segments into verified, restart-safe local WAV artifacts using only Windows.Media.SpeechSynthesis and closed logical profiles, without modifying Production or final video assembly.

## Delivery requirements

- commit all C007B changes
- push to origin/feature/windows-local-narration-synthesis-v1
- do not rebase
- do not merge
- do not tag
- do not release
- working tree clean

Final response only:
remote branch
remote HEAD SHA
files changed
tests
architecture notes
residual risk
git status --short
