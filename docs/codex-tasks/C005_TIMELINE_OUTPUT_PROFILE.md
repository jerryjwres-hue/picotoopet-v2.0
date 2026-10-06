# C005 — Timeline & Output Profile Contract

## Goal

Make Creative timing become real Production render timing and introduce closed output profiles for landscape / vertical / square video without creating a second Production or post-production pipeline.

This task is the first implementation step from V001 after C004.

Branch:
`feature/video-timeline-output-profiles`

Baseline:
`866af949a1c7d180a867cabf17b6bcb669b856f9`

S002 may still be in flight independently. Do not touch its networking/session ownership files.

## Current reality

Creative already carries:
- CreativeBriefResult.duration_min_seconds / duration_max_seconds
- CreativeScriptResult.target_duration_seconds
- ScriptBeat.duration_seconds
- ShotPlanItem.duration_seconds
- CreativeBriefResult.content_format

Production currently ignores Creative duration and always emits:
- width=832
- height=480
- fps=24
- frame_count=81

Production only auto-executes GENERATIVE_VIDEO and IMAGE_TO_VIDEO.

## Architecture decision

Do NOT implement V001's proposed VideoMasterPlanV1 yet.

Reason:
- C005 timing/profile authority is needed before render
- ProductionPackage identity exists only after render
- a pre-render contract must not depend on post-render ProductionPackage facts

For C005:
- minimally extend existing Creative/Production contracts
- keep ProductionPlan as the authoritative pre-render plan
- reserve downstream PostProductionPlan / FinalArtifactReceipt for later C009/C010

## Closed video output profiles

Add one source-controlled allowlist owned by Mac Core:

- `video.landscape.v1`
  - width 832
  - height 480
  - fps 24
- `video.vertical.v1`
  - width 480
  - height 832
  - fps 24
- `video.square.v1`
  - width 640
  - height 640
  - fps 24

No caller may supply raw width / height / fps.

Use profile IDs only.

## Profile selection authority

The selected output profile must come from a strict, allowlisted Creative/Core contract.

Preferred minimal design:
- add `output_profile_id` to `CreativeBriefResult`
- type it as a strict Literal/enum of the three IDs above
- default to `video.landscape.v1` for backward compatibility with existing packages/returns
- update the Creative brief prompt/template so the model selects only one of the closed profile IDs based on the user's explicit creative objective/content-format intent
- Mac Core validates the value through the existing Creative quality/adoption path
- Production compiler reads the validated Creative Brief result from the Creative Package

Do NOT:
- infer profile in Windows
- parse arbitrary width/height from objective text in Production compiler
- allow GPT/UI to send dimensions/fps
- add arbitrary renderer configuration to ProductionJobCreateRequest

If an existing architecture-safe path already provides a stricter structured profile source, use it instead and document why.

## Timeline authority

Production compiler must consume `ShotPlanItem.duration_seconds` instead of always using frame_count=81.

Add bounded timing facts to the authoritative plan:
- plan-level `output_profile_id`
- plan-level `target_runtime_ms`
- task-level `target_duration_ms`

Keep the existing width / height / fps / frame_count task fields because Windows executes those frozen values.

## Frame-count mapping

The renderer must not silently truncate long Creative durations.

Implement one deterministic Core-owned duration -> frame_count policy.

Requirements:
- use the selected profile fps
- preserve the Wan workflow's valid frame-count shape; existing 81 and 121 strongly indicate the workflow-compatible 4n+1 family, but confirm this against the existing workflow/executor constraints before freezing the helper
- quantized rendered duration should approximate target duration with a small documented bound
- frame_count must remain <= existing MAX_FRAME_COUNT
- if a Creative shot duration cannot be represented safely within the frozen renderer limit, fail closed to NeedsHuman / bounded planning outcome; do not cap it and pretend the requested duration was honored
- same inputs always produce the same frame_count

Do not split one Creative shot into multiple Production tasks in C005. Shot splitting is out of scope.

## Timeline consistency

Before compiling:
- read `script.v1` and `shot_plan.v1`
- every shot beat already must resolve to validated script beats
- validate that the total shot target duration is reasonably consistent with the validated script target duration
- define and test an explicit tolerance
- reject clearly inconsistent packages rather than silently changing duration

Prefer preserving existing Creative tolerance semantics where sensible instead of inventing an unrelated threshold.

The plan's `target_runtime_ms` should be derived deterministically from authoritative target timing, not from observed render output.

## Backward compatibility

Existing persisted Creative Packages created before C005 may lack `output_profile_id`.

They must continue to compile using:
`video.landscape.v1`

Do not mutate old Creative Packages.

Existing C001/C002 Web GPT return validation must continue to work:
- adding the new Creative Brief field must not break old valid payloads
- the dynamic strict return schema should expose the field automatically if it derives from the Pydantic model
- no new provider/model/renderer authority

## Windows

Windows remains a closed executor.

Update only the strongly typed Production plan contract if needed so it can receive:
- output_profile_id
- target_runtime_ms
- target_duration_ms

Windows must continue to execute:
- width
- height
- fps
- frame_count
exactly as frozen by Core.

No Windows inference.

Do not touch:
- ControlCenterSession.Production.cs
- MacCoreClient.Production.cs
- ProductionClientHolder.cs
Those belong to S002.

Do not redesign C004 final assembly.

## Expected implementation surface

Mac Core:
- src/picotoopet_core/creative/models.py
- src/picotoopet_core/creative/profiles.py
- src/picotoopet_core/creative/quality.py only if timing/profile validation requires it
- src/picotoopet_core/production/profile.py
- src/picotoopet_core/production/models.py
- src/picotoopet_core/production/compiler.py
- related Production/Creative tests

Windows:
- ProductionContracts.cs only where necessary
- focused smoke/contract tests only where necessary

Avoid DB schema changes unless proven absolutely necessary. ProductionPlan JSON is already the durable source for these plan facts.

## Tests required

### Creative / compatibility
- valid explicit landscape/vertical/square Creative Brief profiles
- missing output_profile_id defaults to landscape for old payloads
- unknown profile rejected
- C001 external adoption still validates/replays

### Production compiler
- 3-second shot no longer compiles to hard-coded 81 unless the deterministic timing policy actually resolves to it
- duration -> frame_count is deterministic
- short/normal supported durations remain Executable
- unsupported over-limit duration fails closed, never truncates silently
- task target_duration_ms preserved
- plan target_runtime_ms deterministic
- script/shot timeline mismatch beyond tolerance rejected
- identical inputs produce identical plan digest

### Output profiles
- landscape -> 832x480@24
- vertical -> 480x832@24
- square -> 640x640@24
- no request/manifest field can inject raw dimensions/fps
- every task in one plan uses the plan's frozen profile dimensions/fps

### Windows contract
- new plan fields deserialize correctly
- executor still binds only frozen task values to Comfy workflow
- no new renderer authority added

### Regression
- Production compiler tests
- Creative quality/external adoption tests
- C001/C002 tests
- C003 autopilot tests
- C004 assembly tests
- Mac Core relevant regression
- Windows Control Center CI if Windows contracts change
- Ruff on touched Python files

## Explicit exclusions

- C006 render-intent expansion
- narration/TTS
- captions/text overlays
- transitions
- music/SFX
- new final compositor
- Delivery Receipt
- export variants
- publishing
- arbitrary FFmpeg filters
- arbitrary width/height/fps
- UI redesign
- Maotai/Natural Motion
- S002 Production HTTP lifecycle files

## Acceptance

PASS when:
1. Creative shot duration materially controls Production frame_count.
2. Production no longer freezes every shot to 81 frames.
3. Mac Core owns one closed output profile ID for the plan.
4. Landscape/vertical/square map to fixed tested dimensions/fps.
5. unsupported duration/profile input fails closed.
6. existing Goal -> Web GPT -> Creative -> Production -> C003 -> C004 paths remain regression-safe.
7. no second Production/Post-production lifecycle is introduced.

## Delivery requirements

After implementation and required tests:
- commit all C005 changes
- push to `origin/feature/video-timeline-output-profiles`
- do not rebase
- do not merge
- do not tag
- do not release
- working tree must be clean

Final response only:
remote branch
remote HEAD SHA
files changed
tests
architecture notes
residual risk
git status --short
