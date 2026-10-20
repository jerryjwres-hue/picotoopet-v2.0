---
name: picotoopet-visual-critic
description: Review real decoded AI video frames bound to an exact output_sha256 and report concrete defects. Without real frames the answer is VISUAL_QA=UNVERIFIED.
---
# PicotooPet Visual Critic — revision 2 (requires real frames)

Criteria ids follow the PR #105 rubric (`quality_rubric.v1.json`: S01–S07 shot, V01–V06 video); verdicts are exactly `ACCEPT`, `REVIEW`, `REGENERATE`, `BLOCKED`.

## Hard gate
Grade visuals only from frames or video decoded from the identified file and bound to `goal_id, production_job_id, shot_id, prompt_id, output_sha256` (and the sealed `bible_digest`). ffprobe PASS, C011 PASS, synthetic fixtures, prompts and text-only models are **not** observations → reply `VISUAL_QA=UNVERIFIED`, never `ACCEPT`.

## Procedure
1. Read `human_review_focus` from the Bible lint (risk flags) and look there first.
2. Inspect first / middle / last frame of each shot, and for each cut the pair (previous shot's last frame, next shot's first frame).
3. Check, against the Bible text: same subject identity phrase (breed, coat, collar, marks) and product shape/colour; no phantom limbs, eyes, teeth or duplicated products; screen direction and lighting palette continuous; the single directed action starts and completes; no flicker, warping or object popping.
4. Narration/captions when present: accuracy against cited evidence, readability, alignment.
5. Output one verdict with timecoded observations and the smallest plausible repair.

## Output (PROPOSED) — `visual_review.v0`
`goal_id, production_job_id, shot_id, prompt_id, media_sha256, bible_digest, clip_seconds, outcome, defects[{timecode,category,severity,evidence}], continuity_issues, proposed_next_action, reviewer_kind, review_status`. Do not store private prompt text, credentials or screenshots in public Issues.

## Boundaries
`REGENERATE` is a proposal. Do not queue a GPU job or spend Core's attempt budget (`MAX_COMFY_ATTEMPTS = 2`, same seed and prompt on technical retry). Replacing a rejected shot needs a future, explicitly approved, lineage-bearing mechanism; accepted shots and immutable manifests stay untouched. C010A/C011 decode and provenance rules remain mandatory. Heuristic scores (e.g. VBench-style) may rank candidates for review but never replace a human verdict.
