# G005 — IMAGE_TO_VIDEO Trusted Asset Migration v1

Status: architecture complete; docs-only  
Branch: design/image-to-video-trusted-asset-v1  
Architecture target: migrate IMAGE_TO_VIDEO from legacy `trusted_local_assets` / `trusted_input_asset_ref` path binding onto the C006B1 trusted asset identity model without changing the existing Comfy I2V workflow or creating a second asset/Production pipeline.

## 1. Executive decision

The smallest backward-compatible contract is:

> Reuse `ShotPlanItem.existing_asset_ref` for both `EXISTING_ASSET` and `IMAGE_TO_VIDEO`.

Do **not** add:

- `image_asset_ref`
- `trusted_input_asset_id`
- a second I2V-only asset registry
- a second frozen asset snapshot type

`existing_asset_ref` is interpreted as an opaque C006B1 Core-issued `asset_id`, not as a UUID that Creative is allowed to synthesize.

The field name is slightly broader than its original C006B2A wording, but reusing it is materially safer and more compatible than introducing a second field for the same C006B1 image identity.

For new IMAGE_TO_VIDEO work:

```text
Creative existing_asset_ref
        ↓
C006B1 TrustedAssetRecordV1
        ↓
same frozen Production trusted-asset snapshot used by EXISTING_ASSET
        ↓
Windows use-time verification
        ↓
verified managed relative path
        ↓
existing Comfy I2V LoadImage slot
```

No new workflow, model, endpoint, executable, or path authority is introduced.

---

## 2. Repository audit — current facts

### 2.1 C006B1 is the only trusted image identity authority

Current C006B1 defines an immutable image registry with:

- `asset_id`
- `scope_kind`
- `scope_id`
- `scope_key`
- `managed_root_id = windows.comfy-input.v1`
- `managed_relpath`
- `sha256`
- `size_bytes`
- `media_type = image/png | image/jpeg`
- `width`
- `height`
- `duration_ms = null`
- provenance

Windows ingress installs bytes under the existing Comfy input root:

```text
ComfyUI/input/PicotooPet/assets/v1/<sha-prefix>/<sha>.png|jpg
```

The final relative path is derived from SHA + canonical MIME, not from the user filename.

Therefore IMAGE_TO_VIDEO should consume this identity directly.

### 2.2 C006B2A already established the Creative allowlist boundary

Current C006B2A adds:

```text
ShotPlanItem.existing_asset_ref
```

and the Goal/Web GPT handoff already includes:

```text
allowed_existing_assets[]
asset_allowlist_digest
```

Safe allowlist fields are currently:

- asset_id
- media_type
- width
- height

The prompt does not expose:

- managed_relpath
- source path
- absolute path
- Comfy root
- executable/model/workflow authority

The video return validator already gathers every non-null `existing_asset_ref`, requires a matching `asset_allowlist_digest`, and rejects references outside the same-goal allowlist.

This is already the correct security boundary for I2V. G005 should widen its intent semantics, not create another allowlist.

### 2.3 C006B2A currently restricts existing_asset_ref to EXISTING_ASSET only

Current `ShotPlanItem` validation says:

```text
EXISTING_ASSET       -> existing_asset_ref required
every other intent   -> existing_asset_ref forbidden
```

Current CreativeQualityGate repeats the same rule.

Therefore IMAGE_TO_VIDEO cannot currently carry a C006B1 asset identity even though the allowlist machinery already exists.

### 2.4 Current Production I2V still uses legacy path mapping

Current compiler reads:

```text
manifest["trusted_local_assets"][shot_id]
```

through `_trusted_asset_ref()`.

If present for an IMAGE_TO_VIDEO shot, the compiler writes that string into:

```text
ProductionTaskPlan.trusted_input_asset_ref
```

and makes the task executable with the fixed I2V workflow.

The legacy value is a managed-relative path-like string, not a C006B1 `asset_id`.

Repository audit originally found no authoritative producer for `trusted_local_assets`. C006B1/C006B2A now provide the real identity system that should replace it.

### 2.5 Windows I2V already has the correct final workflow slot

The fixed I2V workflow contains one:

```text
LoadImage.image = __PICOTOO_TRUSTED_INPUT_IMAGE__
```

`ComfyWorkflowTemplateValidator.Bind()` already accepts only a non-rooted, non-`..` relative string for this slot.

Current `ProductionExecutionService` resolves `trusted_input_asset_ref` under the trusted Comfy input root before passing the relative path to the binder.

Therefore the I2V workflow itself does not need to change.

### 2.6 Current Windows validation is path-bound, not content-bound

Current I2V `ValidateTrustedInput()` verifies:

- relative input exists under the trusted input root
- no root escape/reparse escape

It does **not** verify against Core-frozen:

- asset_id
- SHA
- size
- MIME
- dimensions

That is the principal execution gap G005 must close.

### 2.7 C006B2B is in progress and owns the first frozen trusted-asset Production snapshot

The remote `feature/existing-asset-production-v1` currently contains the C006B2B task specification but no pushed implementation changes beyond that task file at the time of this audit.

Its required architecture already defines one frozen trusted asset snapshot for EXISTING_ASSET containing bounded C006B1 facts and requires Windows to re-verify those facts before local-media execution.

G005 must reuse the exact snapshot type/field that C006B2B lands with.

If C006B2B chooses a concrete name different from the examples in this document, the G005 implementation must reuse the landed type rather than introduce another I2V-specific snapshot.

---

## 3. Creative contract

### 3.1 Chosen field

Keep:

```text
existing_asset_ref: str | None
```

Its v1 semantic becomes:

> A Core-issued, allowlisted C006B1 trusted still-image `asset_id` for render intents that consume an existing image source.

The allowed intents become:

```text
EXISTING_ASSET
IMAGE_TO_VIDEO
```

### 3.2 Why not image_asset_ref

Adding `image_asset_ref` would create two names for the same C006B1 image identity and would require:

- a second Web GPT schema field
- a second allowlist rule
- duplicate quality validation
- migration between two Creative fields
- ambiguity when an image is usable for either EXISTING_ASSET or IMAGE_TO_VIDEO

There is no repository capability that justifies that duplication.

### 3.3 Why not trusted_input_asset_id

That name is closer to Production execution and leaks executor semantics into Creative.

Creative should choose:

- what asset is being referenced
- what render intent is desired

Production decides how that asset becomes an execution input.

Therefore `existing_asset_ref` remains the renderer-neutral Creative reference.

### 3.4 asset_id is opaque

Although the current C006B1 service deterministically issues UUID-shaped IDs, Creative must treat `asset_id` as opaque.

Correct authorization is:

```text
exact ID is present in the Core-provided allowlist
```

not:

```text
string looks like a UUID
```

A syntactically valid invented UUID is still invalid.

---

## 4. ShotPlan compatibility rule

To preserve old persisted IMAGE_TO_VIDEO ShotPlans, the Pydantic model layer must not suddenly require an asset reference for every I2V document it deserializes.

The compatibility shape should be:

```text
EXISTING_ASSET:
    existing_asset_ref REQUIRED

IMAGE_TO_VIDEO:
    existing_asset_ref OPTIONAL at raw schema/read layer

all other render intents:
    existing_asset_ref MUST be null
```

Why IMAGE_TO_VIDEO remains optional at the read layer:

- old CreativePackages already persisted before G005 may contain I2V shots without this field
- the B2A serializer already omits absent fields to keep legacy canonical payloads stable
- "old document remains readable" is different from "old document receives new execution authority"

New Creative output is made strict in the quality/adoption gate, not by making legacy documents unreadable.

---

## 5. New Creative quality rule

For every newly evaluated SHOT_PLAN:

```text
if render_intent in {EXISTING_ASSET, IMAGE_TO_VIDEO}:
    existing_asset_ref must be present
    existing_asset_ref must be in source_set.trusted_asset_ids
else:
    existing_asset_ref must be null
```

Bounded failure codes should remain in the existing trusted-asset family, for example:

- `TRUSTED_ASSET_REF_INVALID`
- `UNKNOWN_TRUSTED_ASSET_REF`

No correction message should echo an untrusted/invented ID.

This preserves the existing C006B2A security pattern.

---

## 6. Web GPT contract

### 6.1 Reuse the existing allowlist

Do not add a second list.

Keep:

```text
allowed_existing_assets
asset_allowlist_digest
```

The safe projection remains:

- asset_id
- media_type
- width
- height

There is no reason for Web GPT to receive SHA, bytes, or managed path information.

### 6.2 Prompt wording migration

Current prompt says only EXISTING_ASSET may use `existing_asset_ref`.

Change the instruction to:

```text
Only EXISTING_ASSET and IMAGE_TO_VIDEO shots may set existing_asset_ref.
The value must be copied exactly from allowed_existing_assets[].asset_id.
Do not invent or transform an asset ID.
If either intent uses an asset reference, return asset_allowlist_digest unchanged.
If the allowlist is empty, do not use EXISTING_ASSET or IMAGE_TO_VIDEO.
All other render intents must omit existing_asset_ref.
```

### 6.3 Return validation

Current `validate_goal_video_return()` already:

- gathers every non-null `existing_asset_ref`
- verifies `asset_allowlist_digest`
- checks all refs are in the current same-goal allowlist

After the ShotPlan model permits I2V references, this existing mechanism naturally covers both intents.

Do not create a second I2V allowlist digest.

### 6.4 Cross-scope protection

Goal handoff assets are still loaded only from:

```text
scope_kind = autonomous_goal
scope_id = current goal_id
```

Therefore a valid asset ID from another Goal must never appear in the prompt allowlist and must be rejected on return.

---

## 7. Local Creative behavior

C006B2A intentionally did not invent an automatic local-Creative asset discovery mechanism.

Current `NormalizedCreativeSourceSet` already has:

```text
trusted_asset_ids: list[str]
```

and defaults it to an empty list.

G005 keeps that authority model:

- local Creative may reference only IDs already bound into `source_set.trusted_asset_ids`
- local Creative must not query Windows or synthesize asset IDs
- if the trusted asset set is empty, new IMAGE_TO_VIDEO/EXISTING_ASSET output must fail the quality gate and be corrected to another valid intent or escalated

If the local SHOT_PLAN model context exposes the asset list, it must expose only the Core-bound IDs/closed safe projection. It must not auto-enumerate Windows files.

Automatic project-scope asset discovery is a separate product integration and is not required for G005 Goal/Web-GPT migration.

---

## 8. Shared frozen Production snapshot

### Decision

YES.

`EXISTING_ASSET` and `IMAGE_TO_VIDEO` must share exactly one frozen C006B1 snapshot model.

Do not create:

- `I2VTrustedAssetSnapshot`
- `ImageToVideoAssetInput`
- another asset projection with different semantics

G005 consumes the exact snapshot type established by C006B2B.

Semantically it contains the immutable execution facts:

```text
asset_id
scope_kind
scope_id
managed_root_id
managed_relpath
sha256
size_bytes
media_type
width
height
```

Closed v1 constraints:

```text
managed_root_id = windows.comfy-input.v1
media_type      = image/png | image/jpeg
```

No source path, URL, filename, endpoint, model, workflow, executable, or command belongs in this snapshot.

---

## 9. Production resolution authority

### 9.1 ProductionService resolves asset identities

The compiler must not read Windows or query filesystem paths.

For an unbound Production Job:

1. read the immutable Creative Package
2. parse ShotPlan
3. collect `existing_asset_ref` for:
   - EXISTING_ASSET
   - IMAGE_TO_VIDEO
4. resolve each asset ID through C006B1 TrustedAssetService
5. verify exact scope binding
6. verify closed C006B1 facts
7. construct/reuse the shared frozen snapshot
8. pass the resolved snapshot map to the deterministic compiler
9. save the immutable ProductionPlan and plan digest

### 9.2 Scope check

The primary invariant is:

```text
trusted_asset.scope_key == creative_job/project Production project_key
```

For Goal video today:

```text
creative project_key
= autonomous-goal:<goal_id>

asset scope_key
= autonomous-goal:<goal_id>
```

Cross-scope mismatch fails closed.

No asset with the same SHA from another Goal is a substitute.

### 9.3 Frozen fact validation

Before snapshot creation Core must verify:

- asset exists
- exact scope_key matches
- artifact type is image
- managed_root_id is `windows.comfy-input.v1`
- MIME is PNG/JPEG
- SHA is valid
- size is positive and within C006B1 bounds
- width/height are valid
- duration is null in the source C006B1 record
- managed_relpath equals the canonical C006B1 derivation from SHA + MIME

Caller/Creative fields never supply these facts.

---

## 10. New I2V ProductionTaskPlan

For a newly compiled IMAGE_TO_VIDEO task after G005:

```text
render_intent          = IMAGE_TO_VIDEO
execution_disposition  = Executable
execution_backend      = comfy
execution_profile_id   = comfy.wan22.ti2v5b.i2v.v1
workflow_id            = comfy.wan22.ti2v5b.i2v.v1

trusted_asset_snapshot = REQUIRED
trusted_input_asset_ref = null
```

The exact snapshot field name must be the one landed by C006B2B.

### Critical migration rule

For **new** snapshot-backed plans, `trusted_input_asset_ref` must not be populated.

The old field remains only as a legacy deserialization/execution bridge for already-persisted ProductionPlans.

The managed relative path needed by Comfy is obtained at Windows execution time from the verified frozen snapshot.

This is what actually removes path mapping from new Production authority.

---

## 11. New compiler behavior

The legacy compiler helper:

```text
_trusted_asset_ref(manifest, shot_id)
    -> manifest["trusted_local_assets"][shot_id]
```

must no longer participate in new I2V compilation after the cutover.

New logic:

```text
shot.render_intent == IMAGE_TO_VIDEO
        ↓
shot.existing_asset_ref
        ↓
resolved_assets[asset_id]
        ↓
shared frozen snapshot
        ↓
I2V executable task
```

If a new Creative Package contains:

```text
IMAGE_TO_VIDEO
existing_asset_ref = null
```

the compiler must not recover execution authority from `trusted_local_assets`.

It becomes non-executable / NeedsHuman according to the existing compiler semantics.

This is intentional.

---

## 12. Old CreativePackage compatibility

Old CreativePackages may contain:

```text
IMAGE_TO_VIDEO
existing_asset_ref absent
trusted_local_assets[shot_id] present
```

They must remain readable.

However, after the G005 cutover:

> an old CreativePackage that has not yet received an immutable ProductionPlan does not automatically gain execution authority from the legacy path map.

Therefore:

```text
old CreativePackage + no bound ProductionPlan
+ I2V without C006B1 asset_id
    -> readable
    -> compile as NeedsHuman
```

Do not auto-convert an arbitrary legacy relative path into a new asset identity.

A future explicit migration/import tool could do that only by registering/validating bytes through C006B1, but G005 does not invent such a tool.

---

## 13. Old ProductionPlan compatibility

This is different from old CreativePackage handling.

Production plans are immutable after `plan_digest` is bound. Existing restart behavior explicitly reuses the durable plan and does not recompile it under new software semantics.

Therefore already-persisted legacy I2V ProductionPlans must remain readable and resumable.

A legacy I2V task is identifiable as:

```text
render_intent == IMAGE_TO_VIDEO
workflow_id == fixed I2V workflow
trusted_asset_snapshot == null
trusted_input_asset_ref != null
```

During the compatibility period Windows may execute this frozen legacy task through the existing relative-path safety boundary.

This is not a new arbitrary-path surface because:

- the legacy value is already frozen in an immutable Core ProductionPlan
- the Production create request cannot supply a path
- post-cutover Creative/Production compilation cannot create new path-only I2V plans
- Windows still rejects rooted/traversal/reparse escape

The compatibility branch exists solely for restart safety.

---

## 14. Windows new-snapshot verification

For a new I2V task, Windows must use the same trusted asset verifier introduced/used by C006B2B.

Do not duplicate the verifier.

Input:

- trusted Comfy input root from existing Production preflight
- shared frozen asset snapshot

Verification order:

1. require `managed_root_id == windows.comfy-input.v1`
2. recompute canonical managed relpath from frozen SHA + MIME
3. require that it equals frozen `managed_relpath`
4. resolve `managed_relpath` under the trusted input root
5. reject rooted/traversal escape
6. reject reparse/symlink/ancestor escape
7. require ordinary existing file
8. verify exact byte size
9. recompute SHA-256 and compare
10. decode the bytes as PNG/JPEG
11. verify actual MIME
12. verify actual width
13. verify actual height

Only after all checks pass does the verifier return the managed relative path.

The absolute Windows path remains local implementation state and never crosses to Core/Creative/GPT.

---

## 15. Attempt ordering for new I2V validation

To converge deterministic asset-integrity failures durably, the active Production attempt must exist before final use-time asset verification that can terminate the task.

Recommended order for the new snapshot-backed I2V branch:

```text
claim
  ↓
load fixed I2V template
  ↓
reserve existing Production attempt (prompt_id = null)
  ↓
verify frozen trusted asset against local bytes
  ↓
derive verified managed relative path
  ↓
bind fixed workflow
  ↓
submit Comfy prompt
  ↓
bind prompt_id to same attempt
  ↓
wait/commit
```

Asset integrity failures are non-retryable and should use the existing durable Production failure path with `comfy_prompt_id = null`.

Examples:

- trusted asset missing
- reparse/escape
- canonical relpath mismatch
- size mismatch
- SHA mismatch
- MIME mismatch
- dimension mismatch

They must not consume a second Comfy attempt.

Transient Comfy/HTTP/history failures continue to use the existing two-attempt policy.

No new attempt table or retry counter is introduced.

---

## 16. Legacy Windows execution branch

During compatibility only:

```text
snapshot == null
trusted_input_asset_ref != null
IMAGE_TO_VIDEO
fixed I2V workflow
```

may use a renamed/isolated legacy verifier equivalent to the current root-bounded behavior.

It must still enforce:

- non-empty relative reference
- trusted Comfy input root
- no rooted path
- no traversal
- no link/reparse escape
- ordinary existing file

It cannot perform SHA/MIME/dimension comparison because those facts do not exist in the old immutable plan.

Do not fabricate a snapshot from current filesystem state.

The legacy branch must never be reachable for newly compiled plans.

---

## 17. Safe handoff to Comfy LoadImage

The Comfy I2V workflow remains unchanged.

After verification, Windows holds only a safe managed relative string such as:

```text
PicotooPet/assets/v1/ab/<sha>.png
```

That verified relative path is passed as the existing `trustedInputImage` argument to:

```text
ComfyWorkflowTemplateValidator.Bind()
```

The binder continues to replace exactly one:

```text
LoadImage.image = __PICOTOO_TRUSTED_INPUT_IMAGE__
```

slot.

No caller/GPT/Core-supplied workflow JSON is introduced.

No new workflow ID is introduced.

No model selection changes.

---

## 18. Plan provenance

### New plans

The Production plan digest naturally binds the entire frozen trusted asset snapshot.

Therefore the new plan identity is bound to:

- asset_id
- scope
- canonical managed identity
- SHA
- bytes
- MIME
- dimensions
- fixed I2V workflow/profile
- existing prompt/timing/seed facts

Same Creative Package + same asset record -> same semantic frozen input facts.

A changed asset identity/fact set cannot silently reuse the same plan.

### Existing plans

Never rewrite a bound legacy plan to inject a snapshot.

That would invalidate its original plan digest and break immutable restart semantics.

Legacy plans are read through compatibility fields only.

---

## 19. Production Package provenance

IMAGE_TO_VIDEO should use the exact same trusted-asset provenance block that C006B2B establishes for EXISTING_ASSET.

Do not create an I2V-specific provenance object.

For new I2V output, package provenance should include the shared bounded snapshot facts defined by C006B2B, such as:

- asset_id
- managed_root_id
- managed_relpath
- sha256
- size_bytes
- media_type
- width
- height

Do not include:

- user source path
- original filename
- absolute Windows path
- raw bytes

I2V still genuinely uses Comfy, so package workflow/model provenance remains present exactly as it is today for the fixed I2V workflow.

For a legacy path-only ProductionPlan that finishes during the compatibility window:

- do not fabricate C006B1 asset provenance
- keep the original plan digest as the immutable input binding evidence
- no source absolute path is added to the package

C004 ignores these extra provenance fields and remains unchanged.

---

## 20. Retry, restart, and idempotency

### New job creation

ProductionService resolves assets only when the job has no bound plan.

Once `plan_digest` exists:

```text
replay/restart -> reuse stored plan
```

Do not re-query assets and rebuild a different snapshot.

### Windows restart

Succeeded I2V tasks continue to be filtered from the claim plan by the existing Production recovery logic.

Unfinished new I2V task:

```text
restart
  -> claim
  -> use same frozen snapshot
  -> reverify local bytes
  -> execute
```

Unfinished legacy I2V task:

```text
restart
  -> claim
  -> use same frozen legacy relative ref
  -> legacy root-bounded validation
  -> execute
```

### Asset registry changes

A new asset imported later does not change an existing ProductionPlan.

There is no "find another similar image" fallback.

---

## 21. Deprecating trusted_local_assets safely

### Phase 1 — Creative dual-read compatibility

Ship Creative schema changes first:

- old I2V without `existing_asset_ref` still parses
- new evaluated I2V requires allowlisted `existing_asset_ref`
- Web GPT prompt authorizes I2V to use the existing allowlist

No Production path behavior changes yet.

### Phase 2 — New Production cutover

After C006B2B snapshot model is frozen:

- resolve I2V `existing_asset_ref` through C006B1
- freeze the same B2B snapshot
- stop reading `manifest["trusted_local_assets"]` for new I2V plans
- do not populate `trusted_input_asset_ref` on new snapshot-backed I2V plans

At this point there is no new path-mapping authority.

### Phase 3 — Windows dual execution compatibility

Windows supports:

```text
new:
    frozen trusted asset snapshot -> full content verification -> LoadImage

legacy:
    old trusted_input_asset_ref -> root/reparse verification -> LoadImage
```

The branch is selected only from the immutable stored task shape.

### Phase 4 — Package provenance cutover

New I2V outputs emit the same B2B trusted asset provenance as EXISTING_ASSET.

Legacy outputs do not claim asset provenance they never had.

### Phase 5 — Retirement gate

Keep legacy `trusted_input_asset_ref` parsing/execution until there are no unfinished legacy I2V tasks.

Retirement condition:

```text
count of nonterminal IMAGE_TO_VIDEO Production tasks where:
    trusted_asset_snapshot is absent
    and trusted_input_asset_ref is present
== 0
```

Only after that condition is verified on supported installations may a later cleanup task:

- remove the legacy Windows execution branch
- remove `_trusted_asset_ref()`
- remove any remaining compiler awareness of `trusted_local_assets`
- eventually remove `trusted_input_asset_ref` from the next Production contract version

Do not tie retirement only to elapsed time.

---

## 22. trusted_local_assets after cutover

The Creative Package manifest may still physically contain a legacy `trusted_local_assets` key in old persisted packages.

After Phase 2:

- it is ignored for new plan authority
- it is not copied into new frozen trusted asset snapshots
- it is not exposed to GPT
- it is not used to resolve filesystem inputs
- it is not emitted by any new trusted asset flow

Old manifests remain readable as dictionaries.

No destructive migration of old CreativePackage blobs is required.

---

## 23. No arbitrary path authority

After new-plan cutover, the only path-like value in the new I2V execution contract is:

```text
snapshot.managed_relpath
```

That value is safe because:

1. it comes from the C006B1 Core registry
2. C006B1 derives it from SHA + canonical MIME
3. Production revalidates that derivation before freezing
4. Windows re-derives it again before filesystem use
5. it resolves only beneath the fixed Comfy input root
6. Windows verifies size/SHA/MIME/dimensions
7. Creative/GPT never sees or supplies it

Thus it is not arbitrary path authority.

---

## 24. GENERATIVE_IMAGE / PRODUCT_ASSET_COMPOSITE

No change.

```text
GENERATIVE_IMAGE
    -> NeedsHuman

PRODUCT_ASSET_COMPOSITE
    -> NeedsHuman
```

G005 does not introduce:

- static image generation workflow
- composite templates
- multi-asset layering
- video-file asset ingress

---

## 25. C004 / C007 / C008

No changes.

### C004

I2V already produces ordinary `video/webm` through the same fixed workflow.

C004 consumes only ordered Production output facts and does not inspect source asset identity.

### C007

Narration is downstream and independent.

### C008

Caption/overlay planning/rendering is downstream and independent.

G005 must not modify any of their files.

---

# READY_TO_IMPLEMENT

**YES, after C006B2B is completed and frozen.**

The architecture decision is complete:

- Creative reuses `existing_asset_ref`
- both EXISTING_ASSET and IMAGE_TO_VIDEO reference C006B1 `asset_id`
- both share exactly one B2B frozen trusted asset snapshot
- new I2V plans no longer carry `trusted_input_asset_ref`
- Windows verifies the snapshot and passes only the verified managed relative path to the unchanged fixed Comfy `LoadImage` slot
- legacy bound ProductionPlans retain a temporary root-bounded compatibility path for restart safety
- old unplanned CreativePackages do not gain new execution authority from `trusted_local_assets`

No unresolved architecture decision remains.

Implementation must not begin by modifying the active C006B2B branch. It should start from the accepted C006B2B result.

# NEXT IMPLEMENTATION SLICE

**C006B2C — IMAGE_TO_VIDEO Trusted Asset Migration v1**

Recommended implementation scope after C006B2B acceptance:

1. widen `ShotPlanItem.existing_asset_ref` semantics to IMAGE_TO_VIDEO while keeping old I2V documents readable
2. update Creative quality gate so every new I2V requires an allowlisted asset ID
3. update Goal/Web GPT prompt wording; reuse existing allowlist/digest and return validation
4. extend ProductionService asset resolution to I2V using the same C006B2B snapshot
5. change new I2V compilation to snapshot-backed execution and stop reading `trusted_local_assets`
6. leave `trusted_input_asset_ref` only as legacy ProductionPlan compatibility
7. reuse the C006B2B Windows trusted asset verifier before Comfy I2V binding
8. preserve the existing I2V workflow and LoadImage slot
9. emit the same B2B trusted asset package provenance for new I2V outputs
10. add dual-read compatibility and retirement tests

Do not implement a separate I2V asset model or renderer.

# MIGRATION PLAN

**Stage A — prerequisite freeze**

- C006B1 accepted
- C006B2A accepted
- C006B2B accepted
- record the exact landed B2B trusted snapshot field/type and Windows verifier
- do not duplicate either in G005

**Stage B — Creative semantic widening**

- `existing_asset_ref` allowed for IMAGE_TO_VIDEO
- legacy I2V without ref remains deserializable
- new SHOT_PLAN quality requires an allowlisted ref
- Web GPT prompt wording allows both EXISTING_ASSET and I2V
- current asset allowlist digest remains unchanged

**Stage C — Core Production cutover**

- ProductionService resolves I2V asset IDs from C006B1
- exact scope/facts validated
- same B2B snapshot frozen into I2V task
- new I2V task sets legacy `trusted_input_asset_ref = null`
- compiler stops reading `trusted_local_assets` for new authority
- old unplanned CreativePackages without an asset ID become NeedsHuman

**Stage D — Windows dual-read**

- snapshot-backed I2V: reserve attempt -> full snapshot/file verification -> fixed workflow bind -> Comfy submit
- legacy bound I2V plan: existing relative-ref compatibility verifier only
- deterministic snapshot failures become durable non-retryable Production failures
- Comfy transport/runtime failures keep existing retry policy

**Stage E — provenance**

- new I2V package outputs reuse exact B2B trusted asset provenance
- legacy path-only outputs do not fabricate trusted asset provenance
- workflow/model provenance remains the existing fixed I2V provenance

**Stage F — deprecation retirement**

- inventory unfinished legacy I2V tasks
- retain legacy field/Windows branch until count reaches zero
- follow-up cleanup task removes legacy compiler helper/path execution
- remove serialized `trusted_input_asset_ref` only in a later contract version

# FILES OWNERSHIP

## G005 docs-only task

Owns only:

```text
docs/architecture/video/G005_I2V_TRUSTED_ASSET_MIGRATION_V1.md
```

## Recommended C006B2C implementation ownership — after C006B2B is finished

Creative / Goal:

```text
src/picotoopet_core/creative/models.py
src/picotoopet_core/creative/quality.py
src/picotoopet_core/autonomous/goal_handoff_access.py
src/picotoopet_core/autonomous/video_return.py
focused Creative/Goal tests
```

Potential local-Creative context file only if required to expose the already-bound source-set allowlist:

```text
src/picotoopet_core/creative/execution.py
```

Production:

```text
src/picotoopet_core/production/compiler.py
src/picotoopet_core/production/service.py
src/picotoopet_core/production/models.py
src/picotoopet_core/production/package.py
focused Production tests
```

Windows:

```text
windows/desktop/src/PicotooPet.Desktop.Core/Contracts/ProductionContracts.cs
windows/desktop/src/PicotooPet.Desktop/Services/ProductionExecutionService.cs
the exact shared trusted-asset verifier landed by C006B2B
focused I2V smoke tests
SmokeTests/Program.cs only under one integration owner
```

Use, but do not redesign:

```text
src/picotoopet_core/assets/**
TrustedAssetIngressService.cs
TrustedAssetContracts.cs
ComfyWorkflowTemplateValidator.cs
wan22-ti2v5b-i2v-api-v1.json
```

The workflow/validator should require no semantic change beyond receiving the newly verified relative path through the existing argument.

Explicitly not owned:

```text
active C006B2B branch/files while it is in progress
C007 narration files
C008 caption/overlay files
C004 final assembly / Goal Center delivery
S002 Production HTTP lifecycle
Maotai/UI
deploy/macos/**
Natural Motion
Comfy model manifest/workflow selection
```

# TESTS

## Creative schema compatibility

- legacy IMAGE_TO_VIDEO without `existing_asset_ref` deserializes
- IMAGE_TO_VIDEO with allowlisted `existing_asset_ref` deserializes
- EXISTING_ASSET still requires the field
- GENERATIVE_VIDEO/TEXT_CARD/GENERATIVE_IMAGE/PRODUCT_ASSET_COMPOSITE reject the field
- absent field remains omitted from legacy canonical serialization

## Creative quality

- new I2V with allowlisted ID -> PASS
- new I2V without ID -> RETRY
- new I2V with invented but syntactically valid ID -> RETRY
- new I2V with cross-goal ID -> RETRY
- local Creative with empty `trusted_asset_ids` cannot pass I2V
- EXISTING_ASSET rules remain unchanged

## Web GPT / Goal return

- prompt states both EXISTING_ASSET and IMAGE_TO_VIDEO may reference the existing allowlist
- prompt contains no managed path/source path
- same existing asset allowlist/digest is reused
- valid I2V asset ref + matching digest passes
- invented ID fails
- cross-goal ID fails
- stale allowlist digest fails
- return with no asset-backed intent remains backward compatible

## Production Core

- new I2V resolves `existing_asset_ref` through TrustedAssetService
- scope_key mismatch fails closed
- wrong root/MIME/duration/canonical relpath facts fail closed
- new I2V freezes the exact shared B2B snapshot
- new I2V does not populate legacy `trusted_input_asset_ref`
- plan digest includes snapshot facts
- new compiler ignores legacy `trusted_local_assets`
- old unplanned CreativePackage with only legacy mapping remains readable but I2V becomes NeedsHuman
- already-bound legacy ProductionPlan loads unchanged
- already-bound plan is never recompiled on idempotent job replay

## Windows new I2V

- same B2B verifier is reused
- managed_root_id mismatch rejected
- canonical relpath mismatch rejected
- traversal/root escape rejected
- file/ancestor reparse rejected
- missing file rejected
- byte-size mismatch rejected
- SHA mismatch rejected
- MIME mismatch rejected
- decoded width/height mismatch rejected
- valid PNG/JPEG returns only safe managed relative path
- verification occurs after durable attempt reservation and before Comfy submit
- deterministic asset failure durably fails without consuming attempt #2
- no prompt_id exists on pre-submit asset failure

## Comfy binding

- verified relative path is inserted only into `LoadImage.image`
- I2V workflow ID unchanged
- workflow template hash unchanged
- no new model/workflow authority
- rooted/traversal input remains rejected by binder defense-in-depth

## Legacy Windows compatibility

- path-only frozen I2V plan still deserializes
- legacy ref must remain relative and under trusted input root
- reparse/traversal still rejected
- no new compiler can emit this legacy shape
- Succeeded legacy tasks remain skipped on restart
- unfinished legacy task resumes under the old frozen plan

## Package provenance

- new I2V output contains the same trusted asset provenance block as EXISTING_ASSET
- no source/absolute path is present
- fixed I2V workflow/model provenance remains present
- legacy path-only completion does not fabricate C006B1 provenance
- mixed T2V/TEXT_CARD/EXISTING_ASSET/I2V package remains one ProductionPackage

## Regression

- C006B1 asset tests
- C006B2A Creative trusted-asset tests
- accepted C006B2B tests
- C006A Production tests/smokes
- C005 timeline tests
- C004 assembly regression without C004 modification
- Windows Release build
- Ruff on touched Python

# BLOCKERS

## Implementation blocker

**C006B2B must finish and be accepted first.**

Reason:

G005 intentionally shares:

- its frozen Production trusted asset snapshot
- its Windows use-time trusted asset verifier
- its package trusted-asset provenance shape

Implementing G005 before those names/contracts land would either race the active branch or create duplicate types that must later be reconciled.

## Not a blocker

C006B1 and C006B2A are already sufficient architecture foundations for the Goal/Web-GPT identity/allowlist side.

No new:

- asset registry
- binary upload
- workflow
- model
- C004 capability
- C007 capability
- C008 capability

is required.

## Intentional v1 limitation

Local Creative source normalization currently defaults to an empty trusted-asset allowlist. Therefore fully automatic local-model I2V asset selection remains unavailable unless a trusted upstream source-set binding supplies asset IDs.

This does not block the Goal/Web-GPT I2V migration and must not be solved by filesystem discovery or invented IDs in G005.
