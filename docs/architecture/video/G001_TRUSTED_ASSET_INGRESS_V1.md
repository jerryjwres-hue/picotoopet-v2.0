# G001 — Trusted Asset Ingress v1 Architecture

Status: architecture complete; docs-only  
Branch: design/trusted-asset-ingress-v1  
Baseline: feature/video-timeline-output-profiles at e82df96a7acddfb7cc2b26c023517b58716b226b

## 1. Objective

Design the smallest safe trusted-asset ingress that can later unlock C006B EXISTING_ASSET and also replace the current ad-hoc trusted_local_assets gap for IMAGE_TO_VIDEO, without creating another Creative pipeline, Production pipeline, asset registry, or arbitrary path authority.

This task does not implement code. It defines the authoritative asset identity, Windows byte-ingress boundary, Mac Core registry, Creative/Production binding, restart semantics, security controls, APIs, future file ownership, tests, and the minimal implementation slices.

The architectural decision is:

> Mac Core owns the immutable asset registration and scope binding. Windows owns the physical imported byte copy under one closed managed input root. User-selected absolute paths never cross the Windows boundary. Production receives a Core-frozen asset identity plus expected content facts; it never receives a user/GPT path.

For v1, the physical managed root is the existing ComfyUI input root already trusted by ProductionExecutionService. Imported media is copied beneath a PicotooPet-owned content-addressed subdirectory of that root.

No media-byte upload to Mac Core is required in v1.

---

## 2. Repository audit — facts that already exist

### 2.1 Mac Core PathPolicy

src/picotoopet_core/permissions/path_policy.py already provides managed/protected root checks and resolves paths before authorization. Its tests cover traversal and symlink escape.

This policy is Mac-filesystem policy. It cannot safely authorize or resolve a Windows absolute path and must not be used as a reason to send Windows source paths to Core.

### 2.2 Existing artifact domain is a dormant registry scaffold

MIGRATION_001 already creates an artifacts table with:

- artifact_id
- project_id
- artifact_type
- classification
- source_path
- stored_object_hash
- media_type
- size_bytes
- sha256
- is_original
- cloud_policy
- created_at

ArtifactContract already exists in src/picotoopet_core/domain/contracts.py and is exported to contracts/schemas/artifact_v2.schema.json.

However repository search found no INSERT INTO artifacts, no ArtifactRepository/ArtifactService, and no REST asset routes. The table is therefore schema/domain scaffolding, not a functioning asset system.

G001 must activate/evolve this existing artifact domain rather than create an unrelated trusted_assets registry.

### 2.3 The existing artifacts schema cannot represent Goal video ownership as-is

artifacts.project_id is currently NOT NULL and references projects(project_id).

The autonomous Goal model has no project_id. Goal video return creates Creative source identity using:

- project_key = autonomous-goal:<goal_id>

Creative and Production propagate project_key, not a projects.project_id foreign key.

Therefore the existing artifacts table cannot be used unchanged for Goal video assets. A minimal in-place schema evolution is required so the existing artifact domain can bind assets to a closed owner scope other than Project.

This is not justification for a second asset table.

### 2.4 MCP list_assets is a registry stub only

list_assets is present in the frozen MCP tool registry and tools_v1 contract as a read operation.

McpToolExecutor has no list_assets implementation. It falls through to CAPABILITY_UNAVAILABLE.

Therefore:

- list_assets cannot currently import/register/list real assets.
- it may later reuse the new ArtifactRepository for project-scoped read-only listing.
- it must not become the ingress transport.
- its current frozen project_id input contract cannot represent autonomous-goal scope without a separate future MCP contract decision.

G001 does not change MCP.

### 2.5 Creative ShotPlan does not currently contain existing_asset_ref

Current ShotPlanItem contains:

- shot_id
- beat_id
- order
- duration_seconds
- subject/environment/action
- framing/lighting_style
- continuity_keys
- required_facts/source_evidence_ids
- text_reference
- production_notes
- render_intent

There is no existing_asset_ref field.

Therefore any implementation that assumes Creative already carries an asset ID is incorrect.

A future C006B2 integration must add a bounded logical reference. That reference must be an asset_id, never a path.

### 2.6 C005 is present on this branch

The design branch is one docs commit ahead of feature/video-timeline-output-profiles at e82df96....

The Production compiler now consumes:

- CreativeBriefResult.output_profile_id
- ShotPlanItem.duration_seconds
- ProductionPlan.output_profile_id
- ProductionPlan.target_runtime_ms
- ProductionTaskPlan.target_duration_ms

C006B can therefore normalize an existing asset against a frozen output profile/timeline rather than inventing timing.

### 2.7 Production already has a trusted Windows input root

ProductionExecutionService preflight resolves:

- Comfy data root
- input root = <Comfy data root>/input
- output root = <Comfy data root>/output

It validates the data/input/output roots with ProductionLocalEnvironment.AssertNoLinkEscape.

For I2V, ValidateTrustedInput takes only a relative reference, resolves it under inputRoot, checks existence and reparse/symlink escape, and returns a normalized relative path to the Comfy workflow.

This is the strongest existing evidence for where v1 trusted asset bytes should live.

### 2.8 Current Production has an unfinished trusted asset hook

production/compiler.py contains _trusted_asset_ref(), which reads:

- Creative Package manifest["trusted_local_assets"][shot_id]

and places the resulting string into ProductionTaskPlan.trusted_input_asset_ref.

No producer for trusted_local_assets exists in the audited repository.

Therefore the current hook is a consumer-side placeholder, not a complete trusted asset system.

G001 replaces the missing producer concept with a real Core asset registry and a future compiler resolution by asset_id.

### 2.9 Existing Mac ResultStore is content-addressed but is not the right byte location for v1

ResultStore already provides:

- SHA-256 content addressing
- objects/<hash-prefix>/<hash-rest>
- atomic temporary writes
- integrity verification
- immutable object semantics

It also has put_file(), but that method resolves a path on the Mac host. Exposing it to Windows would create exactly the forbidden arbitrary cross-machine path authority.

MacCoreClient currently has bounded binary download support for Goal handoff ZIPs, but repository search found no general binary upload path.

Using ResultStore for user media in v1 would require:

Windows source -> upload to Mac -> Mac object store -> download back to Windows -> Production

That adds a new binary upload/download surface and duplicates large media even though C006 executes on Windows.

Therefore G001 reuses ResultStore's design principles, not its physical byte store.

---

## 3. Trusted asset identity

### 3.1 Logical identity

The authoritative logical identity is:

- asset_id

asset_id maps directly to the existing artifacts.artifact_id domain. No second ID namespace is created.

asset_id is Core-issued and opaque to Creative/Windows callers.

The content identity is:

- sha256

asset_id answers "which registered asset in this scope?"  
sha256 answers "which exact bytes?"

Both are required.

### 3.2 Required immutable record

TrustedAssetRecordV1 must contain:

- schema_version = 1.0
- asset_id
- scope_kind
- scope_id
- scope_key
- artifact_type
- classification
- managed_root_id
- managed_relpath
- sha256
- size_bytes
- media_type
- width
- height
- duration_ms
- source_kind
- provenance
- cloud_policy
- created_at

For image-only C006B1:

- media_type is image/png or image/jpeg
- width and height are required
- duration_ms is null

For a future video extension:

- width and height are required
- duration_ms is required and positive

### 3.3 Closed scope

v1 supports closed owner kinds:

- autonomous_goal
- project

Core derives scope_key, callers do not invent it.

For autonomous_goal:

- scope_id = existing goal_id
- scope_key = autonomous-goal:<goal_id>

For project:

- scope_id = existing project_id
- scope_key is a Core-derived project scope key defined by the project integration.

The immediate C006B path uses autonomous_goal because that exactly matches the project_key produced by Goal video return.

Core must verify the referenced Goal/Project exists before registration.

### 3.4 Physical location is not identity

managed_root_id v1:

- windows.comfy-input.v1

managed_relpath is deterministic and Core-derived from sha256 plus canonical media type, for example:

- PicotooPet/assets/v1/ab/<64-char-sha>.png
- PicotooPet/assets/v1/ab/<64-char-sha>.jpg

The request must not be allowed to choose managed_relpath.

No API or Creative contract contains the user's original absolute path.

---

## 4. Who imports/registers the asset

### Windows owns byte ingress

Only Windows sees the user-selected source path.

Responsibilities:

1. Receive a path from an explicit local caller/file-picker boundary.
2. Treat the source as untrusted.
3. Open it read-only.
4. Snapshot bytes into a .partial file below the trusted Comfy input root.
5. Validate media type and dimensions from the staged bytes.
6. Compute SHA-256 and size from the staged bytes.
7. Derive the canonical content-addressed relative destination.
8. Atomically install or safely reuse the managed object.
9. Register immutable facts with Mac Core.
10. Never send the source absolute path to Core.

### Mac Core owns registration authority

Core responsibilities:

1. Verify owner scope exists.
2. Verify closed media/profile constraints.
3. Recompute the expected managed_relpath from sha256 + media type.
4. Issue/reuse asset_id.
5. Persist the immutable registration in the existing artifact domain.
6. Enforce idempotency/conflict rules.
7. List/resolve assets by logical identity.
8. Later resolve existing_asset_ref during Production compilation.

Mac Core does not open or resolve the Windows managed path.

---

## 5. Byte ingress flow

User-selected Windows file

    |
    | absolute path exists only inside Windows process
    v

TrustedAssetIngressService

    |
    | read-only snapshot
    v

<Comfy input>/PicotooPet/assets/v1/.staging/<random>.partial

    |
    | validate staged bytes
    | sha256 + size + image dimensions
    v

derive canonical path from digest

    |
    v

<Comfy input>/PicotooPet/assets/v1/<prefix>/<sha>.<canonical-ext>

    |
    | atomic move; never overwrite conflicting bytes
    v

POST bounded metadata to Mac Core

    |
    v

existing Artifact domain / Core registry

    |
    v

TrustedAssetRecordV1(asset_id, digest, managed relative identity, provenance)

Media bytes do not cross to Mac Core in v1.

---

## 6. v1 media scope

### C006B1 should be image-only

The repository currently has no ffprobe integration and no general media-probe service.

Image ingress can be implemented without a new external executable by decoding staged PNG/JPEG bytes using the existing Windows/.NET desktop runtime, while the later C006B2 renderer can hold the image for the C005 target duration and encode a normalized WebM.

Therefore the smallest implementable C006B1 accepts:

- image/png
- image/jpeg

It rejects all other media types.

This also gives the existing IMAGE_TO_VIDEO path a real trusted image source.

Video-file ingress should be a later extension after a closed duration/stream probe is selected and tested. It must not infer duration from filename/container metadata supplied by the caller.

---

## 7. Existing asset binding in Creative

### 7.1 Future ShotPlan contract

C006B2 should add:

- existing_asset_ref: asset_id | null

This field is a logical Core identity only.

Rules:

- EXISTING_ASSET requires existing_asset_ref.
- The referenced asset must exist.
- asset.scope_key must equal the Creative Package project_key.
- asset media type must be supported by the selected execution profile.
- arbitrary UUIDs that do not resolve in the current scope are rejected.
- no managed_relpath is accepted from Creative/GPT.

IMAGE_TO_VIDEO should migrate to the same asset_id mechanism when practical, while preserving compatibility for already-persisted packages during the transition.

### 7.2 AI allowlist requirement

A model/Web GPT must not be allowed to invent a trusted asset ID.

If Creative generation is expected to select an asset, the Core-provided Creative context/handoff must contain an explicit allowlist of eligible opaque asset IDs plus only safe bounded metadata.

Return/adoption validation must reject any existing_asset_ref outside that allowlist.

This is an integration dependency, not part of C006B1 byte ingress.

---

## 8. Production compiler resolution

C006B2 must resolve asset IDs inside Mac Core.

Recommended flow:

1. ProductionService reads the validated Creative Package.
2. For every shot with existing_asset_ref, Core loads the TrustedAssetRecordV1.
3. Core verifies scope_key == Creative Package project_key.
4. Core verifies supported media type and required immutable facts.
5. Core passes a frozen trusted-asset projection into the deterministic compiler.
6. ProductionTaskPlan freezes:
   - trusted_asset_id
   - trusted_input_asset_ref
   - trusted_input_sha256
   - trusted_input_bytes
   - trusted_input_media_type
7. Windows receives only those Core-frozen facts.

The compiler must not query arbitrary filesystem state.

The current manifest["trusted_local_assets"][shot_id] string hook should not remain the long-term source of authority. It may only be retained as a backward-compatibility path for old packages if required.

---

## 9. Windows C006B2 normalization

For an image EXISTING_ASSET task:

1. Resolve inputRoot from the same Production local environment already used by I2V.
2. Resolve trusted_input_asset_ref under inputRoot.
3. Reject root escape/reparse/non-ordinary file.
4. Verify bytes == trusted_input_bytes.
5. Recompute SHA-256 and compare with trusted_input_sha256.
6. Decode and verify actual media type/dimensions.
7. Normalize deterministically to the C005-frozen width/height/fps/frame_count/target_duration_ms.
8. Output video/webm under the existing Production output root.
9. Commit through the existing Production attempt/result/package lifecycle.
10. C004 consumes the normalized WebM unchanged.

No second Production task/package/store is introduced.

---

## 10. Existing artifacts domain evolution

The existing artifacts table must be evolved in-place rather than bypassed.

The migration should preserve any existing rows, although repository audit found no runtime writer.

Required schema evolution conceptually includes:

- project_id becomes nullable for non-Project scopes
- scope_kind
- scope_id
- scope_key
- managed_root_id
- managed_relpath
- width
- height
- duration_ms
- source_kind
- provenance_json
- idempotency_key or equivalent immutable idempotency binding

Existing fields remain useful:

- artifact_id
- artifact_type
- classification
- media_type
- size_bytes
- sha256
- is_original
- cloud_policy
- created_at

For trusted Windows assets:

- source_path must be NULL
- stored_object_hash may remain NULL because the bytes are not in Mac ResultStore
- is_original = true
- cloud_policy = local_only

Do not overload source_path with a Windows absolute path or a managed relative path.

---

## 11. Registration API

### POST /api/v1/assets

Request: TrustedAssetRegisterRequestV1

Fields:

- schema_version = 1.0
- scope_kind = autonomous_goal | project
- scope_id
- idempotency_key
- sha256
- size_bytes
- media_type
- width
- height
- duration_ms
- managed_root_id = windows.comfy-input.v1
- source_kind = windows_user_import.v1

Not allowed:

- asset_id
- source_path
- absolute_path
- managed_relpath
- URL
- executable
- endpoint
- workflow
- model

Core derives:

- scope_key
- asset_id
- managed_relpath
- classification/cloud policy defaults
- created_at

Response:

- TrustedAssetRecordV1

### GET /api/v1/assets/{asset_id}

Returns one bounded TrustedAssetRecordV1.

No absolute path.

### GET /api/v1/assets

Closed query:

- scope_kind
- scope_id
- bounded limit

Returns only assets registered in that scope.

No filesystem discovery is performed.

### No upload endpoint in v1

There is intentionally no binary POST/PUT endpoint.

---

## 12. Idempotency, restart, replay, and conflict semantics

### 12.1 Windows local import

The installed object path is content-addressed.

If destination does not exist:

- write .partial under the managed root
- flush/close
- verify staged bytes
- atomically move to final path

If destination already exists:

- verify it is ordinary, inside the managed root, expected size, and expected SHA
- exact match -> reuse
- mismatch -> TRUSTED_ASSET_LOCAL_CONFLICT
- never overwrite a conflicting object

### 12.2 Crash after local install but before Core registration

Retrying the same import:

- reuses the content-addressed local object after verification
- replays the same registration idempotency key
- produces/reuses the same Core asset registration

The orphan local object is harmless because a file's existence is not authority. Only the Core registry makes it selectable.

### 12.3 Core registration idempotency

Same idempotency_key + identical canonical request:

- return existing record

Same idempotency_key + different facts:

- TRUSTED_ASSET_IDEMPOTENCY_CONFLICT

Same scope + same SHA/media type registered again with a different idempotency key:

- Core may return the existing asset record rather than create duplicate logical registrations

The first created_at remains authoritative.

### 12.4 Core registration survives Windows restart

Asset registry remains in Core.

Windows byte availability is checked again at Production execution time.

If the local object was deleted/corrupted:

- fail closed with bounded missing/hash failure
- do not silently resolve another path
- require re-import/restoration

Cross-device replication is not part of v1.

---

## 13. Symlink, reparse, traversal, and TOCTOU controls

### User source path

The user-selected source path is ingress-only and never trusted.

Requirements:

- must resolve to an existing ordinary file
- selected file itself must not be a reparse point
- source path is never sent to Core
- source filename does not determine final destination
- source extension alone does not determine trusted media type

The service snapshots bytes; later source mutation does not change the managed object.

### Managed destination

Reuse existing ProductionLocalEnvironment primitives:

- ResolveUnderRoot
- AssertNoLinkEscape
- IsOrdinaryFile
- Sha256FileAsync

Before staging/final write:

- root must be the resolved Comfy input root
- PicotooPet asset directory ancestry must not contain reparse points
- generated relative names only
- no caller filename in destination
- no .., rooted path, colon, or alternate root

### TOCTOU

Validation occurs on the staged managed snapshot, not on the original user path.

After closing the staged write:

- verify length
- hash staged file
- decode staged file
- derive final name from verified hash/media type
- atomic move

At Production use time, C006B2 repeats ordinary-file/root/hash/size checks.

Registration alone never substitutes for use-time file verification.

---

## 14. MIME and metadata validation

C006B1 image-only policy:

Allowed:

- image/png
- image/jpeg

Media type must be determined from the staged bytes/decoder, not trusted from request or file extension.

The Windows ingress service supplies width/height measured from the staged bytes.

Core validates:

- positive width/height
- closed allowed MIME
- duration_ms must be null for image
- bounded size
- lowercase 64-char SHA-256
- managed_root_id exact allowlist value

The exact byte/pixel safety constants should be source-controlled implementation constants and covered by boundary tests. They are not caller-configurable.

---

## 15. Provenance

Minimal provenance must be non-path and privacy-preserving.

TrustedAssetRecordV1 provenance should include:

- source_kind = windows_user_import.v1
- registration actor = authenticated Windows client
- registration/idempotency identity
- scope identity
- content digest
- optional bounded original display filename only if product explicitly needs it later

Do not persist the original absolute path.

Current require_auth authenticates a shared device token and returns authenticated-device; it does not prove a distinct physical device identity. G001 must not claim stronger per-device provenance than the repository currently provides.

A future pairing-specific auth enhancement may add a stable device identity without changing asset_id semantics.

---

## 16. MCP list_assets decision

Current status:

- registry contract exists
- permission is read
- executor implementation does not exist
- result today is CAPABILITY_UNAVAILABLE

Decision:

- Do not use MCP list_assets for ingress.
- Do not change its frozen contract in C006B1.
- After the registry exists, it may be wired to list project-scoped artifacts through the same ArtifactRepository.
- Autonomous Goal asset listing remains REST/service-driven until a separate MCP contract explicitly supports Goal scope.

Therefore list_assets is reusable only as a future read adapter, not as the trusted ingress architecture.

---

## 17. Why bytes stay on Windows in v1

This is a deliberate local-first decision, not an omission.

Existing repository facts:

- Production executes on Windows.
- I2V already reads Comfy input relative paths.
- ProductionLocalEnvironment already enforces the Windows root boundary.
- Mac ResultStore can store bytes but lives on Mac.
- MacCoreClient has bounded downloads but no general upload boundary.

Keeping the canonical local execution copy on Windows:

- avoids Windows -> Mac -> Windows transfer
- avoids a new large binary upload API
- avoids exposing Mac paths
- immediately serves I2V and C006B
- keeps Core as metadata/provenance authority
- preserves local-first behavior

The tradeoff is that v1 does not replicate asset bytes across Windows machines. Missing local bytes fail closed and require re-import.

---

## 18. Exact module ownership

### C006B1 — Trusted Asset Ingress / Registry

Mac Core ownership:

- src/picotoopet_core/assets/__init__.py — new
- src/picotoopet_core/assets/models.py — new
- src/picotoopet_core/assets/repository.py — new
- src/picotoopet_core/assets/service.py — new
- src/picotoopet_core/api/routes/assets.py — new
- src/picotoopet_core/api/app.py — register assets router
- src/picotoopet_core/services.py — wire Artifact/Asset service
- src/picotoopet_core/db/schema.py — in-place artifact-domain migration
- src/picotoopet_core/domain/contracts.py — only if the shared ArtifactContract is evolved rather than keeping TrustedAssetRecordV1 in assets/models.py
- related contract/unit/integration tests

Windows ownership:

- windows/desktop/src/PicotooPet.Desktop.Core/Contracts/TrustedAssetContracts.cs — new
- windows/desktop/src/PicotooPet.Desktop/Services/TrustedAssetIngressService.cs — new
- Windows asset REST client surface using the existing authenticated Mac Core connection pattern
- focused ingress/security tests

C006B1 must not implement UI/file-picker presentation. The service receives a path only from an explicit local caller boundary.

### C006B2 — EXISTING_ASSET Production integration

Only after C006A ownership is released:

- src/picotoopet_core/creative/models.py
- Creative validation/adoption paths needed to validate existing_asset_ref allowlists
- src/picotoopet_core/production/compiler.py
- src/picotoopet_core/production/models.py
- src/picotoopet_core/production/quality.py
- src/picotoopet_core/production/package.py
- windows/desktop/src/PicotooPet.Desktop.Core/Contracts/ProductionContracts.cs
- windows/desktop/src/PicotooPet.Desktop/Services/ProductionExecutionService.cs or a new local-media adapter owned by C006
- C006B2 tests

C006B2 must consume the C005 timeline and emit normalized video/webm through the existing Production package lifecycle.

---

## 19. Explicitly forbidden files / modules

G001 docs task itself modifies only:

- docs/architecture/video/G001_TRUSTED_ASSET_INGRESS_V1.md

Future C006B implementation must not modify while other owners hold them:

S002:

- windows/desktop/src/PicotooPet.Desktop/Services/ControlCenterSession.Production.cs
- windows/desktop/src/PicotooPet.Desktop.Core/Networking/MacCoreClient.Production.cs
- windows/desktop/src/PicotooPet.Desktop/Services/ProductionClientHolder.cs
- S002 tests

C004:

- windows/desktop/src/PicotooPet.Desktop/Services/FinalVideoAssemblyService.cs
- windows/desktop/src/PicotooPet.Desktop/Services/GoalFinalVideoCoordinator.cs
- windows/desktop/src/PicotooPet.Desktop/Services/ControlCenterSession.FinalVideo.cs
- Goal Center delivery implementation
- C004 tests

C006A while active:

- C006A TEXT_CARD-owned Production compiler/model/executor files
- C006A tests

C007A:

- postproduction/narration modules
- Narration contracts/client/service/tests

Always excluded:

- Maotai/UI visual line
- deploy/macos/**
- Natural Motion gate
- Comfy workflow/model authority unless a separate task explicitly owns it

G001 does not require:

- new Comfy workflow
- new model
- new endpoint authority from Creative
- C004 assembler changes
- publishing
- cloud storage

---

## 20. Tests

### Mac Core registry

- autonomous_goal registration requires an existing goal
- project registration requires an existing project
- unknown scope rejected
- Core derives scope_key
- caller cannot supply managed_relpath
- caller cannot supply source_path/absolute path
- unsupported managed_root_id rejected
- invalid SHA rejected
- unsupported MIME rejected
- image duration_ms non-null rejected
- invalid width/height rejected
- idempotent replay returns same asset
- idempotency conflict rejected
- same scope + same digest dedupes safely
- different scopes cannot resolve each other's asset
- GET by asset_id returns no absolute path
- list is scope-bounded
- old artifact rows migrate without loss

### Windows ingress

- source absolute path is never included in registration request
- missing source rejected
- directory source rejected
- source reparse file rejected
- PNG detected/decoded from bytes
- JPEG detected/decoded from bytes
- renamed non-image rejected despite extension
- staging path remains under Comfy input root
- staging/final ancestor reparse escape rejected
- final path derived from SHA/media type only
- exact existing object reused after hash verification
- conflicting existing object is never overwritten
- staged hash/size are recomputed after write
- failed registration leaves only a safe content-addressed local object
- retry after network failure reuses object and idempotency key

### Creative/Production integration tests for C006B2

- EXISTING_ASSET requires existing_asset_ref
- unknown asset ID -> NeedsHuman/fail closed according to final C006 contract
- cross-scope asset ID rejected
- Core freezes asset ID/hash/bytes/MIME/relative ref into Production plan
- Windows revalidates file before use
- hash mismatch fails closed
- missing local file fails closed
- normalized output exactly matches C005 width/height/fps/frame_count
- output is video/webm
- existing Production attempts/restart/package semantics are reused
- C004 consumes a mixed generated/existing-asset ProductionPackage without modification

### MCP regression

- frozen list_assets tool name/schema remains unchanged in C006B1
- until explicitly wired, no fake asset results are returned
- if later wired for Project scope, it delegates to the same ArtifactRepository rather than a second store

---

## 21. Acceptance criteria

G001 architecture is satisfied by implementation only when:

1. Core is the sole authority for registered asset identity and scope.
2. User/GPT absolute paths never enter Core contracts, Creative Package, Production Plan, or manifests.
3. Windows copies selected bytes into one closed managed root before registration.
4. The managed path is content-derived, not caller-derived.
5. Core reuses the existing artifact domain instead of creating a parallel registry.
6. Goal video assets can bind to autonomous-goal:<goal_id> despite the legacy project_id-only schema.
7. Image bytes are validated from staged content and immutable facts are recorded.
8. Restart/replay is idempotent and conflicts fail closed.
9. Production use revalidates hash/size/path instead of trusting registration alone.
10. ShotPlan future existing_asset_ref means asset_id only.
11. Production compiler resolves asset_id to a Core-owned frozen projection.
12. C006B outputs remain normal Production tasks/package outputs.
13. C004 is unchanged.
14. S002 is unchanged.
15. No binary Windows-to-Mac asset upload is added in v1.

---

## 22. Minimal implementation slices

### C006B1 — Trusted Asset Ingress v1

Implement only:

- evolve/activate existing artifacts domain
- TrustedAssetRecordV1 / registration contract
- Core repository/service/REST
- Windows image-only managed import service
- content-addressed copy under Comfy input root
- PNG/JPEG metadata validation
- hash/size/provenance/idempotency
- read/list asset APIs
- tests

Do not touch Creative/Production/C004.

This slice is independently testable and removes the main G001 blocker found during V002.

### C006B2 — EXISTING_ASSET execution

After C006A Production ownership is free:

- add existing_asset_ref asset_id to the correct Creative contract
- enforce Core asset allowlist/scope validation
- resolve asset through ArtifactRepository at Production compile time
- freeze expected asset facts into ProductionTaskPlan
- add local-media EXISTING_ASSET execution
- normalize image to C005 timeline-compatible WebM
- commit through existing Production lifecycle
- prove C004 compatibility

### Later extension — video existing assets

Only after a closed local video probe is selected:

- allowlisted video MIME
- verified duration/streams/dimensions
- deterministic trim policy
- no source audio in initial normalization unless separately specified

This is not required for C006B1.

---

## 23. Blockers and dependencies

### C006B1

No unresolved architecture blocker remains.

Implementation prerequisite:

- work from the current C005-frozen baseline or a later integrated baseline that preserves the audited contracts.

The artifacts schema migration is required, not optional, because Goal assets cannot satisfy the current NOT NULL project_id foreign key.

No TTS/C007 dependency exists.

No C004/S002 dependency exists if their owned files are avoided.

### C006B2

Dependencies:

- C006B1 registry/import complete
- C006A TEXT_CARD ownership of Production compiler/models/executor released
- final C006 execution_backend/profile contract known
- Creative asset-selection allowlist integration decided for the exact product entry path

The last item does not block C006B1.

---

# READY_TO_IMPLEMENT: YES

C006B1 Trusted Asset Ingress v1 is architecturally ready to implement as an image-only, Windows-local byte ingress plus Mac Core artifact registry.

The implementation must use the existing artifacts domain and existing Comfy input trusted root. It must not add a binary upload API or a second asset registry.

# NEXT IMPLEMENTATION SLICE

C006B1 — Trusted Asset Ingress v1

Deliver:

- in-place artifacts-domain migration for Goal/project scopes
- TrustedAssetRecordV1 and register/get/list REST contracts
- ArtifactRepository/TrustedAssetService
- Windows TrustedAssetIngressService
- content-addressed PNG/JPEG import into Comfy input/PicotooPet/assets/v1
- idempotency/restart/conflict/path-security tests

Do not yet modify ShotPlan, Production compiler, Production executor, or C004.

# BLOCKERS

C006B1: none after choosing the architecture above.

C006B2 end-to-end EXISTING_ASSET still waits for:

1. C006B1 implementation.
2. C006A release of shared Production compiler/models/executor ownership.
3. A Core-provided Creative asset allowlist/binding path so existing_asset_ref cannot be model-invented.
4. Video-file asset support remains deferred until a closed duration/stream probe is selected; image EXISTING_ASSET is not blocked by this.

# FILES OWNERSHIP

G001 docs-only branch owns only:

- docs/architecture/video/G001_TRUSTED_ASSET_INGRESS_V1.md

Recommended C006B1 implementation ownership:

Mac Core:
- src/picotoopet_core/assets/**
- src/picotoopet_core/api/routes/assets.py
- src/picotoopet_core/api/app.py
- src/picotoopet_core/services.py
- src/picotoopet_core/db/schema.py
- narrowly scoped artifact contract/schema tests

Windows:
- new TrustedAsset contracts/client/service files
- dedicated Trusted Asset ingress tests

Explicitly not owned:
- C006A Production files while C006A is active
- S002 networking/session files
- C004 final assembly/delivery files
- C007 narration files
- Goal Center/Maotai/UI
- deploy/macos/**
- Natural Motion gate
