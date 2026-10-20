# PicotooPet — Quality-first Multi-shot Video: Skills + Control + Evaluation RFC (2026-10-20)

> **Status: PROPOSAL ONLY — NOT IMPLEMENTED.** Dedicated docs-only branch; no user-device installs, GPU work, production files, CI or release. Integration source reference: G006 PR #96 commit `abadea4b7a1382eb1d0fb94540185be2c22d2c48`; check latest commit again before implementing. User's product goal: **high-quality finished multi-shot videos at high usable yield / low cost**, NOT a one-shot-only product or artificial task-count restriction. Existing first-WebM packet remains historical diagnostics.

## 1. Existing capabilities vs gap

| Existing, source-checked | Real guarantee | Missing; must not claim PASS |
|---|---|---|
| Mac Ollama gpt-oss:20b → autonomous discovery/synthesis → local Creative | Real evidence linkage, strict schema, 4 stages and `shot_plan.v1` | Subject/reference-image visual identity, story/directing quality and physical realism |
| `src/picotoopet_core/creative/{profiles,quality,execution}.py` | Idea/brief/script/shot schema + evidence IDs + beat coverage/order | Brand-specific creative brief and versioned **model-adapted** prompts, long-shot movement consistency |
| `src/picotoopet_core/production/compiler.py` | Immutable deterministic multi-shot tasks with `positive_prompt`, workflow allowlist, seed, duration, `trusted_local_assets[shot_id]` for I2V | Automatic **reference-first** route and immutable reference identity/masks/first-last frame conditioning |
| `windows/desktop/src/PicotooPet.Desktop/Services/ProductionExecutionService.cs` | Approved same-EXE GPU worker, journal, prompt recovery, bounded attempts, Comfy real output commit; recent G006 commits add `ProductionShotObservation` telemetry and whole-plan preflight | Per-shot visual quality decision, reuse or safe deliberate replacement of bad shots, quality-aware renderer A/B |
| C004/C007/C008/C009 FFmpeg postproduction + C010A/C011 | Technical decode, timing, provenance, durable QA receipt, safe Open | Does not grade animal anatomy, identity, flicker, story coherence or visual aesthetics |

**Non-negotiable:** reuse the existing canonical `CreativeJob` / `CreativePackage` / `ProductionPlan` / `ProductionTask` / `Comfy prompt_id` / `ProductionPackage` / QA receipt. Keep one Windows EXE host and one Core queue. No second DB/renderer/scheduler, no fake WebGPT handoff, no modification of frozen schema by silent JSON extra fields, no use of mock CI to claim actual video quality.

## 2. Recover historical design components (audit installed state before adoption)

Earlier frozen platform plan proposed **Mac PydanticAI / MCP Hub / BGE-M3 + Qdrant** for tool-safe creative research and retrieval; **Windows Wan2.2 TI2V-5B, Wan2.1 VACE-1.3B, SAM2, RIFE, Real-ESRGAN, Whisper, FFmpeg** for controllable generation, masks, interpolation, upscale, transcription and assembly. They are **historical planned components, NOT proof that model weights or services are installed, GPU-compatible or production wired**. Check `main`/current PR source, individual license and hardware evidence before any deployment.

- Prefer retrieve already approved product source facts and reference stills. BGE-M3/Qdrant later only if actual retrieval volume warrants it: vector search is candidate finding, never canonical evidence until the existing source validation accepts it.
- `SAM2` can extract/track a subject for reference masks; optional GPU overhead. `Whisper` can audit final narration/caption alignment; it does not generate image detail. `RIFE` is selective motion interpolation, `Real-ESRGAN` selective visual upscale; neither repairs impossible anatomy/identity reliably. Never silently enhance every shot.
- Mac `gpt-oss:20b` is the text story/script/prompt planner; do **not** assume it can perform frame-level visual inspection unless an actually verified vision capability is present.

## 3. External tools benchmarked; add only as validated, immutable versioned adapters

| Candidate / official evidence | Expected use | Fit now | Tradeoff/decision |
|---|---|---|---|
| Current **Wan2.2 TI2V-5B** + pinned Comfy API | baseline, unrestricted T2V & approved I2V | **KEEP PRIMARY** | Zero workflow migration; quality must be measured on real shots |
| **Wan2.1 VACE-1.3B/14B** (official VACE + Comfy templates) | reference-to-video, masked repair, structure/motion video control | **P1 PILOT** | Version is Wan2.1 VACE, NOT interchangeable with Wan2.2 model/LoRAs; new bounded workflow + pinned asset verification and GPU capacity needed |
| **Wan2.2 Animate-14B** | reference character + driving-video motion/character replacement | **P2 SPECIALIST** | Needs approved motion driver, model/preprocessor & substantial resources; don't blanket-route normal product shots |
| **HunyuanVideo-1.5 480p I2V step-distilled** | rapid reference-guided alternative generator | **P1 A/B PILOT** | Official 8/12 steps on RTX 4090 (not a PicotooPet speed guarantee). Different model/scheduler/prompts/licence; no substitution in current frozen `workflow_id` |
| **LTX-2.3 / LTX-2.5** native Comfy templates | optionally coherent A/V, keyframes, IA2V/FLF2V/ID control | **P2 EXPERIMENT** | Larger model, distinct memory/frames and community licence. No guaranteed faster/cheaper on user's unspecified GPU. Do NOT duplicate existing narration/mux by default |
| **VBench-2.0** | offline comparative video evaluation (physics/motion/composition/anatomy) | **P1 BENCHMARK ONLY** | GPU and dependency cost; benchmark is an imperfect signal, not real human approval |
| **Remotion official Agent Skills** | agent-authored layout, captions, titles, branded motion graphics | **P2 OPTIONAL** | Skills are instructions to coding agents, NOT a video-generation/quality model; existing FFmpeg C009 remains production authority |
| **SAM2 / Real-ESRGAN / RIFE / Whisper** | segmentation/masked fix, selective post, speech verification | **P1/P2 BY FAILURE CATEGORY** | Run only when a measured issue justifies GPU or latency overhead |

References (pin upstream tags/commits and read licences before consuming):
- Wan2.2: https://github.com/Wan-Video/Wan2.2
- VACE official guide: https://github.com/ali-vilab/VACE/blob/main/UserGuide.md ; Comfy example https://github.com/Comfy-Org/docs/blob/main/tutorials/video/wan/vace.mdx
- HunyuanVideo-1.5: https://github.com/Tencent-Hunyuan/HunyuanVideo-1.5 ; official prompt handbook https://github.com/Tencent-Hunyuan/HunyuanVideo-1.5/blob/main/assets/HunyuanVideo_1_5_Prompt_Handbook_EN.md
- LTX 2.3: https://github.com/Comfy-Org/docs/blob/main/tutorials/video/ltx/ltx-2-3.mdx ; LTX 2.5 templates https://github.com/Lightricks/ComfyUI-LTXVideo/tree/master/example_workflows/2.5 ; inspect the model-specific licence.
- VBench2: https://github.com/Vchitect/VBench/tree/master/VBench-2.0
- Remotion official agent skills: https://github.com/remotion-dev/skills
- SAM2: https://github.com/facebookresearch/sam2 ; RIFE: https://github.com/hzwer/Practical-RIFE

## 4. Three controlled, repository-owned Agent Skills (prototype, not auto-connected runtime)

**Design versioned `SKILL.md` instructions for Claude/Codex authoring and corresponding *Mac Core-owned* bounded prompt templates**. Merely placing `SKILL.md` in the repository will NOT make the production Mac worker invoke it. Each skill's generated output must be mapped back to **existing canonical Pydantic models and source provenance**, never arbitrary executable Comfy JSON. All input findings treated as untrusted data.

1. **story-director** (Mac Creative `profiles.py`, `quality.py`): produce a cohesive **Video Bible** (target audience, emotional arc, one product claim backed by evidence, must-keep subject/product attributes, scene continuity, palette/lighting, shot transition intentions). Quality preflight: story has a hook, evidence-backed claim, shot coverage, payoff and proposed cut rhythm. Don't invent facts.
2. **shot-prompt-engineer** (Mac `shot_plan.v1` → `production/compiler.py`): output *one per-shot typed prompt* from a frozen per-project bible plus actual `shot_id`: subject + concrete single primary action + environment + camera framing/motion + lighting/style + time-order + physical constraints + disallowed visual defects. Existing `positive_prompt` max 5000 chars; seed/negative prompt policy come from immutable ProductionPlan, NOT agent edits. Different frozen adapters for Wan/Hunyuan/LTX, paired with same shot intent and exact reference asset IDs. **Reference beats prompt verbosity** for product/character identity: prefer approved I2V when an immutable trusted reference exists.
3. **visual-critic-and-repair-planner** (Windows QA evidence → Mac/WPF reviewer): **only after real decoded media is available**, record per-shot ACCEPT/REVIEW/REGENERATE/BLOCKED + faults (identity drift, paws/legs, product logo deformation, flicker/warping, camera incoherence, missed action) + reviewed thumbnails/timecodes + suggested *one controlled change*. Structural FFprobe cannot by itself output `VISUAL_ACCEPT`. No model training/extra renderer by default.

**Video Bible provenance:** store canonical deterministic JSON as an immutable, named, digest-bound sidecar or a compatible existing CreativePackage manifest field **after explicit contract review**; do not silently add forbidden fields to current strict `ShotPlanResult`/`ProductionPlan`. Reuse existing `trusted_local_assets[shot_id]` input pathway where supported. A referenced still has file digest, origin, user rights/consent, approved subject ID and target shot; fail closed if stale/tampered.

Example *planner-only* constrained prompt assembly (not a Comfy workflow or schema mutation):
```text
Subject anchor: [immutable approved reference ID and visual attributes]
Action: [one primary visible motion, temporal sequence with a clear ending]
Scene: [specific location; consistent props and product identity]
Camera: [framing + one realistic movement]
Lighting/color: [shared video-bible look; shot-specific variation]
Physical continuity: [number of limbs, product shape, direction, scene handoff]
Avoid: [unwanted deformation, duplicate limbs, changing text/logo, flicker]
```

## 5. Production pipeline to implement without breaking Core / GPU semantics

```text
Approved product facts / image assets / trusted evidence
  -> Mac Goal discovery & synthesis (source validation, optional retrieval)
  -> Mac Creative: story-director -> SCRIPT -> SHOT_PLAN (existing typed stages)
  -> reference & continuity manifest (digest-bound, no untrusted paths)
  -> per-shot prompt/compiler, model-specific immutable allowlisted workflow
  -> same Windows EXE Worker: per-shot journal/lease/Comfy real POST & history
  -> existing Core output commit and successful-shot reuse
  -> technical media QA (existing FFprobe/decode) + optional cheap frame checks
  -> human/verified vision review of subject/action continuity and flaws
  -> ACCEPT => existing C009 assembly -> C010A/C011 -> Windows verified MP4 Open
     REVIEW => user review; REGENERATE => new explicitly approved bounded
       lineage preserving originals; BLOCKED => no fresh GPU job
```

**Prioritize cheap-before-expensive:** quality of brief/shot plan/reference before GPU, then deterministic checks; expensive VBench or segmentation only for uncertain/high-value shots. Preserve known good shot media; never re-render the whole film because one shot fails. Respect Core's existing max **two attempts** as an attempt ceiling, NOT a licence for blind “quality retry”; adding deliberate alternate candidates requires a separately approved future workflow with new lineage and budget.

## 6. Evidence + measurement (baseline first, no guessed benefits)

For real eligible production tasks record: `goal_id`, `creative_package_digest`, `production_job_id`, `plan_digest`, `shot_id`, `workflow_id`, `reference_digest` when present, `prompt_version`, `seed`, `comfy_prompt_id`, `output_sha256`, `render_seconds`, `qa_outcome`, `rejection_reason`, `gpu_seconds` if actually measurable. Keep nonsecret aggregates, do not dump tokens/raw private prompts.

KPI:
- **First-pass shot yield** = shots accepted without intentional regenerated candidate / shots actually attempted.
- **Final-video yield** = visually approved complete videos / completed real render-backed video candidates.
- **GPU minutes per accepted video** = measured GPU-bound rendering minutes / approved finished videos.
- **Time-to-first-viewable preview** from initial accepted Goal (not CI fixture).
- **Top rejection causes** by category. No baselines yet; `UNVERIFIED`.

Suggested restrained A/B pilot when authorized: choose a small, fixed set of representative real pet-product scene briefs with approved images, compare current T2V against I2V-with-reference using same target/scene/rubric and bounded attempts, blind review by a human before declaring “improvement”. Only then compare HunyuanVideo-1.5 or VACE with matched output profile, reproducible seeds where possible (seeds are not cross-model semantically equivalent), measured seconds and failure rates. Document hardware VRAM, model licence, exact workflow/model hash. Reject speedups that lower usable yield.

## 7. Exact implementation sequencing & ownership

- **P0-QA / Claude #104 (tests/docs only, no new runtime models):** draft 3 skill instruction files, typed Video Bible/shot-prompt review samples, observable visual rubric and A/B scorecard; propose canonical model-compatible mapping. Test-only fixtures can assert story/plan invariants, not aesthetic PASS. Stop at handoff.
- **G006 #91 (sole production owner):** first patch **versioned reference-first prompt/compiler bridge** in existing `creative/profiles.py`, `creative/quality.py`, `production/compiler.py` plus existing asset provenance, ensuring previous Source→Package→Plan hashes remain trustworthy and legacy workflows unchanged. Branch source changes only after G006 checks strict schema. Add focused native contract tests. Continue multi-shot full MP4 integration already in progress; do not duplicate recent new `ProductionShotObservation` and whole-plan guard.
- **Codex new narrow branch only after quality failure data:** automate **cheap media-side observability** and optional reviewer thumbnails as distinct QA *evidence* (not new renderer/second executor); prefer using existing Windows test harness and FFprobe. Avoid opportunistic new GPU models until model/VRAM/license and A/B evidence exist.
- **Model pilot later:** explicit model-adapter decision and pinned Comfy JSON for VACE/Hunyuan/LTX with independent contracted workflow IDs, expected bytes/sha/VRAM, licence review, one-GPU scheduler and failure telemetry. No automatic remote/cloud calls or installations.

### Acceptance hierarchy

1. Source+contract: Mac Creative validates versioned quality spec and approved image asset binding; original tests remain green.
2. Native Windows: same EXE worker can execute a *multi-shot frozen Plan* with all approved tasks (fake HTTP here is only contract).
3. Physical: real Mac AI creative, real Comfy Wan multi-shot `prompt_id` and media hashes, real visual review, final verified MP4 playback, time/gpu measurements. Only #3 can establish real **visual yield**.
