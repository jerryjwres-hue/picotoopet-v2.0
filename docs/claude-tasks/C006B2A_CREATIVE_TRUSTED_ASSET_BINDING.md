# C006B2A — Creative Trusted Asset Binding v1

## Objective
Bind C006B1 trusted asset identities into Creative/Goal video returns safely, without implementing Production EXISTING_ASSET execution yet.

## Branch
feature/creative-trusted-asset-binding-v1
Base: fa5f3e436ac302f78fc6bbb8968649a3cb117cbb

## Required behavior

1. Extend ShotPlanItem with:
- existing_asset_ref: optional logical trusted asset_id
- backward-compatible default None

2. Strict semantics:
- render_intent == EXISTING_ASSET => existing_asset_ref required
- all other render intents => existing_asset_ref must be None in v1
- unknown/invented asset IDs rejected
- no managed_relpath/path/URL/model/workflow/endpoint authority in Creative payloads

3. Core allowlist source
For Goal/Web-GPT handoff:
- obtain eligible assets only from C006B1 TrustedAssetService for scope:
  scope_kind=autonomous_goal
  scope_id=<goal_id>
- expose only safe metadata to the handoff prompt:
  asset_id, media_type, width, height, sha256
- never expose managed_relpath/source path/absolute path

4. GoalHandoffContext
Add a strict trusted-asset allowlist projection.
return_prompt must include it in the bound machine-return instructions.
If no assets exist, expose an empty list.

5. Source/quality binding
Extend NormalizedCreativeSourceSet minimally with trusted_asset_ids (default empty).
Its deterministic source identity/digest must bind the allowlist when present.

CreativeQualityGate SHOT_PLAN validation must enforce:
- EXISTING_ASSET ref is present and in source_set.trusted_asset_ids
- non-EXISTING_ASSET has no ref
- unknown refs yield bounded retry/reject code without leaking paths

6. Goal video return
validate_goal_video_return must preserve/bind the exact allowlist into the normalized source set.
The dynamic GoalVideoReturn JSON schema should expose existing_asset_ref automatically via ShotPlanItem.
Old payloads with no field remain valid.

7. Local Creative path
Do not invent a trusted-asset producer for local Creative in this slice.
With an empty trusted_asset_ids set, local model-produced EXISTING_ASSET must fail validation rather than accept invented IDs.

## Expected files
Likely:
- src/picotoopet_core/creative/models.py
- src/picotoopet_core/creative/source.py
- src/picotoopet_core/creative/quality.py
- src/picotoopet_core/autonomous/goal_handoff_access.py
- src/picotoopet_core/autonomous/video_return.py
- src/picotoopet_core/api/routes/autonomous_goals.py only for assets service wiring
- focused C001/C006B tests

Do not modify C006B1 asset registry semantics unless a proven defect blocks this slice.

## Forbidden
Do not modify:
- production/compiler.py
- production/models.py
- production/profile.py
- production/package.py
- ProductionExecutionService.cs
- ProductionContracts.cs
- C006A TEXT_CARD files
- C007 narration files
- C008 caption/overlay files
- C004 final assembly
- Windows asset ingress implementation
- S002 networking
- Maotai/UI
- deploy/macos
- Natural Motion

## Tests
- old ShotPlan without existing_asset_ref still validates
- EXISTING_ASSET without ref rejected
- EXISTING_ASSET with allowlisted ref passes
- invented/unknown ref rejected
- non-EXISTING_ASSET with ref rejected
- Goal handoff context lists only same-goal trusted assets
- cross-goal asset never appears
- prompt contains safe asset IDs/metadata but no managed_relpath/source path
- source-set digest changes when trusted asset allowlist changes
- external C001 return with allowlisted asset passes
- external return with invented asset fails
- local Creative with empty allowlist cannot accept EXISTING_ASSET
- C001/C002/C005 regressions pass
- Ruff touched files

## Acceptance
PASS when a Web-GPT/Creative ShotPlan can reference only Core-allowlisted C006B1 asset IDs, with no filesystem authority and no Production execution changes.

## Delivery requirements
- commit all C006B2A changes
- push to origin/feature/creative-trusted-asset-binding-v1
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
