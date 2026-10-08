# G005 — IMAGE_TO_VIDEO Trusted Asset Migration v1

Docs-only architecture task. Do not implement code.

## Goal
Design the migration of existing IMAGE_TO_VIDEO input handling onto the C006B1/C006B2 trusted asset identity model.

Current facts to audit:
- C006B1 trusted PNG/JPEG registry + Windows managed Comfy input root
- C006B2A ShotPlan existing_asset_ref allowlist binding
- C006B2B EXISTING_ASSET execution in progress
- current Production compiler still has legacy trusted_input_asset_ref / trusted_local_assets behavior for IMAGE_TO_VIDEO
- current Windows Comfy I2V path resolves trusted input before binding workflow

## Must answer
1. What should Creative IMAGE_TO_VIDEO reference?
   - new image_asset_ref?
   - reuse existing_asset_ref?
   - one generalized trusted_input_asset_id?
   Choose the smallest backward-compatible contract.
2. How Web GPT/local Creative gets the allowlist without inventing IDs.
3. How old persisted ShotPlans/CreativePackages remain readable.
4. How Production freezes C006B1 facts into I2V task plan.
5. How Windows re-verifies root/relpath/hash/size/MIME/dimensions before Comfy LoadImage.
6. How Comfy workflow receives only the safe managed relative path it already expects.
7. How to remove/deprecate manifest trusted_local_assets/path mapping safely.
8. plan/package provenance changes
9. retry/restart/idempotency
10. cross-scope protections
11. exact migration order and compatibility period
12. whether EXISTING_ASSET and IMAGE_TO_VIDEO should share one snapshot model

## Explicit boundaries
- docs only
- do not implement C006B2B
- do not modify C007/C008/C004
- no arbitrary path authority
- no model/workflow selection expansion
- no video-file ingress

## Deliver
docs/architecture/video/G005_I2V_TRUSTED_ASSET_MIGRATION_V1.md

End with:
READY_TO_IMPLEMENT
NEXT IMPLEMENTATION SLICE
MIGRATION PLAN
FILES OWNERSHIP
TESTS
BLOCKERS
