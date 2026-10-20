# PicotooPet P0 #91 — Windows-only first real Wan shot acceptance packet

**Reference production integration SHA:** 0bac610e6bca1c9478fe439ad65f239efd12b107 (Draft PR #96, NOT a formal installer/release).  
**Gate as of 2026-10-20:** `LIVE_MAC_CORE=UNVERIFIED`; `OLLAMA_GPT_OSS_20B_RESIDENT=UNVERIFIED`; `REAL_COMFY_GPU=UNVERIFIED`; `ONE_SHOT_WEBM=UNVERIFIED`; `MAC_PRODUCTION_COMMIT=UNVERIFIED`; `WINDOWS_PLAYBACK=UNVERIFIED`. The native CI suite is already green; do **not** rerun it for this documentation change.

## 0. Electrical hard stop / authority boundary

**ONLY static source/CI inspection, or minimal passive GET/process/directory inspections on an *already safely powered* machine, are permitted now.** The user's Windows desktop recently experienced household breaker/AFCI trips. Do not energize an unsafe workstation for testing, start ComfyUI, load models, warm GPU, benchmark, render, run the app, deploy/install/update, restart a Windows service, reset breakers, or conduct repeated-trip tests. A qualified electrician must first investigate and confirm the relevant circuit/panel/power setup is safe under intended load, followed by explicit user approval for installation/start/render.

**Non-obvious unsafe launch:** `App.xaml.cs::OnStartup` calls `StartP0MediaWorker` on *ordinary WPF launch, even before pairing*. `Program.cs` handles `Picotoo Pet AI.exe --p0-media-worker` with no WPF. That worker polls pending journal then eligible Goals and can POST /prompt. **Do not launch the existing/new GUI or --p0-media-worker merely to “check readiness.”** Opening Goal Center is a **state-changing activation** in this build, not passive inspection. Normal window close-to-tray is not an executor stop. Sending a Goal can automatically produce GPU work. Comfy `/prompt`, Core `/claim`, `/attempt`, `/result`, `/cancel`, any resume/repair/verify installer command with write side effects are disallowed in this phase.

**Scope:** Windows is the user's sole interaction surface for future live use. No manual Mac terminal, Ollama preload, JSON copy, direct FFmpeg job, separate MediaWorker.exe, second database/scheduler, Task Scheduler or service install. Existing Mac verify scripts are **source references**, not instructions to run remotely. Never print/export Credential Manager secrets; do not scrape Ollama private Mac loopback.

## 1. Source-verified chain and operator entry (DEFERRED — only after electrician + explicit go-ahead)

1. Confirm approved **P0 developer preview build** is derived from SHA above and matching Mac Core/Worker code. `main` or an old installed app is **not** proof of this integration; official Release Builder remains blocked by true Maotai `torso_neutral.png` (#78). Do not install anything in this phase.
2. In the approved Windows WPF app, navigate to **Goal Center / 目标中心**, select **视频创意 (video.creative)** or **产品研究到视频 (product.research_to_video)**, depth **快速 (quick)** for first proof, and enter a bounded objective such as “围绕已有可追溯商品证据，生成一段无配音、无字幕的简短宠物产品展示视频；仅一个画面镜头.” Press **发送目标 →** exactly once. This is a *future state-changing action*. UI's `CreateGoalAsync` sends `HumanGoalCreateRequest(goal_type, objective, depth)` with a generated idempotency key; Mac Core defaults new video Goals to `local_video_preferred=true`. Previously persisted legacy Goals may use WebGPT handoff and must not be silently converted. Avoid **粘贴 Web GPT 返回**; it is the separate optional legacy/manual route.
3. Mac Core authenticates and durably creates Goal/Workflow: genuine discovery → local Ollama synthesis → `local.goal.creative` → existing Creative job/quality/CreativePackage (script + shot_plan.v1) → canonical ProductionJob and frozen `production.comfyui.v1` plan. UI shows Creative Package, actual shot-plan text, Creative/Production IDs and statuses. Never fabricate source findings or bypass Creative PASS.
4. **Hard single-shot gate:** read the exact `GET /api/v1/production/jobs/{id}/plan`; require `tasks.Count == 1`, `execution_disposition=Executable`, allowlisted `workflow_id=comfy.wan22.ti2v5b.t2v.v1`, and valid provenance before any permitted GPU work. The objective text **does not enforce** a single-shot plan. This build automatically dispatches eligible jobs; operators **cannot safely open WPF while an unreviewed job is ready** and assume it will wait for a one-shot approval. If this gating cannot be arranged safely using existing approved control/preview, mark `SINGLE_SHOT_CONTROL=BLOCKED`; do not “test anyway,” duplicate Goal, or add ad-hoc manual Comfy POST.
5. Same **Picotoo Pet AI.exe --p0-media-worker** serially runs `ProductionPendingRecovery.ReconcileAsync` **before** fresh Goal scan, acquires Core claim/lease and one-GPU exclusion, checks trusted Wan models/embedded workflow, reserves Core attempt, journals uncertain POST, submits once through `ComfyProductionClient` to `127.0.0.1:8188`, retrieves exact history, hashes output, commits result. GUI does not execute GPU.
6. **Stage 1** accepts a *genuine silent single-shot WebM* plus real Mac commit/provenance and Windows playable evidence. Do not invent a C010A final QA receipt for raw WebM. The WPF **打开最终视频** button belongs to the separate C004/C009/C010A/C011 **QA-approved MP4** path: the headless host produces the final candidate and durable PASS receipt; WPF only reopens a persisted approved projection, revalidates Core authority/media/receipt, then launches. Stage 2 three-shot/narration/captions MP4 is deferred.

Relevant code: `windows/desktop/src/PicotooPet.Desktop/{App.xaml.cs,Program.cs,Views/Pages/GoalCenterPanel.xaml,ViewModels/OperatorHomePageViewModel.cs,ViewModels/GoalVideoContinuationViewModel.cs,Services/P0MediaWorkerHost.cs,Services/ProductionExecutionService.cs,Services/PostProductionDeliveryCoordinator.cs,Services/VerifiedGoalDeliveryProjectionStore.cs}`; `src/picotoopet_core/autonomous/{goal_service,human_pipeline,local_creative,video_continuation}.py`; `src/picotoopet_core/{creative,production}/`.

## 2. Optional **read-only** Windows PowerShell preflight — do not run if PC should remain powered off

These commands **do not start Windows GUI/Comfy/Ollama, do not POST, write logs, claim leases, hash multi-GB model files, or create directories**. Use an already safely operating Windows terminal only; otherwise label all device facts UNVERIFIED and stop. Do not paste raw responses with secrets/content into public Issues.

### A. Existing Mac Core address and unauthenticated health (passive GET)

~~~powershell
$settingsPath = Join-Path $env:LOCALAPPDATA 'PicotooPetV2\Desktop\settings.json'
if (-not (Test-Path -LiteralPath $settingsPath -PathType Leaf)) {
  'MAC_SETTINGS=UNVERIFIED'; return
}
$settings = Get-Content -LiteralPath $settingsPath -Raw | ConvertFrom-Json
$uri = [uri]$settings.macBaseUrl
if ($uri.Scheme -ne 'http' -or $uri.Host -in @('0.0.0.0','127.0.0.1','localhost')) {
  'MAC_ADDRESS=REVIEW_REQUIRED'; return
}
try {
  $h = Invoke-RestMethod -Method Get -Uri ($uri.AbsoluteUri.TrimEnd('/') + '/api/v1/health') -TimeoutSec 4
  if ($h.status -eq 'ok' -and $h.database -eq 'ok') { 'MAC_CORE_HEALTH=PASS' }
  else { 'MAC_CORE_HEALTH=BLOCKED' }
} catch { 'MAC_CORE_HEALTH=UNVERIFIED' }
~~~

An OK health reply proves only **reachable Core plus database SELECT**, not authenticated pairing, model presence, Worker online or task execution. Authenticated `GET /api/v1/status`, `/workers/status`, `/autonomous/goals`, `/creative/jobs` and `/production/jobs` require the existing paired client/Bearer token. There is **no approved token-free PowerShell substitute**: do not export/extract tokens from Windows Credential Manager for convenience. Record `MAC_AUTH=UNVERIFIED` until authorised, existing UI/client observations are possible in the future deployment window. If the PC is not already safe, do not execute even this GET.

### B. Existing Comfy endpoint/queue, without POST or model activation

~~~powershell
$comfy = 'http://127.0.0.1:8188'
try {
  $object = Invoke-RestMethod -Method Get -Uri "$comfy/object_info" -TimeoutSec 5
  $nodes = @('UNETLoader','CLIPLoader','VAELoader','ModelSamplingSD3',
             'CLIPTextEncode','Wan22ImageToVideoLatent','KSampler',
             'VAEDecode','SaveWEBM','LoadImage')
  $missing = @($nodes | Where-Object { $_ -notin @($object.PSObject.Properties.Name) })
  if ($missing.Count -eq 0) { 'COMFY_NATIVE_NODES=PASS' }
  else { 'COMFY_NATIVE_NODES=BLOCKED' }
} catch { 'COMFY_LOOPBACK=UNVERIFIED' }

try {
  $queue = Invoke-RestMethod -Method Get -Uri "$comfy/queue" -TimeoutSec 5
  $running = @($queue.queue_running).Count
  $pending = @($queue.queue_pending).Count
  "COMFY_QUEUE_RUNNING_COUNT=$running"
  "COMFY_QUEUE_PENDING_COUNT=$pending"
  if ($running -gt 0 -or $pending -gt 0) { 'NEW_GPU_WORK=BLOCKED' }
} catch { 'COMFY_QUEUE=UNVERIFIED' }
~~~

Only `GET /object_info` and `GET /queue`; **no `POST /prompt`, `GET /view` large media, Comfy GUI launch, or warming GPU**. Node list alone does not prove models loaded/valid or model SHA. Comfy is **strict loopback** at `127.0.0.1:8188`, not the Mac Core host or LAN proxy. Preflight must report missing `SaveWEBM` as BLOCKED.

### C. Passive local inventory, disk and independent worker deduplication

~~~powershell
# Process args are inspected in memory; do NOT display the full command line.
$procs = @(Get-CimInstance Win32_Process |
  Where-Object { $_.Name -eq 'Picotoo Pet AI.exe' })
$workers = @($procs | Where-Object { $_.CommandLine -match '--p0-media-worker' })
"WINDOWS_MEDIA_WORKER_COUNT=$($workers.Count)"
if ($workers.Count -gt 1) { 'WORKER_DUPLICATE=BLOCKED' }
elseif ($workers.Count -eq 1) { 'WORKER_PROCESS=OBSERVED_NOT_PROOF_OF_IDLE' }
else { 'WORKER_PROCESS=NOT_RUNNING' }

# Static pinned model presence only (NO Get-FileHash of multi-GB models now).
$modelRoot = 'E:\PicotooPet\Models'
$needed = @('diffusion_models\wan2.2_ti2v_5B_fp16.safetensors',
  'text_encoders\umt5_xxl_fp8_e4m3fn_scaled.safetensors',
  'vae\wan2.2_vae.safetensors')
foreach ($relative in $needed) {
  if (Test-Path -LiteralPath (Join-Path $modelRoot $relative) -PathType Leaf) {
    'PINNED_MODEL_FILE=FOUND'
  } else { 'PINNED_MODEL_FILE=MISSING' }
}
$drive = Get-PSDrive -Name E -ErrorAction SilentlyContinue
if ($drive) { "MODEL_DRIVE_FREE_GB=$([math]::Round($drive.Free/1GB,1))" }
else { 'MODEL_DRIVE_FREE_GB=UNVERIFIED' }

# Inspect journal metadata without invoking Pending() (which prunes Settled entries).
$journalDir = Join-Path $env:LOCALAPPDATA 'PicotooPetV2\MediaWorker\v1'
if (Test-Path -LiteralPath $journalDir -PathType Container) {
  $files = @(Get-ChildItem -LiteralPath $journalDir -File -Filter '*.submission.json')
  "MEDIA_JOURNAL_FILE_COUNT=$($files.Count)"
  $unknown = 0
  foreach ($f in $files) {
    try {
      if ($f.Length -gt 16384 -or $f.Length -le 0) { $unknown++; continue }
      $s = Get-Content -LiteralPath $f.FullName -Raw | ConvertFrom-Json
      if ($s.Phase -ne 'Settled') { $unknown++ }
    } catch { $unknown++ }
  }
  "MEDIA_JOURNAL_UNSETTLED_OR_INVALID=$unknown"
  if ($unknown -ne 0) { 'NEW_GPU_WORK=BLOCKED_PENDING_RECONCILIATION' }
} else { 'MEDIA_JOURNAL=NOT_FOUND_NOT_PROOF_OF_CLEAR' }
~~~

`windows/bootstrap/model_manifest.json` pins three model filenames and SHA256 under `E:\PicotooPet\Models`; the actual embedded manifest and `ProductionExecutionService.PreflightAsync` require exact hashes and native nodes. **This passive presence check is not that preflight PASS**. Note that `ProductionExecutionService.PreflightAsync` can create input/output directories and read/rehash huge files, so **do not invoke it for the current strictly read-only electrical phase**. Check the actual configured Comfy data root from `ProductionLocalEnvironment.ResolveComfyDataRoot` once deployment is approved (possible existing config under `%APPDATA%\ComfyUI\config.json`; also fixed known roots). Logs: `%LOCALAPPDATA%\PicotooPetV2\Desktop\logs\media-worker.log` and `desktop.log`. Reading excerpts is passive but logs may contain project data; never publish raw logs.

### D. Mac Ollama `gpt-oss:20b` — precise evidence gate, no manual Mac input

Mac's `OllamaClient` uses **Mac-local loopback** `127.0.0.1:11434`, `GET /api/tags` for installed, `GET /api/ps` for actually loaded, and the `ResidentManager` may invoke a **model preload** when requested. Never contact the Mac's loopback API through a new tunnel, bind it to LAN, use `ollama run`, preload, or run `VERIFY_GOAL_CENTER_E2E.command` on the Mac in this phase.

In future approved deployment, read authenticated Mac Core `GET /api/v1/workers/status` and `GET /api/v1/status` using existing paired client and compare supported task types to `autonomous.discovery.v1`, `autonomous.goal_synthesis.v1`, and `autonomous.goal_creative.v1`. Existing `deploy/macos/phase23-worker/VERIFY_GOAL_CENTER_E2E.command` checks the **older** discovery/synthesis/handoff chain, not necessarily the new local Creative/Production path; a PASS there alone is insufficient. Worker `online` or synthesis capability **is not evidence of actual loaded gpt-oss:20b**. Require an already exposed, nonsecret Mac-side `/api/ps` observation or verified resident-model status explicitly naming `gpt-oss:20b`; otherwise `OLLAMA_GPT_OSS_20B_RESIDENT=UNVERIFIED`. No Mac manual action is part of the user journey. Running real local synthesis later will be distinct actual inference proof, not a current read-only check.

## 3. Deferred exact-ID task and media evidence collection (only after written clearance)

At the authorized live gate, capture **actual** identifiers from authenticated Core via existing Windows client/Goal UI; do not invent IDs, replay random POST, or send credentials to external diagnostics.

Read-only authenticated endpoints after an authorized Goal exists:

- `GET /api/v1/autonomous/goals/{goal_id}`; `GET /api/v1/autonomous/goals/{goal_id}/handoff/video-return` → `creative_job_id`, `creative_package_id`, `creative_package_digest`, `production_job_id`, mode. A `404` while local workflow is still creating is not a synthetic WebGPT return.
- `GET /api/v1/creative/jobs/{creative_job_id}` and `/package` → Creative `creative_ready`, package digest, `stage_results.script.v1`, `stage_results.shot_plan.v1`, source evidence/provenance. Compare exact package IDs/hashes. Absence or failed quality gate = BLOCKED.
- `GET /api/v1/production/jobs/{production_job_id}`, `/plan`, `/package` (GET only) → immutable `plan_digest`, exactly one Executable T2V task, `production_ready` and stored `ProductionPackage.manifest.outputs[0]`. The Core **production result commit** is the Mac durable task receipt; it includes `production_task_id`, `comfy_prompt_id`, `output_relpath`, `output_sha256`, `output_bytes`, `mime_type=video/webm`, `fps`, `frame_count`, source/plan identity. A **C010A PASS receipt** is a separate final MP4 QA artifact, not interchangeable with the raw WebM Core commit.
- Fixed Windows Comfy **GET** `http://127.0.0.1:8188/history/{actual_prompt_id}`, where ID came from the Core-bound output/journal, and `GET /queue`; confirm matching `prompt_id`, completed successful execution, output file name/subfolder under the trusted Comfy `output` root and no still-running matching job. Never infer `prompt_id` from order or filename alone, and never use `GET /history` as proof if item is absent or error.
- For a real file **after safety clearance**, ensure the manifest `output_relpath` resolves to one ordinary non-reparse file **under trusted Comfy output root**, no traversal, >0 bytes. Compute `(Get-Item -LiteralPath $webm).Length` and `(Get-FileHash -LiteralPath $webm -Algorithm SHA256).Hash.ToLowerInvariant()`; compare both with Core immutable manifest. If already installed, use `ffprobe -v error -show_entries format=duration,format_name:stream=index,codec_type,codec_name,width,height -of json -- $webm` (read-only tool, but do not install now). Open the exact WebM with an already installed Windows player; take screenshot/video with file name or task identifier visible **without displaying tokens/user-sensitive text**. The final MP4 WPF “打开最终视频” is allowed only after C010A/C011 QA PASS and revalidation of durable `%LOCALAPPDATA%\PicotooPet\PostProduction\VerifiedGoals\v1` index and C010 receipt. Do not weaken QA merely to open WebM through the MP4 button.

Suggested nonsecret evidence schema (populate with real facts, every missing value explicitly `UNVERIFIED`):

~~~text
candidate_sha: 0bac610e6bca1c9478fe439ad65f239efd12b107
goal_id: UNVERIFIED
workflow_id: UNVERIFIED
creative_job_id: UNVERIFIED
creative_package_id / digest / source_set_digest: UNVERIFIED
production_job_id / plan_digest / production_task_id: UNVERIFIED
core_attempt_number / core_bound_comfy_prompt_id: UNVERIFIED
comfy_history_prompt_id / completed_state: UNVERIFIED
webm_managed_path / bytes / sha256 / codec / duration: UNVERIFIED
mac_production_package_id / manifest_digest / committed_output: UNVERIFIED
windows_player_open_evidence: UNVERIFIED
final_c010a_receipt_digest / c011_approved_open: NOT_REQUIRED_FOR_STAGE1_WEBM
electrical_clearance: BLOCKED
user_render_authorization: NOT_GRANTED
LIVE_MAC_CORE: UNVERIFIED
REAL_COMFY_GPU: UNVERIFIED
~~~

A screenshot of a fake API test, CI fixture, mock HTTP `/prompt`, empty placeholder file, or manually constructed Core package is NOT a real two-host PASS. Preserve immutable receipts and native Windows file hashes; never publish sensitive prompt contents or authentication tokens.

## 4. Stop, restart, unknown submission and power-failure playbook

- **Right now:** do not start GUI/worker/render. Read-only inspect existing `queue`, process list and journal if power is already safe. If any `Prepared`, `Submitting`, `Submitted`, `FailurePending`, malformed journal, Core/Comfy disagreement or still-running Comfy queue is found, classify `GPU_RESTART=BLOCKED_PENDING_RECONCILIATION`. Never delete/rename a journal, force clear locks, reset attempt budget or re-POST /prompt to “see what happens.”
- **Normal future UI close/minimize:** WPF observer closes or goes to tray; background media worker remains running. It is **not** a stop/rollback. A deliberate **Exit / 退出** emits cooperative `Local\PicotooPetV2.P0MediaWorker.ExplicitExit`, and host finishes a started GPU call before exiting. Do not confuse this with GPU emergency stop. For a running prompt, first observe queue; do not kill active process to simulate recovery, cancel Core independently or shut off breakers.
- **Unexpected outage:** do not cycle breaker or re-energize merely to test. Preserve Windows `%LOCALAPPDATA%\PicotooPetV2\MediaWorker\v1\*.submission.json` and Mac Core durable data, with no manual edits. After electrician safety clearance and explicit permission, **first GET** Comfy `/queue` and `/history/{known_id}`, inspect Core job/plan/package and exact journal. Run the existing same-EXE host only when restart is authorized. Its `ProductionPendingRecovery.ReconcileAsync` runs before new dispatch; known bound attempt-2 with expired Core lease can recover via exact history + commit, and Core blocks attempt 3. Unknown/unbound POST must stop in `MEDIA_SUBMISSION_UNKNOWN` / `MEDIA_PENDING_RECONCILIATION` until evidence resolves; terminal canceled/failed job still waits for Comfy to finish before releasing fresh GPU work.
- `POST /api/v1/production/jobs/{id}/cancel` is **state-changing** and does not prove a GPU prompt stopped; do not issue it as a power-failure shortcut. No ad-hoc Comfy interrupt/queue delete, manual GPU re-submission, scheduler/service activation, or emergency circuit intervention. If irreconcilable, record exact sanitized failure code, stop further GPU work, and request a separate reviewed recovery decision.

## 5. Operational gate (no user device touched)

| Gate | Current assessment | Evidence / next condition |
| --- | --- | --- |
| Source integration & same-EXE recovery | READY (CI only) | Exact SHA 0bac610e; existing Mac Core+Worker, Windows Control Center, P0 Worker and C011 scoped CI all PASS |
| Legitimate preview install provenance | BLOCKED | Formal Release Builder fails missing Maotai torso_neutral.png; no official release claim |
| Electrical safety & explicit deploy/render permission | BLOCKED | Qualified electrician clearance under intended load plus user's specific authorization |
| Actual Mac Core auth and Worker state | UNVERIFIED | Authenticated, exact-sha deployed Core and Windows paired-client read-only records |
| Mac gpt-oss:20b installed, loaded, real creative execution | UNVERIFIED | Legitimate local residency and real CreativePackage provenance |
| Wan nodes, pinned models SHA, Comfy loopback and disk | UNVERIFIED | Passive inventory now if safe; complete model hash & readiness only later |
| Worker no pending unknown POST, exactly one executable shot | UNVERIFIED | Exact-ID status, journal/queue clear and 1-task frozen ProductionPlan before launch |
| Real one-shot prompt/history/WebM/hash + Mac commit | UNVERIFIED | Future **one** user-approved production run, no mocks |
| WebM actual Windows playback | UNVERIFIED | Actual player evidence and matching file hash, after clearance |
| Final MP4 QA PASS, C011 UI Open | DEFERRED | Stage 2, not a prerequisite for Stage 1 raw WebM |

**Do not rerun native CI or official Full Release Builder for this document-only handoff.** Draft PR #96 only; no merge/rebase/tag/release, no Mac terminal work, no user-device mutation, and do not call a passive availability check a production success.
