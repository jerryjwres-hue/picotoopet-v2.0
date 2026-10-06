# S003 — Windows Local TTS Compatibility Spike

## Objective
Prove which credential-free local Windows TTS engine is compatible with the current PicotooPet Windows/.NET stack before C007B product integration.

This is a compatibility/engineering spike, not the final narration product.

## Branch
spike/windows-local-tts-compatibility

Base is the frozen C005 contract. C007A Core NarrationPlan is independently in CI.

## Candidates to evaluate
In this order unless repo/toolchain evidence disproves it:
1. System.Speech / Windows SAPI
2. Windows.Media.SpeechSynthesis

Do not add cloud TTS.
Do not add Piper/Coqui/other model runtimes in this spike.
Do not install external executables.

## Required proof
For each candidate that can be built in the repo's Windows toolchain, determine:
- can it compile under the repo's current Windows target framework?
- does it synthesize fully offline with no API key/account?
- can a fixed logical voice profile select an installed Windows voice deterministically enough for v1?
- can output be produced as WAV/PCM without shelling out?
- can cancellation and timeout be bounded?
- what happens when no compatible installed voice exists?
- what runtime/package dependency is required?

## Implementation
Create an isolated Windows-only probe, preferably under:
windows/tools/PicotooPet.TtsCompatibilityProbe/

Do not integrate into the main app yet.

The probe must:
- synthesize a fixed safe phrase
- write only under a temp/probe-managed directory
- verify the result has a valid WAV/PCM header and nonzero bounded size
- enumerate installed voices only for compatibility reporting
- never persist credentials
- never accept arbitrary executable/model/voice-file paths
- never use network/cloud providers

If a NuGet package is required for the probe, keep it scoped to the probe project only.
Do not change main PicotooPet.Desktop package dependencies in S003.

## CI/build integration
Prefer a separate project that can be built explicitly without modifying C006A-owned smoke Program.cs.

If adding the probe project to the main solution would create overlap with C006A, do NOT do that.
Instead provide one deterministic PowerShell build/run command for Windows CI/manual validation.

Do not modify production workflows or app behavior.

## Output
Add:
- probe source/project
- docs/claude-tasks/S003_WINDOWS_LOCAL_TTS_COMPATIBILITY.md if needed
- a concise result document:
  docs/architecture/video/S003_WINDOWS_LOCAL_TTS_RESULT.md

The result document must state exactly one of:
- RECOMMEND_SYSTEM_SPEECH
- RECOMMEND_WINDOWS_MEDIA_SPEECH
- NO_COMPATIBLE_LOCAL_ENGINE_PROVEN

and include concrete evidence.

## Explicitly forbidden
Do not modify:
- Production compiler/models/profile
- ProductionExecutionService
- C006A files
- C004 final assembly
- Goal Center
- ControlCenterSession.Production.cs
- MacCoreClient.Production.cs
- ProductionClientHolder.cs
- postproduction/narration.py
- postproduction API
- C007A tests
- Maotai/UI
- deploy/macos
- Natural Motion

## Tests / validation
At minimum:
- probe project builds on Windows
- fixed synthesis succeeds when a compatible installed voice exists
- output header/size validated
- missing compatible voice fails with bounded code/message
- cancellation/timeout path is bounded
- no network/provider/API-key/model-path/executable authority exists

If Claude's current container lacks Windows/.NET support:
- still implement the isolated probe
- push it
- clearly mark local validation UNVERIFIED
- do not fake PASS
- GitHub/real Windows validation will be handled by orchestrator

## Acceptance
S003 is PASS only when a real Windows build/run proves one local engine viable, or conclusively proves neither candidate viable.

## Delivery requirements
- commit all S003 changes
- push to origin/spike/windows-local-tts-compatibility
- do not rebase/merge/tag/release
- working tree clean

Final response only:
remote branch
remote HEAD SHA
files changed
local validation
recommended engine
evidence
residual risk
git status --short
