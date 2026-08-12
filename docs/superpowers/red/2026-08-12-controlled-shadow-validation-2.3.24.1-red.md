# PicotooPet 2.3.24.1 Controlled Shadow Validation — RED Evidence

Date: 2026-08-12
PR: #28
RED feature head: `fc73b880fef78c822e0b8c42d7dea6fa02cce2c1`
Base: `4a19528868b835a8b214f0aff11e7215b31f97d3`

## Native RED run

- Workflow: `Mac Core Slice B CI`
- Run ID: `31630207406`
- Run number: `1486`
- Native job: `94226773261` — `Native macOS Core delivery (arm64)`
- Runner architecture: `arm64`
- Focused pre-existing contract suite: `74 passed`
- Full regression: `10 failed, 702 passed in 34.51s`

## Expected failures

The RED failures were limited to the new 2.3.24.1 contract surface:

1. Five shadow-domain tests failed because `picotoopet_core.deep_ai.shadow` did not exist yet.
2. Three shadow API tests failed with HTTP 404 because `/api/v1/deep-ai/shadow-runs` routes did not exist yet.
3. Schema migration test observed `16` migrations instead of target `17`.
4. Schema identity test observed no `quality_shadow_runs` / `quality_shadow_reviews` indexes because schema 17 tables did not exist yet.

No legacy regression failure was identified in the RED run.

## RED conclusion

This is the intended test-first state: 2.3.23.1 behavior remains green while the new 2.3.24.1 schema/domain/API contracts fail specifically because production implementation has not started.

The GREEN implementation must satisfy these tests without introducing local-AI, paid-AI, ComfyUI, publication, Git/GitHub execution, runtime policy mutation, or automatic promotion.