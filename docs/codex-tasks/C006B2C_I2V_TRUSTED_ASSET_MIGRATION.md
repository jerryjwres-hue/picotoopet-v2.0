# C006B2C — IMAGE_TO_VIDEO Trusted Asset Migration v1

## Objective

Migrate new IMAGE_TO_VIDEO shots from the legacy trusted_local_assets / trusted_input_asset_ref authority onto the C006B1/B2 trusted asset identity model.

Reuse C006B2B's frozen trusted asset snapshot and Windows verifier.
Do not create a second asset contract or verifier.

## Branch

feature/i2v-trusted-asset-migration-v1

Base:
5953190acff02357ea4d5a6a7a3993c944ef34c5

This base contains:
- C006A local-media execution
- C006B1 trusted asset registry/ingress
- C006B2A Creative trusted asset binding
- C006B2B EXISTING_ASSET frozen snapshot + Windows verifier

If PR #61 later reports a semantic blocker in C006B2B, stop and report before continuing past that dependency. Small analyzer/comment fixes may be incorporated normally.

## Core contract decision

Reuse ShotPlanItem.existing_asset_ref.

Do NOT add:
- image_asset_ref
- trusted_input_asset_id
- any new path field

Allowed meanings:
- EXISTING_ASSET: existing_asset_ref identifies the source image to normalize directly
- IMAGE_TO_VIDEO: existing_asset_ref identifies the trusted input image for the existing Wan I2V workflow

Other render intents must not carry existing_asset_ref.

Backward compatibility:
- legacy stored ShotPlan with IMAGE_TO_VIDEO and no existing_asset_ref must still deserialize
- old already-bound ProductionPlan using trusted_input_asset_ref must still deserialize/restart
- new Creative/Web-GPT I2V must use allowlisted asset_id

## Creative / Goal validation

Update ShotPlanItem semantics minimally so:
- EXISTING_ASSET may carry existing_asset_ref
- IMAGE_TO_VIDEO may carry existing_asset_ref
- other intents forbid it
- EXISTING_ASSET remains structurally required as today
- IMAGE_TO_VIDEO remains structurally optional only for legacy-deserialization compatibility

For new Creative quality/adoption:
- IMAGE_TO_VIDEO requires existing_asset_ref
- ref must be in source_set.trusted_asset_ids
- invented/cross-goal IDs fail closed
- no path/managed_relpath/url authority

Goal/Web GPT:
- reuse existing allowed_existing_assets
- reuse asset_allowlist_digest
- prompt instructions must state IMAGE_TO_VIDEO also copies only an allowlisted asset_id
- stale allowlist digest still rejected
- return validation must reject new I2V with missing/invented ref

Do not expose managed_relpath/sha/path in prompt.

## Production cutover

### Asset resolution

Extend ProductionService trusted-asset collection to include refs from:
- EXISTING_ASSET
- IMAGE_TO_VIDEO

Resolve through the same TrustedAssetService and same goal scope checks.

Use the exact existing ProductionTrustedAssetSnapshotV1 from C006B2B.

### New I2V plan

For new IMAGE_TO_VIDEO with existing_asset_ref:
- execution_backend = comfy
- execution_profile_id = existing Wan I2V profile
- workflow_id = existing Wan I2V workflow ID
- trusted_asset = required frozen C006B2B snapshot
- trusted_input_asset_ref = null
- no local_media

Do not change workflow/model IDs.

### ProductionTaskPlan validator

Evolve the closed COMFY rules:
- T2V: trusted_asset must remain null
- new I2V: trusted_asset required, trusted_input_asset_ref null
- legacy frozen I2V plan: trusted_asset null + trusted_input_asset_ref allowed
- no other COMFY combination accepted

The compatibility branch must be explicit and narrow.

### Compiler

New compilation must NOT use manifest["trusted_local_assets"] as authority.

For IMAGE_TO_VIDEO:
- if shot.existing_asset_ref resolves to frozen snapshot => Executable
- if missing/unresolvable in a new compile => NeedsHuman or bounded planning failure according to existing Production semantics; do not invent/fallback to paths

Do not generate trusted_input_asset_ref in new plans.

Keep legacy helper only if needed to parse/restart old frozen plans, not for new compile authority.

## Windows I2V execution

Reuse the C006B2B trusted asset verifier.

Before Comfy submit for a new I2V task:
1. require trusted_asset snapshot
2. resolve managed_relpath only under trusted Comfy input root
3. reject traversal/reparse
4. verify ordinary file
5. recompute bytes/SHA
6. decode MIME/width/height
7. require exact snapshot match
8. only then pass the already-safe managed relative path to existing ComfyWorkflowTemplateValidator.Bind() LoadImage slot

No absolute path enters workflow parameters.

Do not duplicate verifier logic. Extract/shared helper only if C006B2B has not already exposed a reusable internal primitive.

Legacy frozen plan:
- if trusted_asset is null and trusted_input_asset_ref is present on an old persisted I2V plan, retain current root/reparse-safe execution branch
- this branch is restart compatibility only
- do not write new plans in this form

Deterministic asset integrity failures must fail before Comfy submit and must not burn a second GPU attempt.

## Package provenance

For new I2V:
- reuse exactly C006B2B source_asset provenance block
- asset_id
- sha256
- media_type
- width
- height
- managed_root_id
- managed_relpath

I2V still records actual Wan I2V workflow/model provenance.

Legacy path-only plans:
- do not fabricate source_asset provenance if no frozen snapshot exists
- preserve existing package behavior for already-running legacy plan as safely as possible

No absolute/source paths.

## trusted_local_assets retirement

After this slice:
- new compiler no longer reads trusted_local_assets for I2V execution authority
- legacy field may remain in old Creative Package JSON but is ignored for new compilation
- do not delete schema/fields yet

Document future cleanup condition:
legacy removal only after no nonterminal persisted I2V plan remains with:
trusted_asset == null AND trusted_input_asset_ref != null

Do not implement destructive cleanup in C006B2C.

## Explicit exclusions

- no changes to Wan I2V workflow JSON
- no new Comfy workflow/model
- no video-file asset ingress
- no GENERATIVE_IMAGE
- no PRODUCT_ASSET_COMPOSITE
- no C007 narration changes
- no C008 overlay changes
- no C004 changes
- no Goal Center UI
- no S002 networking
- no Maotai/UI
- no deploy/macos
- no Natural Motion

## Expected files

Creative/Goal likely:
- src/picotoopet_core/creative/models.py
- creative/quality.py
- autonomous/goal_handoff_access.py
- autonomous/video_return.py
- focused tests

Production likely:
- src/picotoopet_core/production/models.py
- production/compiler.py
- production/service.py
- production/package.py only if provenance regression requires it
- focused tests

Windows likely:
- ProductionContracts.cs
- ProductionExecutionService.cs
- C006B2B shared trusted-asset verifier/helper
- focused I2V smoke tests

Do not redesign C006B1/B2 contracts.

## Required tests

### Creative
- legacy I2V without ref deserializes
- new I2V + allowlisted ref PASS
- new I2V missing ref rejected by quality/return boundary
- invented/cross-goal ref rejected
- EXISTING_ASSET rules unchanged
- other intents carrying ref rejected

### Web GPT
- prompt tells I2V to copy only allowed asset_id
- safe allowlist only
- stale asset_allowlist_digest rejected
- no path/managed_relpath leakage

### Production
- new I2V freezes same ProductionTrustedAssetSnapshotV1 as EXISTING_ASSET
- new I2V has trusted_input_asset_ref == null
- new compiler ignores trusted_local_assets for I2V authority
- unknown/cross-scope/bad MIME/root/facts fail closed
- T2V cannot carry trusted asset
- legacy frozen I2V plan with trusted_input_asset_ref still validates/restarts
- old bound ProductionJob replay does not recompile

### Windows
- new I2V snapshot fully reverified before any Comfy submit
- verified managed relative path is the only value bound into LoadImage
- hash/size/MIME/dimension/reparse mismatch blocks before submit
- deterministic asset failure does not consume second GPU attempt
- legacy path-only frozen I2V plan still executes under existing root/reparse checks
- no arbitrary path authority

### Package
- new I2V uses source_asset provenance
- Wan I2V workflow/model provenance remains
- legacy path-only package does not fabricate C006B1 identity

### Regression
- C001-C006B2B relevant Python tests
- C006A/B2B Windows smokes
- C004 compatibility
- Windows Release build
- Control Center self-test
- Ruff touched Python

## Acceptance

PASS when all newly compiled IMAGE_TO_VIDEO tasks use Core-issued trusted asset IDs/frozen snapshots, Windows re-verifies the same bytes before existing Wan LoadImage binding, while old already-frozen relative-ref plans can still restart safely.

## Delivery requirements

- commit all changes
- push to origin/feature/i2v-trusted-asset-migration-v1
- do not merge/rebase/tag/release
- working tree clean

Final response only:
remote branch
remote HEAD SHA
files changed
tests
architecture notes
residual risk
git status --short
