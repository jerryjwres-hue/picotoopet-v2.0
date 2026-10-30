---
name: picotoopet-story-keyframe-review
description: Human or multimodal pre-review of the three approval stills in a keyframe_kit.v1 before any video GPU is used.
---
# PicotooPet Keyframe Review (pre-GPU)

Use after `build_keyframe_kit` produced a `keyframe_kit.v1`. Review-only: no image generation, upload, Comfy call or attempt changes from this skill.

## Procedure
1. Look at the three actual stills (not prompts). For each `keyframe_id` walk its `review_checklist`.
2. Compare the three stills against each other and against `locks`: same subject (face or head, body proportions and marks); same accessory, wardrobe and product colour, shape and position; same set layout, props and lighting; every prop visibly supported.
3. Record `ACCEPT-CANDIDATE`, `REVIEW` or `REJECT` per still with the defect and evidence. Uncertain means `REVIEW`. Only a human approval counts as `human_approved`.
4. Any inconsistency among the three stills -> `REJECT` the set. Do not patch with prompts.

## Limits
Even with three approved stills, Mac Creative cannot make them trusted. `evaluate_keyframe_submissions` can at best return `AWAITING_CORE_PROVENANCE`; Core must recompute the image sha256, decode size, bind generator identity and approval, and mint the `trusted_local_assets[shot_id]` reference (see `docs/p0_video_quality/story/README.md`). Never write a path or digest into the kit.
