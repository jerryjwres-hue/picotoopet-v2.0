# PicotooPet P0 #91 — G-Wan Windows ComfyUI/Wan read-only preflight

**Audit baseline:** [b6230da62eb803e9a7be840374feeb481a657c3a](https://github.com/jerryjwres-hue/picotoopet-v2.0/tree/b6230da62eb803e9a7be840374feeb481a657c3a), 2026-10-20. This branch contains **documentation and a passive inspection script only**. No production Worker, Journal, HOLD/ALLOW, Mac Core, or GPU execution source is changed.

**Current live-device status:** COMFY_8188=UNVERIFIED; WAN_MODEL_SHA=UNVERIFIED; NATIVE_NODES=UNVERIFIED; NVIDIA_VRAM=UNVERIFIED; FFMPEG_LIBX264=UNVERIFIED; PROMPT_HISTORY=UNVERIFIED; REAL_COMFY_GPU=UNVERIFIED; WEBM_X3=UNVERIFIED; C011_MP4=UNVERIFIED; VISUAL_ACCEPT=UNVERIFIED. A successful GitHub native CI run cannot promote these statuses.

## Safety and use

Do not use these instructions to power, install, repair, start, or test an unsafe Windows workstation. The user's Front Basement/AFCI circuit has exhibited unexplained trips, and the P0 operator contract explicitly requires qualified electrical clearance before load-producing activity, then explicit authorization for model loading/first render. On a machine **already safely running** ComfyUI, this script performs read-only HTTP GETs and local reads only. It never calls **POST /prompt**, POST /queue, Core claim/attempt/cancel, starts Comfy, launches the Windows GUI/Worker, edits the acceptance gate, installs a model, creates an output folder or invokes an encoder. A full model SHA scan is disk-intensive; use -SkipModelHashes for rapid presence-only inventory, which must remain UNVERIFIED.

At a verified checkout of the specified source SHA:

~~~powershell
# No writes, no GPU inference, no process launch; full model hash can be slow.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\docs\p0_wan_preflight\Test-WanReadOnlyPreflight.ps1

# If Comfy Desktop's data root is elsewhere, supply the actual existing root.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\docs\p0_wan_preflight\Test-WanReadOnlyPreflight.ps1 -ComfyDataRoot 'D:\ComfyUI' -SkipModelHashes

# Only for prompt IDs already recorded by Core/Worker, never guessed IDs.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\docs\p0_wan_preflight\Test-WanReadOnlyPreflight.ps1 -PromptIds 'known-prompt-id-1','known-prompt-id-2','known-prompt-id-3' -WebmPaths 'D:\ComfyUI\output\existing-1.webm'
~~~

The report is emitted to standard output as JSON and never writes a report to disk. Optional -ManifestPath points to an unchanged, SHA-verified copy of windows/bootstrap/model_manifest.json. The passive PASS_PASSIVE_ONLY aggregate indicates that **available checks** were observed, not that a GPU can render a shot, not that the Worker can submit, and not that a Core receipt exists. If a compositor node or model is absent, label BLOCKED and hand to the owner. If a field is missing/unmeasured, label UNVERIFIED; do not invent a PASS.

### Frozen graph and numerical contract

| Contract | Exact source-controlled value |
| --- | --- |
| Workflow | comfy.wan22.ti2v5b.t2v.v1; embedded windows/production/workflows/wan22-ti2v5b-t2v-api-v1.json |
| Comfy endpoint | http://127.0.0.1:8188 **on the Windows host only** |
| Native T2V graph classes | UNETLoader, CLIPLoader, VAELoader, ModelSamplingSD3, CLIPTextEncode x2, Wan22ImageToVideoLatent, KSampler, VAEDecode, SaveWEBM |
| Diffusion model | diffusion_models/wan2.2_ti2v_5B_fp16.safetensors |
| Text encoder | text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors; CLIPLoader type=wan |
| VAE | vae/wan2.2_vae.safetensors |
| Sampler | KSampler steps=30, cfg=5.0, sampler_name=uni_pc, scheduler=simple, denoise=1.0; ModelSamplingSD3 shift=8.0 |
| Saved shot | SaveWEBM codec=vp9, fps=task.fps, crf=16.111083984375, mime_type=video/webm |
| Frozen render slots | positive_prompt, seed, width, height, frame_count, fps, filename_prefix; no runtime model/node rewrites |
| 4-second shot | **97 frames** from nearest Wan 4n+1 family at 24 fps; 97/24=4.041666... seconds nominal video time, subject to container timestamps |
| First three shots | Three separate **Executable** GENERATIVE_VIDEO tasks; order 1,2,3; 24 fps; 97 frames each; seeds/prompts come from the frozen Plan, **not operator-selected constants** |
| Output profiles | landscape 832x480x24, vertical 480x832x24, square 640x640x24; inspect plan.output_profile_id; no unapproved resolution override |
| Filename prefix | PicotooPet/production/{production_job_id}/{task.Order:D3}-{sanitized-shot-id}; actual SaveWEBM suffix/name comes from history |
| Result | Comfy history status completed and exact .webm output, normal file under trusted Comfy output root, bytes>0, SHA256, Core commit, then existing C011/QA final MP4 |

Sources: [T2V template](https://github.com/jerryjwres-hue/picotoopet-v2.0/blob/b6230da62eb803e9a7be840374feeb481a657c3a/windows/production/workflows/wan22-ti2v5b-t2v-api-v1.json), [ComfyWorkflowTemplateValidator.cs](https://github.com/jerryjwres-hue/picotoopet-v2.0/blob/b6230da62eb803e9a7be840374feeb481a657c3a/windows/desktop/src/PicotooPet.Desktop.Core/Production/ComfyWorkflowTemplateValidator.cs), [profile.py](https://github.com/jerryjwres-hue/picotoopet-v2.0/blob/b6230da62eb803e9a7be840374feeb481a657c3a/src/picotoopet_core/production/profile.py), [ProductionExecutionService.cs](https://github.com/jerryjwres-hue/picotoopet-v2.0/blob/b6230da62eb803e9a7be840374feeb481a657c3a/windows/desktop/src/PicotooPet.Desktop/Services/ProductionExecutionService.cs).

### Model identity and path admission

The source [bootstrap model_manifest.json](https://github.com/jerryjwres-hue/picotoopet-v2.0/blob/b6230da62eb803e9a7be840374feeb481a657c3a/windows/bootstrap/model_manifest.json) pins E:\PicotooPet\Models and the **full SHA256** of each file:

| File | SHA256 |
| --- | --- |
| wan2.2_ti2v_5B_fp16.safetensors | 456f901338bd9eadbded3828b819109a9b68e8a525ca5cf8d0049a69fcfeca1e |
| umt5_xxl_fp8_e4m3fn_scaled.safetensors | c3355d30191f1f066b26d93fba017ae9809dce6c627dda5f6a66eaa651204f68 |
| wan2.2_vae.safetensors | e40321bd36b9709991dae2530eb4ac303dd168276980d3e9bc4b6e2b75fed156 |

The 5B and VAE files are from Comfy-Org/Wan_2.2_ComfyUI_Repackaged revision e58ce6c7762f9662699e3479ba30b5004204f93c; UMT5 is from Comfy-Org/Wan_2.1_ComfyUI_repackaged revision 06e001fc51048fb03433a6fb25334de7836704a5. The manifest additionally marks Wan2.1 VACE 1.3B and Wan2.1 VAE required for the *whole bootstrap inventory*, but the current ProductionExecutionService T2V preflight checks **these three files only**. Do not falsely block a 5B T2V on the optional-for-T2V auxiliary two models, nor report the overall five-file installer as fully verified.

ComfyUI must actually advertise the **three pinned filenames as loader choices in GET /object_info**, not merely have files on E:. Its extra_models_config.yaml should point to the external root. The built-in model hash requirement does **not** support substituting another filename, quantization, model version, or sampler without a separate reviewed contract change. Comfy Desktop resources\ComfyUI is forbidden as a managed model/data tree.

### API and filesystem observations (strict GET/read only)

| Observation | API / local surface | Acceptance boundary |
| --- | --- | --- |
| Service/version and device info | GET /system_stats | API accessible; record observed VRAM/torch/device data where present; **not** a successful sample render |
| Nodes and loader model choices | GET /object_info | All graph nodes; model dropdown choices include three exact filenames; check SaveWEBM codec=vp9, KSampler uni_pc/simple, CLIPLoader type=wan before live use |
| Queue | GET /queue | Existing running/pending prompts require reconciliation/review; never clear/cancel/re-POST |
| Existing history | GET /history?max_items=50; GET /history/{known_prompt_id} | A retained history may be partial; a missing ID is not proof of no prior GPU submission; status.completed + output WebM must match Core record |
| Comfy data root | %APPDATA%\ComfyUI\config.json basePath, then fixed [ProductionLocalEnvironment](https://github.com/jerryjwres-hue/picotoopet-v2.0/blob/b6230da62eb803e9a7be840374feeb481a657c3a/windows/desktop/src/PicotooPet.Desktop/Services/ProductionLocalEnvironment.cs) candidate order | Existing output folder, under real running Comfy root, ordinary non-reparse files; no directory auto-creation in this inspection |
| Known Worker journal | %LOCALAPPDATA%\PicotooPetV2\MediaWorker\v1\*.submission.json | Read only and correlate exact task, plan digest, graph digest, prompt_id; pending/unknown submission prohibits new POST |
| Model exact files | E:\PicotooPet\Models\{diffusion_models,text_encoders,vae}\... | Files present AND SHA256 exact AND visible to Comfy loader |
| FFmpeg/FFprobe | ffmpeg -hide_banner -encoders; ffprobe -version | libx264 is present; later actual FFmpeg C011 output should be H.264 yuv420p in MP4 with QA receipt, not confuse raw VP9 WebM with final MP4 |
| GPU inventory | nvidia-smi --query-gpu=name,driver_version,memory.total,memory.free,memory.used,utilization.gpu,power.draw --format=csv,noheader,nounits | Snapshot and baseline only; **no validated minimum VRAM** from repository; fail on real OOM, never promise sufficient memory from total alone |

### Two targeted contract risks for G006 (no production changes here)

1. **"Preflight" is not strictly read-only.** ProductionExecutionService.cs PreflightAsync line 182 calls Directory.CreateDirectory(outputRoot). Never invoke it to satisfy the current no-side-effect preflight. The independent script observes instead. Minimal future G006 change *if necessary*: split pure Observe/Validate from the mutating prepare-to-run phase, keeping actual production output initialization immediately before authorized execution and preserving fail-closed semantics.

2. **Whole-bootstrap required != T2V-required.** windows/bootstrap/model_manifest.json marks 5 models required, but ProductionExecutionService.cs lines 36-41, 156-176 hashes only Wan2.2 5B + UMT5 + Wan2.2 VAE. The bootstrap installer can report incomplete for unrelated Wan2.1 files despite an otherwise valid T2V first shot. Minimal future owner fix *only if this actually blocks first-run UI*: distinguish role-scoped T2V admission from full-model-suite installation reporting; do not weaken the three pinned SHA checks.

Also note: ProductionExecutionService.cs lines 48-50 has a **20-minute history polling timeout**, and ProductionShotObservation.WallElapsedMs explicitly includes non-GPU wall time. GPU execution may outlast this timeout on a constrained VRAM host. Treat this as an **evidence-dependent risk**, not proof of a live bug; only G006 should adjust policy when actual history timings and queue state are known. The current preflight checks LoadImage even for T2V although T2V template does not include it; usually a built-in core node, but if absent this can unnecessarily block T2V. No alternative Worker implementation is authorized in this window.

### Real three-shot collection: after separate clearance and authorized controlled run ONLY

The exact three Task IDs, Plan digest, Task prompts/seeds/width/height/fps/frame_count and Core prompt_id bindings must first come from the authorized Mac Core GET Plan/Job/Package, with **HOLD-first + exact-job ALLOW** controlled by G006's combined operator contract. This packet does not issue a render. Once G006's existing same-EXE Worker has generated three prompts:

~~~powershell
# GET history using Core-bound real IDs; do NOT invent, POST, retry or clear a queue.
$base = 'http://127.0.0.1:8188'
$ids  = @('REAL_CORE_PROMPT_ID_1','REAL_CORE_PROMPT_ID_2','REAL_CORE_PROMPT_ID_3')
foreach ($id in $ids) {
    $h = Invoke-RestMethod -Method Get -Uri "$base/history/$id"
    $entry = $h.PSObject.Properties[$id].Value
    [pscustomobject]@{ PromptId=$id; Status=$entry.status; Outputs=$entry.outputs }
}

# Probe only the actual already-existing Core-bound output file (replace example path).
$webm = 'D:\ComfyUI\output\PicotooPet\production\<real-job-id>\<history-filename>.webm'
(Get-Item -LiteralPath $webm).Length
(Get-FileHash -LiteralPath $webm -Algorithm SHA256).Hash.ToLowerInvariant()
ffprobe -v error -show_entries 'format=duration,size,format_name:stream=index,codec_type,codec_name,width,height,nb_frames,r_frame_rate' -of json -i $webm
~~~

The WebM path must be built from the **actual history output.filename/output.subfolder and trusted output root**, not by copying the illustrative placeholders. Confirm output SHA/length against the matching Core committed Task output, not only against local filename. For each of three tasks record: production_job_id, plan_digest, task_id, shot_id, order, workflow_id, prompt_id, output_relpath, bytes, sha256, width, height, fps, frame_count, ffprobe duration/codec and verified Core commit timestamp. Save only sanitized evidence, never tokens/prompts containing private source facts.

For an actual user-authorized GPU run, capture 1-second NVIDIA telemetry samples **only while rendering** (e.g. nvidia-smi --query-gpu=timestamp,index,utilization.gpu,memory.used,power.draw --format=csv,noheader -l 1, stop when the real third job finishes). Record UTC submission, execution_start, execution_success/completion times from trustworthy native history events where available, along with Worker per-shot wall_elapsed_ms and peak sampled VRAM. **Wall duration is not GPU busy time.** Sampling GPU utilization allows only an **estimated utilization-weighted busy interval** and power-derived energy estimate, not precise GPU CUDA execution duration; if timestamps/sampling are incomplete, set GPU_BUSY_SECONDS=UNVERIFIED. Do not divide an unverified GPU cost by a guessed number of good shots.

After all three VP9 WebMs and Core commits, existing Worker/C011 handles final FFmpeg postproduction/receipt. Native QA should verify H.264, yuv420p, 24-fps target profile/duration, approved manifest/receipt hash and Windows playback. Neither this script nor manual FFmpeg calls should manufacture an MP4 or bypass C010A/C011. Human review scores camera/action continuity, pet/product identity, artifacts, legibility, temporal drift, and yes/no ACCEPT for every shot and full master. **First-shot yield = human accepted first attempts / actually rendered first attempts; cost per accepted master requires actual GPU utilization/power/time and approved accepted master counts.**

### Triage matrix

| Evidence | Classification | Owner / next step |
| --- | --- | --- |
| No 8188 GET /system_stats or /object_info | BLOCKED: COMFY_OFFLINE | Windows device/config operator after electrical clearance; never start in preflight |
| Missing Wan22ImageToVideoLatent / SaveWEBM or pinned loader choice | BLOCKED: NATIVE_GRAPH / MODEL_DISCOVERY | Comfy environment, version/custom node inventory; do not replace graph/adapt Worker casually |
| Pinned file missing/hash mismatched | BLOCKED: MODEL_IDENTITY | Model installation owner; no downloading authorized here |
| Known history status error, output missing, or queue unresolved | BLOCKED: PROMPT_HISTORY / OUTPUT | G006 journal/history-first reconciliation; do not resubmit |
| 8188 idle, all model hashes match, but no GPU run | UNVERIFIED: REAL_COMFY_GPU | controlled first actual render after safety/permission |
| CUDA OOM, codec failure, history timeout | BLOCKED: LIVE_RENDER | preserve exact timestamps, logs, nvidia-smi, history; G006 decides bounded repair |
| Completed three WebMs without QA MP4/receipt | UNVERIFIED: FINAL_VIDEO | C011/C010A existing path; don't call raw WebMs released masters |

**GitHub handoff:** attach branch/PR link and this matrix to [Issue #91](https://github.com/jerryjwres-hue/picotoopet-v2.0/issues/91) for total controller/G006. No merge, rebase, tag, release, Comfy POST, model download or live GPU attempted.

### Dedicated Windows PowerShell 5.1 read-only contract CI (#91)

The separately owned test file `tests/Test-WanPowerShell51.Native.ps1` is run by
`.github/workflows/p0-wan-readonly-powershell51-native.yml` on an ephemeral
`windows-2022` GitHub-hosted runner using **Windows PowerShell 5.1**:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\docs\p0_wan_preflight\tests\Test-WanPowerShell51.Native.ps1
```

This is an **isolated mock contract**, not a live Comfy readiness result.
It invokes the actual unmodified API/manifest preflight entry point through
`powershell.exe -File`; a local `HttpListener` mimics only GET
`/system_stats`, `/object_info`, `/queue`, and bounded `/history`.
Tiny fake files test exact SHA256 checking. Ephemeral no-op executables expose
FFmpeg/libx264, ffprobe and NVIDIA inventory queries without model/GPU activity.

CI asserts all ten cases: offline 8188 BLOCKED, healthy passive snapshot
PASS_PASSIVE_ONLY (queue empty, retained history and known ID), missing SaveWEBM
BLOCKED, missing UNET model dropdown BLOCKED, missing VAE BLOCKED, missing
text encoder BLOCKED, tampered model SHA BLOCKED, ffmpeg/ffprobe missing BLOCKED,
nvidia-smi absent UNVERIFIED, and nvidia-smi returning nonnumeric/N/A VRAM
with exit 0 UNVERIFIED. It also rejects any method other than approved GETs,
asserts all input fixture file hashes are unchanged and asserts no production
folder was created by the preflight process. The harness creates its own mock
fixtures before inspection; **the preflight script never creates them**.

A native CI PASS verifies PowerShell 5.1 compatibility, classification, and
these offline no-side-effect contracts. It does **not** verify the user's real
Comfy 8188, real Wan/UMT5/VAE hashes, genuine model-loader options, actual
GPU/VRAM, local disk/electrical safety, persisted Core journal, the first
three WebMs, C011 QA master MP4, or human visual acceptance. Those remain
UNVERIFIED until individually inspected on an authorized, safe workstation.
No script option authorizes POST /prompt or starting any production process.
