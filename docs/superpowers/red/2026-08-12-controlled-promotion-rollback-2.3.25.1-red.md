# PicotooPet 2.3.25.1 Controlled Promotion / Rollback — RED Evidence

Date: 2026-08-12
PR: #29
RED feature head: `53cd0adbe7682683f85e54f1b3c0b25762f1d391`
Base: `a3d77a9bdfc6d413565972971ed10dcb4c34045d`

## Native RED run

- Workflow: `Mac Core Slice B CI`
- Run ID: `31649170384`
- Run number: `1544`
- Native job: `94289520466` — `Native macOS Core delivery (arm64)`
- Runner architecture: `arm64`
- Focused pre-existing contract suite: `74 passed`
- Full regression: `12 failed, 712 passed in 30.76s`

## Expected failures

The RED failures were limited to the new 2.3.25.1 surface:

1. Six Promotion-domain tests failed because `picotoopet_core.deep_ai.promotion` did not exist.
2. Four Promotion API tests failed because `/api/v1/deep-ai/promotions` routes did not exist; create/read returned HTTP 404 instead of the new bounded contract.
3. Schema migration test observed 17 migrations instead of target 18.
4. Schema identity/index test observed no Promotion tables/indexes because Migration 18 did not exist.

No legacy regression failure was identified in the RED run.

## RED conclusion

This is the intended test-first state. The 2.3.24.1 cumulative baseline remains green while 2.3.25.1 fails specifically because schema 18, Promotion governance service and authenticated Promotion APIs have not been implemented.

GREEN must satisfy these tests without introducing runtime policy consumption, prompt/model/provider/endpoint/budget/workflow mutation, local/paid model execution, ComfyUI execution, publication, Git/GitHub execution, automatic merge/tag/release, or user-machine source compilation.
