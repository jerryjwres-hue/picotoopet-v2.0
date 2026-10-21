# P0 #91/#106 — Reference I2V authority and v1.1 migration contract

**Status:** G006 interface design / pre-authorization code; **NOT** an enabled GPU path.
**Owner boundaries:** G006 Mac Core authority, Production composition, exact Windows UI proposal. Codex #107 owns `TrustedReferenceAssetVerifier.cs` and its tests. Claude #109 owns tests/docs for proposed Video Bible. Do not silently cherry-pick either PR.

## Source-verified incompatibility and decision

At #96 baseline `160b6fc407f8315058a5038e7047dd588d9c92bf`, `ProductionTaskPlan.trusted_input_asset_ref` is a **path only**, and `ProductionPlan.schema_version="1.0"` is `extra="forbid"`. This cannot grant usage rights or validate reference bytes. `CreativePackageFinalizer` freezes four `stage_results` and a package digest; it does not register assets.

Codex #107 (`92c831000b36ae391e80526b9a304fe20cd3b516`) requires `TrustedReferenceDescriptor(ApprovalId, ShotId, AssetId, RelativePath, Sha256, ByteLength)` and a consumer-owned `ITrustedReferenceApprovalSource.IsApprovedAsync(...)`. G006 Core previously had *no AssetId*. **Freeze this mapping** in G006 `reference_assets.py`:

| Codex required value | Core authority (never inferred from path/hash) |
| --- | --- |
| `AssetId` | `ReferenceAssetIdentityV1.asset_id`: canonical UUID allocated by a **future authenticated Core registration request**, stored in the immutable approval scope; distinct from `approval_id` |
| `ApprovalId` | Existing `approvals.approval_id`, type `production.reference_asset.v1` |
| `ShotId` | Frozen `shot_plan.v1` shot ID, exactly equal to approved scope |
| `RelativePath` | Windows-staged, managed Comfy input relative path, exactly approved scope and bound to plan |
| `Sha256` | Windows-computed **actual reference-file byte SHA256**, not package manifest digest |
| `ByteLength` | Windows-computed byte length, 1..32MiB, bound with SHA |

An approved **six-field descriptor is NOT a complete authorization** by itself. `approved_reference_descriptor()` requires the real existing Core approval row and exact source/rights scope before projecting the six fields. The eventual authenticated host adapter MUST also match `goal_id, creative_job_id, creative_package_id, creative_package_digest, production_job_id, production_task_id, shot_id` against the *actual frozen* plan and Core job; the Windows verifier's Boolean `IsApprovedAsync` must fail closed if it cannot check this complete context. Never construct AssetId as `Sha256[:N]`, random Windows ID, an approval ID, or a media filename.

## Two-stage authority: avoid impossible ID ordering

**Phase A (after four Creative stages & immutable Creative Package, before Production Job creation).**
The user chooses an image for a particular `IMAGE_TO_VIDEO` shot. Windows measures bytes and stages within a fixed Comfy input root; this is a **client attestation**, not evidence that Mac read those bytes. Core checks eligible creative package and its exact `shot_plan.v1` `shot_id`, existing Goal and Creative Job lineage and source. Core creates `asset_id` UUID, stores one **Pending** resource approval using the existing `HandoffApprovalService.request_resource_in_transaction` + `approvals` table with exact immutable fields:

`asset_id, goal_id, creative_job_id, creative_package_id, creative_package_digest, shot_id, input_relative_path, sha256, bytes, source_reference, source_digest, rights_scope="wan22.i2v.production.v1"`.

**Phase B (after explicit user decision).**
The existing authenticated `/api/v1/approvals/{approval_id}/decision` with request digest, idempotency key and reason handles Approve/Reject; approval status, expiry and any later rejection/revocation must be re-read, not cached as an eternal bool. Only then may a **new** Production Job be compiled with planned `production_job_id`, `production_task_id` and `shot_id`, all checked against the frozen package and source-approved `asset_id`. The post-compile `ReferenceAssetIdentityV1` contains these production IDs but the **user's approval scope deliberately does not**: the IDs did not exist in Phase A. Bind them in the frozen `ProductionPlan v1.1`, not by modifying earlier consent scope.

This permits `CreativePackageFinalizer` and `ProductionService.create_job` to remain immutable and avoids a second asset database. However **Phase A registration API, user-consent entrypoint and Plan v1.1 producer are not yet implemented**. The read-only Core verifier is only groundwork. Any `IMAGE_TO_VIDEO` v1.0 plan still fails `I2V_REFERENCE_APPROVAL_CONTRACT_REQUIRED` before lease/POST. No reference at all → existing `GENERATIVE_VIDEO` T2V unchanged; an explicitly I2V shot with no approved asset remains NeedsHuman, never converted silently to T2V.

## Exact proposed API and lifecycle (not an existing endpoint)

Authenticated routes within existing `/api/v1` router; do not expose arbitrary paths/metadata as a user grant:

1. `POST /production/references/registrations`: payload `creative_package_id, shot_id, relative_path, sha256, byte_length, source_reference, source_digest, user_rights_attestation, idempotency_key`. Server derives Goal and Creative Job from the immutable package, issues `asset_id`, checks that this is an I2V shot and the asset context is bounded, persists *Pending* resource approval. Response: `asset_id, approval_id, approval_request_digest, pending`. Repeated same key returns same pending identity; changed bytes/context must conflict, not mutate an already approved record.
2. Existing `GET /approvals` and `POST /approvals/{approval_id}/decision` remain the **only** human decision authority; no new approval-token shortcut. Do not auto-approve an image because the chooser selected it.
3. `GET /production/jobs/{production_job_id}/plan`: existing v1.0 response unchanged for old jobs. Only newly created v1.1 jobs may return discriminated `ProductionPlanV11` (`schema_version="1.1"`) with exactly one per-I2V-task `reference_asset` describing `asset_id, approval_id, approval_request_digest, sha256, byte_length, relative_path, source_digest, goal_id, creative_job_id, creative_package_id, shot_id, production_task_id`. Persist *canonical entire* plan JSON and SHA before first lease. A read-only approval-check route must return a **full authenticated** context-bound decision, never an unbound `approved=true`.
4. Existing worker first reconciles Pending Journal/unknown POST. For **new** I2V: fetch exact immutable Core plan/job and current Core approval; compare full identity, call Codex `TrustedReferenceAssetVerifier.VerifyAsync` using `ProductionLocalEnvironment` delegates, hold `VerifiedReferenceAsset` through Comfy's terminal history (not only POST acknowledgement), then commit. Verify again after restart **before any new POST**. If history/queue reconciliation is uncertain, block new GPU; no second scheduler.

**v1.1 migration gate:** separate typed Core `ProductionPlanV11` plus C# `ProductionPlanV11Record` discriminated by `schema_version`, rather than unknown optional fields in v1.0 models. Version-aware repository load/claim and API response; old v1.0 plan digests, persisted `plan_json`, saved `task_plan_json`, journals, succeeded receipts, lease/attempt ceiling and restart behavior must remain byte-identical. No in-place upgrades; no auto rewriting existing frozen plans. Once present, v1.1 must be covered by canonical JSON SHA and the same lease/journal authority. New API/plan wire-up requires explicit product approval and independently tested migration before G006 enables GPU.

## Minimal Windows GUI UX — proposal only; **no UI semantics changed yet**

Existing Goal Center provides Goal/Creative continuation and existing Approvals screen performs digest-bound decisions. Add a **Reference Image** action only when a `creative_ready` Package has an I2V shot, with a controlled file picker (PNG/JPEG/WebP, fixed size/length bounds). Display actual preview, originating local filename for the chooser *locally*, SHA prefix, file byte length, the exact Goal, Creative Package/Shot, intended Wan I2V usage, rights/source choice and explicit `I have rights to use this specific image for this shot` checkbox. No rights default. The operator must confirm a dedicated submission. Core then creates Pending; an *independent* Approvals-page Approve/Reject action presents a **specific**, visible, nonsecret asset ID / image hash prefix / Goal / Shot / use scope, plus reason and digest. Existing current approval summary is a fixed whitelist and does **not** display these fields yet: extending the whitelist/UI is a prerequisite before the feature can be user-facing. A generic Approve with hidden scope **must not count**.

The file must remain content-addressed/immutable and local under the Comfy input managed root for queued LoadImage across process crash. A process-held file handle from Codex does NOT guarantee survival after reboot, filesystem replacement or queuing. Require durable staging ACL/write-denial and startup SHA/approval revalidation of queued and journaled graphs before turning on I2V. A full directory permissions/staging implementation is **not included** in this checkpoint.

## Claude #109 Video Bible runtime reality and safe insertion point

PR #109 is tests/docs only. Current Mac Core `CreativeStageKind`, `creative.content_plan.v1` in `creative/profiles.py`, `CreativeIntelligenceCoordinator._JOB_STATUS`, `_stage_context`, `CreativeQualityGate.evaluate`, `CreativeIntelligenceService.adopt_external` and repository stages are a fixed **four-stage** sequence:

`idea_ranking.v1 → creative_brief.v1 → script.v1 → shot_plan.v1`.

`CreativePackageFinalizer` can mechanically serialize extra `stage_results` keys, and compiler ignores them, but **Mac Ollama will never generate a fifth Bible stage just because a JSON key is appended**. Also external adoption strictly checks stage list, so silently appending `stage_results["video_bible.v1"]` breaks the frozen API. The legitimate runtime entrypoint is `CreativeStageDefinition` and `CreativeIntelligenceCoordinator.adapter.run(profile, context, correction)`; v2 would require explicit new stage kind, prompt schema/template, status/transition, context passed to SHOT_PLAN, quality lint, independent stage recovery, and external-adoption compatibility. Keep v1 jobs on the four-stage path and existing continuity-notes → Wan Prompt v1.1.0. Do not import #109's reference model directly into production or conflate text lint with visual quality.

## Independent T2V shipping track

P0 T2V goal → four-stage Mac Ollama → Production Plan → Windows same EXE Wan Comfy POST/Journal → WebM verified SHA/receipt → existing C004/C009 → C010A/C011 technical QA-gated MP4 remains **independent** of I2V. No GPU invoked during this contract work. Prior 3-shot tests are synthetic; genuine 3+ `prompt_id`, playably verified individual WebMs, C011 QA receipt, MP4 SHA and human visual checks remain **UNVERIFIED** unless separately supplied from a physically authorized device. Maintain the explicit electrical safety hard stop for user Windows; no GUI/Worker launch or GPU POST until hardware clearance and authorization.
