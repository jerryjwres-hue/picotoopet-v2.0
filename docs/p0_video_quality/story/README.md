# P0-Q2 source-grounded three-shot Story Bible / Keyframe Kit (Issue #139)

Status: Mac Creative code and native tests only. **Not a visual ACCEPT.** No model, GPU, user device, Core `production/**`, Windows, C011 or attempt code was touched.

## What exists
- `creative/video_bible.py` (existing `video_bible.v1`, schema and digests unchanged):
  - `evaluate_story_storyboard(draft)`, also `evaluate_video_bible(..., story_gate=True)`: opt-in, text-only gate (`story-gate-v1.0.0`) for one protagonist with fixed marks/accessory colour, one scene and lighting, no floating wording, product contact stated, CONTINUOUS state handoffs, camera progression, product present through to the payoff shot.
  - `build_keyframe_kit(bible, script, output_profile_id=...)` -> `keyframe_kit.v1`: three PENDING_HUMAN_REVIEW stills with shared `locks` (+digest), per-still checklist, and an `UNTRUSTED_PROPOSAL` reference manifest (no path, no digest).
  - `evaluate_keyframe_submissions(kit, submissions)`: fail closed `NO_SEND` on missing/unknown/duplicate stills, differing locks, wrong aspect, no human approval, no image digest, identical images. Best case `AWAITING_CORE_PROVENANCE`; `send_allowed` is always False.
- Canonical fixture: `tests/creative_quality_2026/story_fixture_2026.py` (white cat Mochi, teal scarf, charcoal tag, one living room with lamp on side table; tag on floor -> clipped on -> cat walks past lamp). Derived `shot_plan.v1` validates and compiles with the unchanged compiler (`GENERATIVE_VIDEO`, no reference).
- Skills: `.agents/skills/picotoopet-story-director`, `picotoopet-story-keyframe-review`.

## Not wired
The story gate is not called by `quality.py` or `director.py`, so running v2 jobs behave as before. Switching it on for three-shot Goals (and adding the rules to the Story Director prompt, which bumps `VIDEO_BIBLE_TEMPLATE_VERSION`) changes live behavior and needs owner approval.

## Must be enforced by Core, impossible in Creative today
1. Image sha256 recomputed from stored bytes; decoded dimensions equal to the profile.
2. Generator identity and generation-request digest recorded outside this kit.
3. Human approval bound to `keyframe_id`, `kit_digest` and image sha256.
4. Immutable `trusted_local_assets[shot_id]` reference minted by Core; I2V feasibility explicit, no silent T2V downgrade.
5. Any visual identity/physics claim (same cat, no floating lamp) needs a human or calibrated visual review of real pixels; text checks cannot prove it.

## Live Creative v2 wiring (follow-up to the controller's 6501940432)
- Entry: `creative/execution.py::_run_stage` -> `CreativeQualityGate.evaluate` -> `quality._evaluate_video_bible` now passes `story_gate=directives.story_gate`.
- Selection: only an explicit positive phrase in the Goal objective (`quality-first story`, `story gate`, `keyframe kit`, `质量优先故事`, `故事门禁`, `关键帧审核`; negated forms do not select). Never inferred from shot count, never for v1. Without the phrase, behavior and stage input digests are unchanged.
- Selected jobs: the Story Director context gains `director_constraints.story_gate` (`STORY_GATE_RULES`); gate findings come back as one deterministic correction; a story that fails twice ends `NeedsHuman` / `CREATIVE_VIDEO_BIBLE_UNRESOLVED` with no package.
- Output: for exactly three gated shots the package gets a sidecar `stage_results["keyframe_kit.v1"]`: three `PENDING_HUMAN_REVIEW` stills and `UNTRUSTED_PROPOSAL` references. It claims no generated image, hash, approval or send permission. The compiler ignores the key (same as `video_bible.v1`).
- Core contract, not implemented here (`production/**` is not ours): to make the kit a mandatory pre-GPU review, Core must refuse to start a renderer for a package whose `stage_results` contains `keyframe_kit.v1` until it holds, per keyframe, a Core-recomputed image sha256 and a human approval bound to `keyframe_id` + `kit_digest` + that sha256, and has minted `trusted_local_assets[shot_id]` itself.
