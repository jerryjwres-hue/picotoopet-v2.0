# C006B1 — Trusted Asset Ingress v1

Architecture source:
origin/design/trusted-asset-ingress-v1:docs/architecture/video/G001_TRUSTED_ASSET_INGRESS_V1.md

## Objective
Implement image-only trusted asset ingress/registry. Do NOT integrate EXISTING_ASSET into Production yet.

## Branch
feature/trusted-asset-ingress-v1
Base: C005 frozen timeline/profile contract.

## Core design
- Reuse/evolve the existing artifacts domain; do not add a second asset registry.
- Mac Core owns logical registration/provenance.
- Windows owns byte ingress into the existing trusted Comfy input root.
- User absolute source paths never cross to Core.
- v1 media: image/png and image/jpeg only.
- managed_root_id: windows.comfy-input.v1.
- canonical managed_relpath is Core-derived from SHA/media type.
- bytes stay on Windows in v1; no binary upload API.

## Mac Core
Implement:
- src/picotoopet_core/assets/__init__.py
- assets/models.py
- assets/repository.py
- assets/service.py
- api/routes/assets.py
- minimal app.py/services.py wiring
- in-place artifact-domain schema evolution in db/schema.py
- focused tests

TrustedAssetRecordV1 must include bounded identity/provenance:
schema_version, asset_id, scope_kind, scope_id, scope_key,
artifact_type/classification, managed_root_id, managed_relpath,
sha256, size_bytes, media_type, width, height, duration_ms,
source_kind, provenance, cloud_policy, created_at.

Closed scopes:
- autonomous_goal
- project
Core verifies owner existence and derives scope_key.
For autonomous_goal: scope_key = autonomous-goal:<goal_id>.

POST /api/v1/assets:
caller may send only bounded registration facts:
scope_kind, scope_id, idempotency_key, sha256, size_bytes,
media_type, width, height, duration_ms=null,
managed_root_id=windows.comfy-input.v1,
source_kind=windows_user_import.v1.

Caller MUST NOT send asset_id, absolute/source path, managed_relpath, URL,
endpoint, executable, workflow, model.

Add bounded GET by asset_id and scope-bounded list.

Idempotency:
- same key + same canonical facts => same record
- same key + changed facts => conflict
- same scope + same digest/media may dedupe
- different scopes cannot resolve each other's asset.

## Windows
New files only for this asset surface:
- TrustedAssetContracts.cs
- TrustedAssetIngressService.cs
- narrow asset REST client/session partials if required
- focused tests

Ingress flow:
explicit local source path -> read-only snapshot -> managed .partial below
Comfy input/PicotooPet/assets/v1 -> validate bytes -> SHA/size/dimensions ->
content-addressed final path -> atomic promote/reuse -> register bounded metadata with Core.

Rules:
- source must be existing ordinary non-reparse file
- MIME determined from decoded staged bytes, not extension/request
- PNG/JPEG only
- final path derived only from SHA + canonical media type
- verify exact existing object before reuse
- never overwrite conflict
- no source absolute path in request/log/persisted facts
- reuse ProductionLocalEnvironment root/reparse/hash primitives where possible
  without modifying C006A Production execution files.

## Schema
Evolve existing artifacts table in-place. Preserve old rows.
Allow non-project closed scope; do not create trusted_assets table.
source_path must remain NULL for Windows trusted assets.

## Forbidden
Do NOT modify:
- production/compiler.py
- production/models.py
- production/profile.py
- production/package.py
- ProductionExecutionService.cs
- ProductionContracts.cs
- ProductionLocalMediaRenderer.cs
- C006A tests
- C007 narration/postproduction files
- C004 final assembly/Goal Center
- S002 Production HTTP files
- Maotai/UI
- deploy/macos
- Natural Motion

Do not implement:
- existing_asset_ref
- Production EXISTING_ASSET execution
- file-picker UI
- video-file ingress
- MCP list_assets behavior changes
- cloud storage/upload

## Required tests
Core:
- owner existence/scope derivation
- unsupported scope/root/MIME rejected
- caller cannot choose managed_relpath/source path
- image duration must be null
- width/height/sha/size validation
- idempotent replay/conflict/dedupe
- cross-scope access rejected
- GET/list contain no absolute path
- old artifact rows migrate intact

Windows:
- missing/directory/reparse source rejected
- PNG/JPEG decoded from bytes
- renamed non-image rejected
- staging/final paths remain under trusted root
- ancestor reparse rejected
- content-addressed final identity
- exact object reuse
- conflict never overwritten
- hash/size recomputed after staging
- failed Core registration leaves only harmless content-addressed bytes
- network retry reuses object + idempotency key
- request contains no absolute source path

Regression:
- C001-C005 relevant tests
- asset/schema contracts
- Windows build/smokes if Windows files change
- Ruff touched Python

## Acceptance
PASS when a local PNG/JPEG can be safely imported once, registered as an immutable Core asset identity, replayed after restart/network ambiguity, and queried without any arbitrary path authority.

## Delivery requirements
- commit all C006B1 changes
- push to origin/feature/trusted-asset-ingress-v1
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
