# C006A — TEXT_CARD Render Intent v1

## Objective
Add deterministic TEXT_CARD execution to the existing Production lifecycle after C005. Do not implement EXISTING_ASSET, GENERATIVE_IMAGE, or PRODUCT_ASSET_COMPOSITE in this slice.

## Branch
feature/render-intent-text-card-v1
Base: e82df96a7acddfb7cc2b26c023517b58716b226b

## Reuse
- existing Production Job/Task/claim/lease/attempt/commit/package lifecycle
- C005 output_profile_id / target_runtime_ms / target_duration_ms / width / height / fps / frame_count
- ProductionExecutionService
- ProductionLocalEnvironment path/hash safety
- C004 unchanged final assembly
- existing two-attempt budget and restart filtering of Succeeded tasks

## Core contract changes
Extend ProductionTaskPlan minimally with:
- execution_backend: closed enum {comfy, local_media}
- execution_profile_id: closed allowlisted logical ID
- optional bounded local_media payload for TEXT_CARD containing only:
  - text_digest
  - text_content (bounded, validated source)
  - text_profile_id

Rules:
- GENERATIVE_VIDEO => comfy + current t2v profile
- IMAGE_TO_VIDEO => comfy + current i2v profile
- TEXT_CARD with valid text => Executable + local_media + production.local.text-card.v1 + workflow_id=null
- TEXT_CARD missing text => NeedsHuman
- GENERATIVE_IMAGE => NeedsHuman
- EXISTING_ASSET => NeedsHuman in C006A
- PRODUCT_ASSET_COMPOSITE => NeedsHuman
- unknown backend/profile rejected

Preferred text source:
1. ShotPlanItem.text_reference
2. matching ScriptBeat.on_screen_text
If neither exists, NeedsHuman. Do not call another model.

Comfy tasks still require workflow_id.
Local-media tasks must have workflow_id=null.

## Windows execution
Add a closed local-media renderer path under ProductionExecutionService dispatch.

Preferred new file:
ProductionLocalMediaRenderer.cs

TEXT_CARD v1:
- one frozen/source-controlled style
- no arbitrary font file/path
- no HTML/CSS
- no user/GPT FFmpeg filter graph
- no shell
- exact C005 width/height/fps/frame_count
- deterministic text rendering
- fixed internally authored ffmpeg args
- output normalized video/webm
- commit through existing ProductionTaskCommitRequest

If repository constraints make text->frame rendering require a new arbitrary dependency, stop and report before broadening.

## Attempt/commit semantics
- reserve existing Production task attempt before local rendering
- local-media may use comfy_prompt_id=null
- backend-aware validation:
  - comfy commit/attempt rules retain prompt identity requirements
  - local-media must not invent fake prompt IDs
- max two attempts
- partial output is not durable success
- after restart, Succeeded local-media tasks must be skipped exactly like Comfy tasks

## Package
Do not create a new package type.
ProductionPackage remains the only package.

Add backward-compatible provenance where appropriate:
- execution_backend
- execution_profile_id
- text_digest
Do not duplicate raw card text into ProductionPackage.

C004 must remain unchanged and consume the normalized WebM as an ordinary ordered output.

## Security
Mac Core owns intent/backend/profile/text selection/timing.
Windows executes only frozen values.
No arbitrary workflow/model/endpoint/path/command/font/filter authority.

## Explicit exclusions
- EXISTING_ASSET implementation
- trusted asset ingress
- GENERATIVE_IMAGE workflow
- PRODUCT_ASSET_COMPOSITE
- narration/TTS
- C004 changes
- S002 files:
  - MacCoreClient.Production.cs
  - ControlCenterSession.Production.cs
  - ProductionClientHolder.cs
- Goal Center UI
- Maotai/UI
- deploy/macos
- Natural Motion

## Likely files
Core:
- src/picotoopet_core/production/models.py
- profile.py
- compiler.py
- package.py
- repository.py only if backend-aware prompt validation requires it
- tests/production/*

Windows:
- ProductionContracts.cs
- ProductionExecutionService.cs
- new ProductionLocalMediaRenderer.cs
- focused smoke tests
C006A owns shared SmokeTests/Program.cs registration during this parallel slice.

## Required tests
- TEXT_CARD valid text => Executable/local_media/null workflow
- missing card text => NeedsHuman
- existing GENERATIVE_VIDEO/I2V behavior unchanged
- GENERATIVE_IMAGE/EXISTING_ASSET/PRODUCT_ASSET_COMPOSITE remain NeedsHuman
- unknown backend/profile rejected
- exact C005 width/height/fps/frame_count honored
- deterministic output identity for same task
- output is video/webm
- no font/path/filter/command authority
- attempt reserved before render
- local-media null prompt accepted only for local-media
- comfy rules unchanged
- max two attempts
- restart skips Succeeded local-media task
- mixed Comfy + TEXT_CARD produces one ProductionPackage
- workflow provenance includes only actual Comfy workflows
- C004 package consumer compatibility regression
- C001-C005 relevant regression
- Windows build + Control Center CI
- Ruff touched Python

## Acceptance
PASS when TEXT_CARD automatically becomes a verified timeline-compatible WebM inside the existing Production lifecycle, with no second executor/store/package and no regression to Comfy tasks.

## Delivery requirements
- commit all C006A changes
- push to origin/feature/render-intent-text-card-v1
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
