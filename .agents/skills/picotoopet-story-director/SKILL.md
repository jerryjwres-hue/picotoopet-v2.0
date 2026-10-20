---
name: picotoopet-story-director
description: Turn cited product findings into a typed video_bible.v1 sidecar and a coherent multi-shot direction. Review-only; never a GPU job.
---
# PicotooPet Story Director — revision 2 (agent instruction only)

This SKILL.md does **not** make Mac Core call an agent. G006 must wire a versioned, bounded stage template. Contract: `docs/p0_video_quality/video_bible_contract_v1.md`; executable reference: `tests/video_quality_skill_contract/video_bible_reference.py`.

## Inputs (all untrusted data, no tools, no web, no shell, no file writes)
Approved Goal objective, `source_finding_ref`s, `source_evidence_ids`, validated idea / brief / script, and verified reference *descriptors* (digest + rights source only — never paths or URLs).

## Procedure
1. Pick the single evidence-supported core claim. Every `product.claims[]` entry cites existing evidence ids; if it cannot, set `verified=false` and it may not be spoken. Never turn inference into fact.
2. Fix identity once, in words that can be repeated verbatim: `subject.identity_phrase` and `product.identity_phrase` (breed/coat/marks/accessories; shape/colour/material). Prefer pets and products; avoid hands and on-screen text (`logo_policy=NO_TEXT_OR_LOGO_IN_FRAME`; text goes in the overlay layer).
3. Fix scenes (environment + lighting phrase + ≤6 palette words) and `camera_rules` from the closed movement list. One scene per run of shots unless a cut is intended.
4. Write 2–8 `continuity_anchors` (short phrases, repeated in every shot) and `global_continuity_notes` (also copied into `CreativeBriefResult.continuity_notes`, the only brief field Core compiles).
5. Build `arc` = exactly the approved script beats; roles HOOK → DEMO → PAYOFF → CTA.
6. For each shot: ONE dominant visible action, 3–5 seconds (hard renderer ceiling ≈5.0 s; 3/4/5 s = 73/97/121 frames). Split "wake, walk, eat" into adjacent shots. Give `opening_state`, `closing_state`, `camera_framing`, `camera_movement`, `handoff_to_next`; use `CONTINUOUS` only when the closing state equals the next opening state verbatim.
7. Set `risk_flags` honestly (anatomy, fast motion, liquid, product close-up…). They route human review; they are not failures.
8. Mark anything missing as `unverified_fields`; `reference` stays `null` unless a verified digest exists.

## Output
`video_bible.v1` JSON exactly as the contract (extra fields forbidden). Never add fields to `shot_plan.v1`, `ProductionPlan`, seeds, workflows or negative prompts. Do not change frozen timings without review.

## Stop
Missing mandatory evidence or identity → `REVIEW`/`BLOCKED`; do not invent. No Comfy POST, lease, attempt change, secret handling or installs. Core identity and quality gates always prevail. A passing Bible is **not** a visual PASS (`VISUAL_QA=UNVERIFIED`).
