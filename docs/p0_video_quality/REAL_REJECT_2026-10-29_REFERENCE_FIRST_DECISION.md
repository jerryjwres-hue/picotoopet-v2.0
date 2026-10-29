# P0-Q2 — real three-shot visual REJECT: evidence-led reference-first upgrade
Date: 2026-10-29 UTC | Owner: ChatGPT project controller | Scope: research and implementation decision, **no user GPU or file changes**.
Baseline candidate: `1698fee9e843c3be2de1a5185c49a5db4020af72` (Windows Preview 156); separate prior broad P0 base PR #96. Parent issue: #138, Claude #139, Codex #140, G006 quality #106.

## 1. Observed real-world failure and limitations

Operator's actual three Wan2.2 TI2V 5B T2V WebMs in Job `64695948-fb1a-4793-815f-3f6ad4d4d536` generated successfully after shot3 resumed as Core attempt2. Original Comfy history/Journals and output have provenance. **The human verdict is REJECT**, because character features/cat appearance change across shots, continuity/storytelling is weak, and lamp/props show impossible free-floating/unsupported geometry. No story success or visual acceptance is implied by render completion. At final check `FINAL_MP4=NOT_FOUND` and no C011 receipt file found; independently diagnose final delivery, but do not regenerate GPU just for missing MP4.

What we can prove from current source:
- `src/picotoopet_core/production/compiler.py`: each `GENERATIVE_VIDEO` shot is **independent T2V**; `IMAGE_TO_VIDEO` is executable only if package `trusted_local_assets[shot_id]` supplies the reference path. `_positive_prompt` now includes brief continuity notes under adapter `wan22-shot-prompt-v1.1.0`; prompting alone does **not** share a visual latent/character.
- `windows/desktop/src/PicotooPet.Desktop.Core/Production/ComfyWorkflowTemplateValidator.cs`: two frozen template IDs `comfy.wan22.ti2v5b.t2v.v1` and `comfy.wan22.ti2v5b.i2v.v1`. Same fixed diffusion `wan2.2_ti2v_5B_fp16.safetensors`, `umt5_xxl_fp8_e4m3fn_scaled.safetensors`, `wan2.2_vae.safetensors`; I2V adds `LoadImage` / approved input slot.
- `src/picotoopet_core/creative/{video_bible,quality,director,profiles}.py`: source-grounded Bible/director and structural evaluation already present. Do not create competing second Bible or claim continuity prose is equivalent to image consistency.
- `FinalVideoAssemblyService` C004 and C011 receipt verify integrity, media decode and lineage. None verifies subjective visual quality. Issues #104/#105 contain visual rubric/test-only prior work.

## 2. Why the first film failed: causal hierarchy

| Mechanism | Evidence | Consequence | Corrective priority |
|---|---|---|---|
| Each shot independent T2V; deterministic but **different** seeds | Core compiler and actual rendered plan | no shared image identity, product shape/scene geometry varies | **P0** freeze actual reference character/product and anchor every shot via existing I2V |
| No accepted 3-shot keyframe/storyboard before GPU | Operator's actual weak storyline; Bible exists but cannot enforce visual acceptance | disconnected scene changes and unclear action/payoff | **P0** cheap story/keyframe review BEFORE video |
| Physical supports/placement absent or not visually verified | Human observed hovering lamp | plausible image colors cannot imply physics | **P0** scene-layout constraints and evidence-based image/clip defect review |
| Current QA tests files not semantics | C011 source rubric | false sense of success | **P0** advisory vision critic + explicit visual outcome separate from C011 |
| Unconstrained model switching | RTX 5070 Ti 16 GB context + local Comfy | high install/OOM/licence risk | **P1** benchmark against current I2V first |

### Encoding audit to avoid treating compressed file size as a generative defect

Both frozen native Comfy templates `windows/production/workflows/wan22-ti2v5b-{t2v,i2v}-api-v1.json` use `SaveWEBM` with `codec=vp9`, `crf=16.111083984375`, and `KSampler steps=30, cfg=5, uni_pc/simple`. Official Comfy docs state **lower CRF = higher quality** (default SaveWEBM CRF=32). This is already a relatively high-encoding-quality setting; **300-420 KB per mostly static 4s clip alone is not proof of bad encode**. Verify real decode/bitrate separately, but do not waste GPU or engineering time merely lowering CRF or adding RIFE/ESRGAN for a wrong cat/story/floating lamp. Upstream definition: https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/SaveWEBM/en.md

## 3. Recommended P0 minimum workflow (reuse the same EXE and Core)

1. **Freeze immutable Video Bible**: one visual identity (white cat exact ears/eyes/body/scarf), approved pet-product appearance and claims, scene prop inventory/ground contact, consistent light/color/style. Simple three-beat story: hook/problem -> visible action/product use -> resolved/payoff. Per shot: subject ID, objective, primary action, 4 sec, camera/lighting, incoming/outgoing visual state. Reuse existing Creative v2 schema; do not add unvalidated fields.
2. **Pre-video keyframes**: one master front/side character sheet and three storyboard stills derived from the same approved reference (generated or uploaded with rights). Each still must pass *visual plausibility, physical placement, same identity/product, correct causal scene order*. Evidence: SHA256, provenance, rights/approval and shot identity. If not approved, no expensive Wan POST. Keyframe-generation method is separately vetted and consented: **a Skills file alone is not a renderer**.
3. **Approved I2V**: use the existing `comfy.wan22.ti2v5b.i2v.v1` per executable shot, with all `trusted_local_assets[shot_id]` bound to real immutable reference files. Build strict asset provenance/digest verification before Core compile and before Comfy. Avoid upgrading `GENERATIVE_VIDEO` silently. Old packages remain immutable and T2V legacy unchanged. Do not infer rights from file names. Only use explicit current Job/child Job lineage; never tamper with old package/digest.
4. **Optional sequence control**: after I2V yields are measured, inspect native ComfyUI Wan2.2 Fun InP (first+last frames) / Fun Control (depth, pose, trajectory), pinned model/workflow ID. A last frame from a failed shot must not automatically poison the next; explicitly approve source frames.
5. **Read-only Visual Critic**: sample candidate videos with existing FFmpeg/ffprobe at multiple defined timestamps (first/mid/end, optionally more for flicker). Show shot-contact sheet + keyframe pairings, inspect subject appearance, scarf/product, paws/ears/eyes, object supports and grounding, target action, order and transition, generated text/logo. Run local VLM only when consented and present. Output REVIEW/REJECT-SUSPECT/UNVERIFIED + evidence timecodes and SHA. *No AI-only ACCEPT until calibration against human labels*.
6. **Existing technical production**: unchanged one Mac Core Production Job/Plan/Worker Journal/one GPU queue, immutable shot commit, C004/C009 C010A/C011. No second finalizer; end-user video opens only after real persisted C011 PASS and human visual acceptance.

## 4. Open code, official docs and model feasibility — current 2026-10-29 review

| Option | Use now? | Evidence / constraints |
|---|---|---|
| **Wan2.2 TI2V 5B native Comfy I2V** | **P0 FIRST** | Already installed 5B for T2V and existing validated I2V graph; same core weights, first-frame image control. Official Wan/Comfy support. Does **not guarantee** continuity if the three stills differ. https://github.com/Wan-Video/Wan2.2 ; https://blog.comfy.org/p/wan22-day-0-support-in-comfyui ; https://huggingface.co/Comfy-Org/Wan-2.2 |
| **Wan2.2 Fun-5B-InP / Fun Control** | P1 second candidate | Alibaba PAI / Comfy official first+last and depth/pose/trajectory controls; additional checkpoints and workflow. 5B Fun InP repo reports 23 GB *weights* (not equal VRAM); 16 GB requires verified offload/quantization support and no-default-download. https://blog.comfy.org/p/comfyui-wan22-fun-inp-support ; https://huggingface.co/alibaba-pai/Wan2.2-Fun-5B-InP/blob/main/README_en.md |
| **HunyuanVideo-1.5** | P1 conditional A/B | 8.3B T2V/I2V; upstream claims >=14GB VRAM with offload, but original code lists Linux CUDA, and model carries **Tencent Hunyuan Community License**, not Apache/OSI. Must independently prove Windows Comfy adaptation, commercial license/territory and 16GB feasibility before any download. https://github.com/Tencent-Hunyuan/HunyuanVideo-1.5 ; https://huggingface.co/tencent/HunyuanVideo-1.5 |
| **LTX-2.5 ComfyUI** | **Not default** | Official LTX Comfy docs list CUDA GPU with **32GB+** VRAM, beyond current 16GB baseline. Pilot only if verifiable smaller compatible checkpoint/offload/licensing and real gain. https://docs.ltx.io/open-source-model/integration-tools/comfy-ui |
| **Qwen3-VL:4b via Ollama** | P0 *optional critic*, not generator | Official Ollama local model available ~3.3 GB distribution; requires Ollama >=0.12.7. Can understand images/video/spatial relations and produce **fallible advisory** structural verdicts; confirm Mac host RAM/version, no automatic pull/remote upload. Never send private frame by default. https://ollama.com/library/qwen3-vl:4b ; https://github.com/QwenLM/Qwen3-VL |
| **VBench-2.0** | Evaluation reference/offline | Published 2025; physics, commonsense, creativity, controllability, human fidelity; resource-heavy evaluation not production safety oracle. Do not install full suite on 16GB GPU by default. https://arxiv.org/abs/2503.21755 ; https://github.com/Vchitect/VBench/tree/master/VBench-2.0 |
| **StoryDiffusion** | Concept / still inspiration | NeurIPS 2024 consistent-self-attention across images and semantic motion prediction; does not plug directly into current Wan I2V workflow and is not a guaranteed consistency fix. https://proceedings.nips.cc/paper_files/paper/2024/hash/c7138635035501eb71b0adf6ddc319d6-Abstract-Conference.html ; https://github.com/HVision-NKU/StoryDiffusion |
| **ConsisID** | NOT for this pet case | CVPR 2025 identity preservation designed for **human faces**, not white-cat + pet-product spatial story. https://openaccess.thecvf.com/content/CVPR2025/html/Yuan_Identity-Preserving_Text-to-Video_Generation_by_Frequency_Decomposition_CVPR_2025_paper.html |
| SAM2 / RIFE / Real-ESRGAN | P2 selective repairs only | Segmentation / frame interpolation / enhancement do **not fix** broken story or wrong physical scene. Only after failure type shows these help. https://github.com/facebookresearch/sam2 ; https://github.com/hzwer/Practical-RIFE ; https://github.com/xinntao/Real-ESRGAN |

Note: all cross-model superiority claims need matched human A/B on user's actual RTX 5070 Ti. Manufacturer examples are not local measurements. Cross-model identical seeds do not produce comparable latent trajectories.

## 5. Machine-first **and** human-calibrated review

Review identity: `goal_id`, `creative_package_digest`, `production_job_id`, `plan_digest`, `shot_id`, `comfy_prompt_id`, `output_sha256`, reference SHA, prompt adapter version, model hash, frame timestamps.

- **Cheap deterministic** (safe pre/post GPU): actual file size/hash, ffprobe full media metadata, short/black/duplicate frame heuristic, wrong aspect, unexpected cuts, insufficient frames, contact support metadata if reference image has audited scene annotations. No invented physics claims.
- **Local VLM optional**: exact image/frame evidence and fixed schema; compare shot images to *same reference* not just text. Flags `identity_drift`, `floating_prop_suspect`, `morphology`, `action_missing`, `transition_jump`, `product_deformation`, `flicker_suspect`; include (shot, seconds, confidence, description, reference IDs). Require calibration for sensitivity/specificity; disagree => review.
- **Human feedback initially authoritative**: `VISUAL_REJECT` for this job with at least identity/story/physical reasons; C011 technical PASS could co-exist and is not `VISUAL_ACCEPT`. Accumulate labeled real examples. Once false-accept rate measured and validated, automated low-risk rejection, never automated GPU rerender by default.
- Suggested initial nonnumeric verdicts: `TECHNICAL_PASS` separate `VISUAL_REVIEW_REQUIRED`, `VISUAL_REJECT`, `VISUAL_ACCEPT`; omit uncalibrated 0-100 scores. Quality-based new generations require *new approved candidate lineage and GPU budget*, not Core crash attempt2.

## 6. Minimal A/B and economics

No GPU until approved story+reference kit; choose at most **one short shot** on same test concept for T2V baseline vs I2V reference (the first film's T2V baseline already exists). If single-shot I2V has comparable failure, do not launch 3×4s. Only after pre-registered human comparison (recognizability, physics, action, product exactness, acceptance) approve full three-shot I2V. Store per-shot render wall and GPU active separately; `gpu_active_seconds=UNVERIFIED` until measured. KPIs = visual-first-pass usable shots / attempted, complete visually accepted videos / completed candidates, GPU-minutes / accepted film, percent rejected at cheap pre-GPU stage, rejection taxonomy. With zero accepted videos, GPU minutes/accepted film is N/A, not zero.

## 7. Skill handling and file ownership

Existing **prototype, not installed/runtime-active** files in `architecture/quality-first-video-skills-v1`:
- `.agents/skills/picotoopet-story-director/SKILL.md`
- `.agents/skills/picotoopet-shot-prompt-engineer/SKILL.md`
- `.agents/skills/picotoopet-visual-critic/SKILL.md`

Agent skills can guide Claude/Codex's authorship, **but cannot automatically insert frames into Mac worker Ollama prompt stages or video quality gates**. Adapt them within existing typed Creative `profiles.py / video_bible.py / quality.py` + production compiler, and test the emitted strict Pydantic structure. No copying entire old docs branch / no brand-new QA framework.

**Claude issue #139**: owner Creative/skill/three-keyframe storyboard and renderer feasibility contracts. **Codex issue #140**: owner read-only Windows frame extractor/contact sheets and optional local multimodal critic. **Controller/G006 #106 + #138**: exact trusted image asset binding/provenance and model decision/CI, same runner. No source edits by this docs-only research PR.

## 8. STOP criteria

- Any generated keyframe fails visual identity, text/image rights, product claims, scene physics => stop before GPU.
- Missing trusted asset digest/approval, Comfy model absent, Windows memory feasibility unknown, missing license obligations => BLOCKED.
- Any unknown live Comfy `prompt_id`, active queue, unsettled journal => do not POST.
- Any generated visual unreliability => REVIEW/REJECT, not silently ACCEPT.
- New agent/model installation, local hardware operations and GPU use require user explicit authorization.
