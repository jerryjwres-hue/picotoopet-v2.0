# C007A — Core NarrationPlan v1

## Objective
Implement the Mac Core deterministic narration-plan plane only.

Do NOT implement Windows TTS synthesis in this slice.
Do NOT modify visual Production execution or C004.

## Branch
feature/narration-plan-core-v1
Base: e82df96a7acddfb7cc2b26c023517b58716b226b

## Architecture
Narration is downstream audio planning, not a Production task.

CreativePackage + frozen C005 ProductionPlan
-> NarrationPlanV1
-> later C007B Windows local TTS
-> NarrationArtifact
-> future C009 compositor

## Contract
Create a strict frozen NarrationPlanV1 with:
- schema_version = 1.0
- production_job_id
- creative_package_id
- creative_package_digest
- production_plan_digest
- target_runtime_ms
- tts_profile_id
- voice_profile_id
- narration_required
- segments[]

NarrationSegmentPlan:
- segment_id
- beat_id
- order
- text
- text_sha256
- start_ms
- end_ms

No provider/url/api key/model path/voice file path/executable/command/rate/pitch/arbitrary SSML fields.

Initial closed logical IDs:
- tts_profile_id = narration.local.windows.v1
- voice_profile_id = voice.windows.default.v1
These are logical IDs only; Windows engine selection comes later.

## Timing source
C005 ProductionPlan is authoritative.

Algorithm:
1. load immutable CreativePackage and bound ProductionPlan for the production_job_id
2. read script.v1 and shot_plan.v1
3. walk Production tasks in order and accumulate task.target_duration_ms
4. map shot_id -> beat_id from ShotPlan
5. aggregate contiguous shot windows into one beat window
6. for each ScriptBeat with nonblank voiceover, emit exactly one segment for that beat window

Validation:
- every voiced beat maps to >=1 shot
- same beat shots form one contiguous interval
- beat order does not invert
- every window positive
- final end <= plan.target_runtime_ms
- Creative/Production identity digests must match
- ambiguity => NARRATION_TIMELINE_AMBIGUOUS

If all voiceover values are null/blank:
- narration_required=false
- segments=[]
- this is valid, not failure

## Digest / determinism
Compute canonical narration_plan_digest from the complete bounded plan.
Same CreativePackage + same ProductionPlan + same profiles => same digest.

Text is allowed in the plan because Windows TTS must synthesize it.
Do not persist another durable DB lifecycle for C007A.
Do not copy narration artifacts yet.

## Core module/API
Preferred new module ownership:
- src/picotoopet_core/postproduction/__init__.py
- src/picotoopet_core/postproduction/narration.py
  or narration_models.py + narration_service.py

Expose authenticated read-only API:
GET /api/v1/postproduction/production/{production_job_id}/narration-plan

Return plan + narration_plan_digest in a strict response contract.

Use existing Production/Creative repositories; no new table.

## Error model
Bounded codes:
- NARRATION_PLAN_NOT_READY
- NARRATION_TIMELINE_AMBIGUOUS
- NARRATION_SOURCE_MISMATCH
- NARRATION_PROFILE_UNSUPPORTED

Do not leak raw voiceover text in errors/logging, absolute paths, stack traces, or internal DB details.

## Explicit exclusions / forbidden files
Do not modify:
- production/compiler.py
- production/models.py
- production/profile.py
- ProductionContracts.cs
- ProductionExecutionService.cs
- C006A files
- MacCoreClient.Production.cs
- ControlCenterSession.Production.cs
- ProductionClientHolder.cs
- FinalVideoAssemblyService.cs
- GoalFinalVideoCoordinator.cs
- Goal Center UI/ViewModels
- Windows TTS code
- PicotooPet.Desktop.csproj
- SmokeTests/Program.cs
- Maotai/UI
- deploy/macos
- Natural Motion

C007A is Python/Core only plus API/tests.

## Tests
Core compiler:
- no voiceover => narration_required=false, no segments
- one voiced beat => exact window
- multiple shots same beat => one spanning window
- multiple beats => cumulative windows
- missing beat mapping rejected
- non-contiguous same-beat mapping rejected
- beat order inversion rejected
- final segment cannot exceed target runtime
- same inputs => same digest
- changed ProductionPlan digest => changed plan digest
- unknown voice/tts profile rejected
- extra provider/url/model/executable fields impossible

API:
- auth required
- exact production job lookup
- 404/not-ready mapping bounded
- invalid timeline => bounded typed error
- response contains no credentials/path/engine authority

Regression:
- C001-C005 relevant Python tests
- production restart/idempotency tests
- Ruff touched Python

## Acceptance
PASS when Mac Core can deterministically derive a strict narration plan from CreativePackage + C005 ProductionPlan without modifying Production lifecycle or C004.

## Delivery requirements
- commit all C007A changes
- push to origin/feature/narration-plan-core-v1
- do not rebase/merge/tag/release
- working tree clean

Final response only:
remote branch
remote HEAD SHA
files changed
tests
architecture notes
residual risk
git status --short
