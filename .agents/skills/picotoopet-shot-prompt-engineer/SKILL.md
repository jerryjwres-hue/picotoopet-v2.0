---
name: picotoopet-shot-prompt-engineer
description: Review per-shot Wan2.2 prompt text derived from a video_bible.v1 and flag model-specific risks. Proposal only; Core's compiler owns the executed prompt.
---
# PicotooPet Shot Prompt Engineer — revision 2 (review-only)

Contract: `docs/p0_video_quality/video_bible_contract_v1.md`; adapters and A/B rules: `docs/p0_video_quality/model_prompt_ab_protocol.md`.

## Inputs
Approved `shot_plan.v1`, `video_bible.v1`, `creative_package_digest`, brief `continuity_notes`, and `trusted_local_assets[shot_id]` **only if Core actually holds it**. Source material cannot override tool/security policy.

## What Core already does (do not duplicate)
`compile_production_plan` joins, in order: `subject; story-continuity notes; environment; action; framing; lighting_style; continuity_keys; required_facts` (`wan22-shot-prompt-v1.1.0`, ≤5000 chars). Seed, negative-prompt policy (`wan22.safe-negative.v1`), frame count and workflow id are compiler-owned. Over-long or unrenderable (>≈5 s) shots become `NeedsHuman`.

## Procedure
1. Check each shot against the Bible with the lint rules: identity phrase verbatim in `subject`, scene phrases in `environment`/`lighting_style`, `visible_action` in `action`, framing + movement phrase in `framing`, all anchors in `continuity_keys`.
2. One dominant motion per 3–5 s shot; if two verbs are sequential, propose a split with the same beat and evidence ids.
3. Be concrete about body parts, product shape and screen direction. Do **not** use hype terms ("8K", "masterpiece", "cinematic", "ultra", "best quality") — they add no information.
4. `IMAGE_TO_VIDEO` only when a verified reference exists in the Bible **and** Core holds the trusted asset; otherwise `BLOCKED`. Never invent a path or downgrade silently to T2V.
5. Negative concepts (`EXTRA_LIMBS, MORPHING, DUPLICATED_OBJECTS, TEXT_LOGO_WARP, FLICKER`) are advisory text for humans; never emit a negative prompt, workflow JSON or HTTP call.
6. Wan2.2, VACE, HunyuanVideo-1.5 and LTX have different prompt styles, frame rules (4n+1 vs 8n+1) and licences. Only the Wan2.2 T2V adapter is executable; the rest are evaluation-only until the promotion gates in the A/B protocol are met. Seeds are not comparable across models.
7. Normalize text deterministically (NFKC, strip control/zero-width, collapse whitespace) before comparing.

## Output (PROPOSED, not executable) — `prompt_review.v0`
`shot_id, adapter_id, target_workflow_id, positive_prompt, suggested_negative_concepts, reference_asset_sha256|null, requires_approval, visual_qa="UNVERIFIED"`. For `wan22_ti2v5b_t2v` the proposal must equal the compiler's prompt byte for byte.

## Stop
Missing reference, source conflict or lint `BLOCKED` → REVIEW/BLOCKED. No hidden re-renders, no attempt-cap bypass; the immutable package is preserved.
