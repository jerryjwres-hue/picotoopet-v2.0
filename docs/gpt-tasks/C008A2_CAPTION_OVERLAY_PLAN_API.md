# C008A2 — CaptionOverlayPlan Read-only API

## Objective
Expose the completed C008A CaptionOverlayPlan compiler through an authenticated read-only Core API, without implementing Windows burn-in.

## Branch
feature/caption-overlay-plan-api-v1
Base: b734a4e3d50601baeda844b834557bee9f5c7b90

## Required behavior

Add a strict response contract:
- plan: CaptionOverlayPlanV1
- caption_overlay_plan_digest: sha256

Add a read-only service projection that:
1. looks up the exact Production job
2. requires a bound immutable ProductionPlan
3. loads the exact CreativePackage by job.creative_package_id through public repository APIs
4. verifies package/job identity
5. calls compile_caption_overlay_plan()
6. returns canonical digest

Add authenticated endpoint:
GET /api/v1/postproduction/production/{production_job_id}/caption-overlay-plan

Reuse the existing postproduction router.
No new DB table/lifecycle.

## Error mapping
- unknown Production job => 404 PRODUCTION_RESOURCE_NOT_FOUND
- no bound plan => 409 TEXT_PRESENTATION_NOT_READY, retryable=true
- source/timeline/profile/text-card ambiguity => bounded 422 code from CaptionOverlayPlanError
- fixed user-safe message only
- never leak authored overlay text, paths, raw package JSON, stack traces

## Files
Prefer only:
- src/picotoopet_core/postproduction/captions_overlay.py
- src/picotoopet_core/api/routes/postproduction.py
- tests/integration/api/test_caption_overlay_plan_api.py
- focused unit tests only if needed

Do not modify app.py; postproduction router is already registered.

## Forbidden
Do not modify:
- C006A/C006B asset/Production files
- C007A narration.py logic/tests
- C007B Windows TTS
- C004 final assembly
- Windows
- Goal Center
- Maotai/UI
- deploy/macos
- Natural Motion

## Tests
- auth required
- exact GET path
- valid plan returns stable digest
- unknown job => 404
- job without plan => 409 retryable
- source mismatch => bounded 422
- timeline ambiguity => bounded 422
- TEXT_CARD + authored overlay => TEXT_OVERLAY_TEXT_CARD_AMBIGUOUS
- response contains no credentials/path/renderer authority
- error never contains authored text
- no mutation/new rows
- C007A narration endpoint regression remains green
- Ruff touched files

## Acceptance
PASS when C008A is consumable as a stable authenticated Core projection while remaining Core-only and read-only.

## Delivery requirements
- commit all C008A2 changes
- push to origin/feature/caption-overlay-plan-api-v1
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
