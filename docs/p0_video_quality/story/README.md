# P0-Q2 three-shot Story Bible gate and Keyframe review proposal (Issues #139, #156, #179)

**Text-only, not a visual ACCEPT.** Nothing here renders, looks at a picture, approves an image or authorizes a GPU/Comfy run. No Core `production/**`, Windows, Maotai or C011 code is touched.

## Current behavior (Creative v2)
- **Gate selection (default).** `director.story_gate_applies` picks the quality-first story gate from typed facts, never from keywords alone: an exact shot-count directive of 3, or (no directive) a Video Bible with exactly three shots. The explicit phrases (`quality-first story`, `story gate`, `keyframe kit`, `质量优先故事`, `故事门禁`, `关键帧审核`; negated forms do not select) still select it for any size. An explicit other count (for example 4) keeps the legacy gate; v1 has no Bible stage and is untouched.
- **Entry points.** `execution._run_stage` -> `CreativeQualityGate.evaluate` -> `quality._evaluate_video_bible` -> `video_bible.evaluate_video_bible(..., story_gate=True)` -> `evaluate_story_storyboard` (`story-gate-v1.0.0`): one protagonist with fixed marks/accessory/product colour, one scene and lighting, physically supported props (no "floating"), stated product contact, CONTINUOUS opening/closing handoffs, camera progression, product present through to a payoff shot that differs from the opening. Findings come back as one deterministic correction; a Bible still failing becomes `NeedsHuman` / `CREATIVE_VIDEO_BIBLE_UNRESOLVED`, no package, no queue task beyond the creative one.
- **Model-facing rules.** The rules are sent as `director_constraints.story_quality_rules` (default) or `story_gate` (explicit phrase). `execution._digest_view` removes `story_quality_rules` from the stage input digest, so a Bible stage persisted before the default existed keeps its immutable input and resumes. The explicit-phrase key stays in the digest as it always did. Template version, `video_bible.v1` schema and Bible digests are unchanged.
- **Shot Plan integrity (#156).** A v2 `shot_plan.v1` must equal `derive_shot_plan(sealed Bible, script)` field for field, at the quality gate and again when a restart reuses a `Completed` stage (`CREATIVE_COMPLETED_SHOT_PLAN_BIBLE_MISMATCH` -> `NeedsHuman`, stored row untouched).
- **Keyframe review proposal.** A gated Bible with exactly three shots adds two sidecars to `stage_results`: `keyframe_kit.v1` (three stills, all `PENDING_HUMAN_REVIEW`, references `UNTRUSTED_PROPOSAL`, shared locks) and `keyframe_review_notice.v1` (`images_exist=false`, `render_authorized=false`, plain statement that three real, human-reviewed stills of the same subject, wardrobe or accessories, product and scene, registered by Core as trusted references, must exist before any render). No image, hash, approval or `trusted_local_assets` is ever written. The unchanged compiler ignores both keys and still compiles text-to-video. `evaluate_keyframe_submissions` can at best return `AWAITING_CORE_PROVENANCE`; `send_allowed` is always false.

## Jobs that started before the default
Nothing is re-gated or rewritten. A Bible stage completed before the default is reused as stored (no model call, no story-gate re-check, same input digest); the shot plan is derived from it as before. No persisted field says whether a completed Bible was produced before or after the default, so the sidecars are added whenever the finished job's sealed Bible has exactly three shots *and itself passes* the story gate; a non-story Bible never receives them. Adding the two untrusted sidecars to such a package is the only possible difference; they authorize and block nothing. Telling the cases apart exactly would need a persisted marker (schema/Goal change), which is outside Creative ownership.

## Canonical example and skills
- `tests/creative_quality_2026/story_fixture_2026.py` is a synthetic example (white cat, teal scarf, charcoal tag, one living room with a lamp on a side table); product code and the notice are subject-neutral and a second, dog/collar story is tested.
- Skills (instructions only; not installed anywhere by this repo): `.agents/skills/picotoopet-story-director`, `picotoopet-story-keyframe-review`.

## Must be enforced by Core, impossible in Creative today
1. Image sha256 recomputed from stored bytes; decoded dimensions equal to the profile.
2. Generator identity and generation-request digest recorded outside this kit.
3. Human approval bound to `keyframe_id`, `kit_digest` and image sha256.
4. Immutable `trusted_local_assets[shot_id]` reference minted by Core; I2V feasibility explicit, no silent T2V downgrade.
5. Refusing to start a renderer for a package containing `keyframe_kit.v1` until 1-4 hold.
6. Any visual identity/physics claim (same subject, no floating prop) needs a human or calibrated visual review of real pixels; text checks cannot prove it.

## Still missing before any new Wan run
Real rendered stills of one subject/accessory/product/scene, their source rights and digests, a human verdict, and Core-minted trusted references.
