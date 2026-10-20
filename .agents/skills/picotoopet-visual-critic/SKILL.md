---
name: picotoopet-visual-critic
description: Review real decoded AI video clips and identify concrete visual defects with source-bound evidence.
---
# PicotooPet Visual Critic — PROTOTYPE (requires real video frames)

## Hard gate
Do not grade visuals unless **actual frames or video from the identified rendered file** are available and bound to `production_job_id`, `shot_id`, `prompt_id` and media SHA256. Technical FFprobe PASS, synthetic CI fixtures, prompts or text-only Mac gpt-oss are NOT observations of visual fidelity. If visual input unavailable, reply `VISUAL_QA=UNVERIFIED`, never ACCEPT.

## Review criteria
- Subject/product identity: same breed/coat/collar/brand/logo/shape; no phantom extra legs, eyes, teeth or duplicated products.
- Temporal: frame-to-frame shape stability, flicker, warps, object popping, drift; coherent direction and physical movement.
- Directed action: matches approved shot intent and camera brief; action starts/completes visibly.
- Multi-shot: handoff continuity, lighting and color treatment, storyline, composition and editing rhythm.
- Sound/captions when present: intelligibility, text accuracy, no clipped syllables, alignment, readability. Spoken product claims must remain evidence-supported.

## Decision
Choose exactly one `ACCEPT`, `REVIEW`, `REGENERATE`, `BLOCKED` with timecoded observations and the smallest plausible repair. Automatic heuristics/VBench may rank for review but are NOT equivalent to human-reviewed image quality. `REGENERATE` is a proposed action requiring explicit approved provenance and bounded budget; do not queue a GPU job or spend Core's attempt budget from this skill.

## Output (PROPOSED)
`visual_review.v0`: `goal_id`, `shot_id`, `prompt_id`, `media_sha256`, `clip_seconds`, `outcome`, `defects:[{timecode,category,severity,evidence}]`, `continuity_issues`, `proposed_next_action`, `reviewer_kind`, `review_status`. Do not store raw private prompt text, credentials, arbitrary execution instructions or screenshots in public Issues.

## Preservation
Keep original accepted outputs and immutable manifests; replace **only deliberately rejected shot** under a separate approved future versioned production mechanism. Existing C010A/C011 decode/provenance rules remain mandatory.
