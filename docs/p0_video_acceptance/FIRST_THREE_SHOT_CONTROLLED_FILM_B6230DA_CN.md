# PicotooPet P0 #91 — 首条真实三镜头 T2V 受控双机验收（operator v1）

> **冻结候选**：Draft PR #117，`b6230da62eb803e9a7be840374feeb481a657c3a`。本文是**操作规程，不是实机通过报告**。本文分支仅含本文件；不覆盖 #117、#115、Creative、预览发布或 C011。任何现场事实尚未实测均填 `UNVERIFIED`。
>
> **安全硬前提**：未完成电路/负载安全确认、用户设备与实际 GPU 提交授权、匹配候选部署预检时，不启动用户 Mac、Windows GUI、Ollama、Comfy、Wan 或 GPU。禁止为“测试一下”关闭/反复复位跳闸回路、改配电箱、模型下载、合成伪造视频或人工直接 POST Comfy。

## 0. 冻结来源、工件与不同窗口交接

- 原生 CI 同 SHA：Mac Core `39537234608`、Mac Worker `39537234530`、P0 Same EXE/独立 28-case `39537234564`、C011 `39537234528`、Windows Control Center `39537234648`、Reference Preview `39537234681` 均 SUCCESS。
- **对应 SHA 的** Windows portable Developer Preview：GitHub Actions [Run 39537229111](https://github.com/jerryjwres-hue/picotoopet-v2.0/actions/runs/39537229111)，artifact ID `12318028230`，名称 `PicotooPet-P0-ThreeShot-DeveloperPreview`。内部 ZIP 名称以实际工件为准；原生日志 `P0_PREVIEW_PORTABLE_BUILD=PASS; SOURCE_SHA=b6230da62eb803e9a7be840374feeb481a657c3a; ZIP_SHA256=8066cda29dab81b6183e01633a1b6c650b908b4f0b0a6c091d5f7753f2273f16`。人工比对 ZIP hash、`preview-manifest.json` 的 `source_sha` 和每文件哈希、`product-version.txt`；签名/正式发行不在该工件范围。
- 正式 Release `39537234653` 的 Maotai 独立资产 gate FAILED；**不绕过** `torso_neutral.png`，且不把 portable preview 当成正式安装包。
- G-Mac-preflight 负责 Mac 8766/LaunchAgent/Ollama `gpt-oss:20b`/SQLite/Outbox/认证 LAN 的*设备前静态清单*；G-Wan-preflight 负责 Comfy 8188/SaveWEBM/Wan pinned model、历史输出/FFmpeg/显卡计时的*设备前静态清单*。各自文件/报告尚未进入本冻结 SHA 时标为 **PENDING HANDOFF**，不得冒充现场 PASS；本规程只定义跨机共同交接字段，不重复制作这两组预检脚本。
- 现存旧单镜头说明 `docs/p0_video_acceptance/STAGE1_WINDOWS_ONLY_SINGLE_SHOT.md` 仍是参考，**不可**沿用其“仅一条 Task 即放行”的验收标准。

## 1. 真实业务与执行入口：唯一自动链路

1. **Windows GUI** `Views/Pages/GoalCenterPanel.xaml` → `ViewModels/OperatorHomePageViewModel.cs` 的“生成 AI 视频方案”选择 `goal_type=video.creative` 和 `depth=quick`；目标文本写清**恰好三个镜头、纯文字生成视频、不用参考图/旁白/字幕**。建议在真实 Goal 目标内使用明确英文约束：`Exactly 3 shots, text-to-video only; same pet, same product, three distinct physical actions.`，再补可审核的主体、产品、场景、动作描述。此处是*输入建议*，不是绕过质量门的保证。
2. `ControlCenterSession.Goals.cs::CreateGoalAsync` → `MacCoreClient` `POST /api/v1/autonomous/goals`；Core `autonomous/goal_service.py::HumanGoalRequest` 默认 `local_video_preferred=true`，`human_pipeline.py` 的 `local-creative` workflow 在真实 Discovery / Synthesis 完成后生成本地 Creative；不得人为粘贴 WebGPT 伪返回。
3. Mac Worker `autonomous/local_creative.py::GoalLocalCreativeCoordinator.handler` 从真实有来源的 discovery/synthesis 读取 `evidence_ids` 和 source hashes，创建 Creative job；`creative/service.py` 冻结 package，Core `production/service.py` 创建规范 `Production Job + Plan + plan_digest`。是否形成**恰好三条可执行 T2V**需下节只读核实，创意质量拒绝/延期不是放行理由。
4. Windows `App.xaml.cs::StartP0MediaWorker` 启动**同 EXE** `--p0-media-worker`；`Services/P0MediaWorkerHost.cs::RunAsync` 用独立 Session 遍历 Core Goal/continuation，但首先 `ProductionPendingRecovery.ReconcileAsync`，有未决 Journal 就不调度新 Goal。
5. `Services/P0ThreeShotAcceptanceGate.cs::AllowsJobAsync` 对**指定 Job ID + 精确 64 位 digest**验明三条 `Executable`、`GENERATIVE_VIDEO`、`comfy.wan22.ti2v5b.t2v.v1`、顺序 1/2/3、唯一且非空白的 `shot_id`/`production_task_id`、无 reference/trusted input、Core 冻结包与计划一致。Core claim 及每个新 Comfy POST 再通过文件许可复核。
6. `Services/ProductionExecutionService.cs::RunAsync/ExecuteTaskAsync` 使用已有 Journal、Core lease、固定本机 `ComfyProductionClient.Create()` (`http://127.0.0.1:8188`)；在 `POST /prompt` 获 `prompt_id`，随后只读 `GET /history/{prompt_id}` 查 `SaveWEBM` output。按顺序生成 **WebM × 3**，各自计算 SHA256 并通过 `POST /production/jobs/{job}/tasks/{task}/result` 回写 Core。**操作者不代替执行器调用这些写端点**。
7. Mac Core 三个 Task 成功后创建 `ProductionPackage`（`quality_outcome=PASS`）和 `production_ready`；Worker 的 `FinalVideoDelivery.Observe` 接原有 C004 固定 FFmpeg 多输入 concat → 不需要的旁白/字幕走原有 fallback → C010A QA 与 C011 authority → `VerifiedGoalDeliveryProjectionStore` 只在 PASS receipt 后写索引。GUI `PostProductionDeliveryCoordinator.OpenCurrentAsync` 在“打开最终视频”点击时**再次**检查 Core、文件 SHA、receipt、C011 选择绑定，不重新渲染。

## 2. API 真正契约，不用猜出来的 JSON/地址

**统一前缀** `/api/v1`（服务路由在 `api/routes/*.py` 下定义；Windows 客户端也使用该前缀）。Production/Creative/Goal API 均在 `require_auth` 之下：请求头 `Authorization: Bearer <已配对设备 token>`；服务端 `security/auth.py` 恒时比较。Windows 客户端从既有配对 Session 凭据仓库拿令牌；**不要为排查而提取或公开 Credential Manager/token/数据库秘密**。

| 目的 | 只读方法与原样路径 | JSON 的实际字段/归属 |
|---|---|---|
| Goal 细节 | `GET /api/v1/autonomous/goals/{goal_id}` | `goal_id,workflow_id,intent_type,constraints,status,objective` |
| 本地链路 | `GET /api/v1/autonomous/goals/{goal_id}/handoff/video-return` | `goal_id,continuation_mode,creative_job_id,creative_package_id,creative_package_digest,creative_status,production_job_id,production_status,handoff_sha256,return_sha256`。本地 Creative 尚未生成时可能 404；**不要**当成必须贴 WebGPT |
| Creative | `GET /api/v1/creative/jobs/{creative_job_id}`、`/package` | Creative Job 与 PASS package；审核真实镜头来源、场景动作、三镜头可执行性 |
| Job | `GET /api/v1/production/jobs/{production_job_id}` | `production_job_id,creative_package_id,creative_package_digest,project_key,production_profile,plan_digest,status,lease_executor_id,lease_expires_at,...` |
| 完整 Plan | `GET /api/v1/production/jobs/{production_job_id}/plan` | `schema_version,production_profile,production_job_id,creative_package_id,creative_package_digest,project_key,output_profile_id,target_runtime_ms,tasks[]`。每个 Task: `production_task_id,shot_id,order,render_intent,execution_disposition,workflow_id,positive_prompt,negative_prompt_policy_id,seed,width,height,fps,frame_count,target_duration_ms,trusted_input_asset_ref`；v1.1 才有额外引用字段 |
| Core 产物 | `GET /api/v1/production/jobs/{production_job_id}/package` | 最外层 `production_package_id,production_job_id,creative_package_id,plan_digest,package_digest,package_relpath,quality_outcome,manifest,created_at`；`manifest.outputs[]` 的实际字段见 §6 |

创建 Goal 的后端 schema 是 `goal_type,objective,depth,local_video_preferred`；**唯一已验证的创建路径** `POST /api/v1/autonomous/goals`，**另需** `Idempotency-Key` 请求头。UI 已使用此路径；本次验收**只通过 GUI 创建**，不发重复 POST。Plan Digest **只采信 Core Job 的 `plan_digest`**；不要拿 PowerShell `ConvertTo-Json`/任意空格排序自算冒充 Canonical SHA：门禁会自行对实际 Plan 按既有 `CanonicalJson` 计算并对比。无权读取认证 API 时标记 `MAC_AUTH=UNVERIFIED`，**不得猜 token、Job ID 或 digest 并 ALLOW**。

## 3. 严格 HOLD-first（即使 GUI 自动启动 Worker）

**执行许可条件**：用户 Windows 当前无正在进行的提交、机器电气安全且已授权上机，且已下载验证上述同 SHA 预览。**先关闭所有同用户运行中的 `Picotoo Pet AI.exe` GUI/worker，再做下一步**。正式开机测试前必须在**未来获准的目标 Windows 上**，与未来 GUI **同一 Windows 账户**执行工件所带脚本：

```powershell
# 未来经用户授权在自己的 Windows 上执行；现在不得执行。
& ".\Prepare-P0ThreeShotHold.ps1"
# 必须得到：P0_HOLD_PREPARED=PASS
```

它只原子写 `%LOCALAPPDATA%\PicotooPetV2\MediaWorker\v1\three-shot-acceptance.json`：
```json
{"schema_version":"1.0","mode":"hold"}
```

Worker 的 `P0ThreeShotAcceptanceGate.OpenGate` 第一次观察配置时持久创建同路径 `three-shot-acceptance.json.armed`。**验明 Worker 已观察后该 marker 存在**；不存在时继续保持 HOLD 排查，不进入 ALLOW。已 armed 后 config 被删除/损坏，Worker 仍 fail-closed；**永不删除 .armed 来“恢复默认”**。新机从未存在配置且未 armed 时仍沿用旧 unattended 设计，因此**必须 HOLD 在 GUI/Worker 之前**。

此后才可在有电气安全与机器授权的 Windows 环境启动预览程序并连接 Mac Core。HOLD 下可让 Mac 继续 Goal/Creative，不能发新增 GPU POST。必要检查已有 Journal 中是否存在非 `Settled` submission（参 §4），旧历史未知不能用人工删 JSON 解锁。

## 4. 冻结三镜头的只读审核：必须在 ALLOW 之前

从实际 Goal 页面/已配对认证客户端取得真实 `goal_id`，读取 continuation 得实际 `production_job_id`，查询 Job + Plan（无需 POST /claim）。**不能用“列表第一个”或旧运行样例猜 Job**。

审核逐项：

- `goal.intent_type = video.creative`（或用户明确选的 `product.research_to_video`），`constraints.local_video_preferred = true`，`continuation.continuation_mode = local`；Creative package 不为 null、来源链/质量 PASS。
- `job.production_job_id == continuation.production_job_id == plan.production_job_id`，`job.plan_digest` 是小写 64 位 hex，`job.production_profile == plan.production_profile == production.comfyui.v1`；`job.creative_package_id/digest` 与 Plan 一致；`plan.schema_version=1.0`。
- `plan.tasks.length=3`；`order=1,2,3`；全部 `execution_disposition=Executable`、`render_intent=GENERATIVE_VIDEO`、`workflow_id=comfy.wan22.ti2v5b.t2v.v1`，`trusted_input_asset_ref=null`，无 `reference_asset`；`shot_id`/`production_task_id` 均非空白且分别唯一；`positive_prompt` 包含同一个宠物/产品/场景连续性并有三项不同的物理动作。不要把 C010A/C011 误当成 Task/Shot ID。
- 与源 package 核验时长、帧数、分辨率、种子和关键动作；若质量门拒绝、`NeedsHuman`、I2V、缺来源、Job 非 Ready/Claimed 或 digest 不一致：维持 HOLD，交 Creative 负责人处理真实原因，不修改/伪造 Plan。
- `%LOCALAPPDATA%\PicotooPetV2\MediaWorker\v1\*.submission.json` 是既有提交 Journal，字段大小写依 `ProductionSubmission` 为 `JobId,TaskId,PlanDigest,GraphDigest,Phase,PromptId,FailureCode`。只读清点非 `Settled` 或无法解析文件；已知 prompt 要先找本机 Comfy history + Core 对账；**未知提交不准放行新 Job**。此处读取日志不能替代 Worker 的原生 `ReconcileAsync`。

若用户明确提供了经授权的 Mac Core Bearer 凭据，可在未来操作窗口使用**只读** PowerShell，令牌手动输入而非从 Credential Manager 导出；不保存/打印原始响应到 GitHub：

```powershell
# 未来经设备/电气许可使用；$base 必须从实际已配对 Mac Core 地址确认。
$base = "http://<实际 Mac LAN 地址>:8766"
$secret = Read-Host "Enter already-authorized Mac Core Bearer token" -AsSecureString
$ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secret)
try { $token = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
$auth = @{ Authorization = "Bearer $token" }
# $goalId 从真实 Goal 页面取得，不构造随机值：
$goal = Invoke-RestMethod -Method Get -Uri "$base/api/v1/autonomous/goals/$goalId" -Headers $auth
$link = Invoke-RestMethod -Method Get -Uri "$base/api/v1/autonomous/goals/$goalId/handoff/video-return" -Headers $auth
$jobId = $link.production_job_id
$job = Invoke-RestMethod -Method Get -Uri "$base/api/v1/production/jobs/$jobId" -Headers $auth
$plan = Invoke-RestMethod -Method Get -Uri "$base/api/v1/production/jobs/$jobId/plan" -Headers $auth
# 仅展示不含 token 的简化字段；先人工检查完整计划及三个真实 prompt。
[pscustomobject]@{Goal=$goal.goal_id; Job=$job.production_job_id; Digest=$job.plan_digest; Schema=$plan.schema_version; Tasks=@($plan.tasks).Count}
$plan.tasks | Select-Object order,shot_id,production_task_id,render_intent,execution_disposition,workflow_id
Remove-Variable token,auth -ErrorAction SilentlyContinue
```

`$goalId` 必须先赋**实际** ID，否则代码故意不完整，禁止调用；`$base` 占位符不是可运行 IP。凭据仅在允许的现场会话中输入；若认证失败，不用此脚本继续。

## 5. 指定 Job ALLOW / 重新 HOLD / Journal 优先级

**只有** §3–4 每项确认、旧 Journal 对账清晰、Comfy/FFmpeg/模型/磁盘/队列/负载通过 G-Wan/G-Mac 交接，且用户另行明确授权**真实 GPU 提交**时才可放行。读取的 `job.production_job_id` 必须为规范**小写 UUID D**，`job.plan_digest` 必须为**小写** 64 hex。将同一用户 `three-shot-acceptance.json` **原子替换**为以下精确四键 JSON（不能增加审计字段进门禁配置）：

```json
{"schema_version":"1.0","mode":"allow","production_job_id":"<由实际认证 Core Job 取得的小写 UUID>","plan_digest":"<由实际认证 Core Job 取得的小写 64 位 hex>"}
```

以下代码仅供**已授权现场用户**执行；只有在§4审核、Mac/Wan预检、电气与GPU授权全部明确通过后才允许运行。变量 `$job` 与 `$plan` 必须来自上节同一次真实认证只读 GET；这一步会允许后台 Worker 发新 GPU POST，绝不可在当前源码审查阶段执行：

```powershell
# DANGER: permits GPU work. Run ONLY after explicit user + electrical clearance.
$jobId = [string]$job.production_job_id
$digest = [string]$job.plan_digest
$tasks = @($plan.tasks)
if ($jobId -cnotmatch '^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$' -or
    $digest -cnotmatch '^[0-9a-f]{64}$' -or $jobId -cne $plan.production_job_id -or
    $job.plan_digest -cne $digest -or $plan.schema_version -cne '1.0' -or
    $plan.production_profile -cne 'production.comfyui.v1' -or
    $job.production_profile -cne $plan.production_profile -or
    $job.creative_package_id -cne $plan.creative_package_id -or
    $job.creative_package_digest -cne $plan.creative_package_digest -or
    $job.project_key -cne $plan.project_key -or $tasks.Count -ne 3) {
    throw 'P0_ALLOW_IDENTITY_INVALID'
}
for ($i=0; $i -lt 3; $i++) {
    $t = $tasks[$i]
    if ($t.order -ne ($i+1) -or [string]::IsNullOrWhiteSpace($t.shot_id) -or
        [string]::IsNullOrWhiteSpace($t.production_task_id) -or
        $t.render_intent -cne 'GENERATIVE_VIDEO' -or
        $t.execution_disposition -cne 'Executable' -or
        $t.workflow_id -cne 'comfy.wan22.ti2v5b.t2v.v1' -or
        $null -ne $t.trusted_input_asset_ref -or $null -ne $t.reference_asset) {
        throw 'P0_ALLOW_T2V_PLAN_INVALID'
    }
}
if (@($tasks | Select-Object -ExpandProperty shot_id -Unique).Count -ne 3 -or
    @($tasks | Select-Object -ExpandProperty production_task_id -Unique).Count -ne 3) {
    throw 'P0_ALLOW_DUPLICATE_ID'
}
$root = Join-Path $env:LOCALAPPDATA 'PicotooPetV2\MediaWorker\v1'
$path = Join-Path $root 'three-shot-acceptance.json'
if (-not (Test-Path -LiteralPath $path -PathType Leaf) -or
    -not (Test-Path -LiteralPath "$path.armed" -PathType Leaf)) {
    throw 'P0_ALLOW_HOLD_NOT_ARMED'
}
$old = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
if ($old.schema_version -cne '1.0' -or $old.mode -cne 'hold') {
    throw 'P0_ALLOW_NOT_STARTING_HOLD'
}
$json = [ordered]@{
  schema_version='1.0'; mode='allow'
  production_job_id=$jobId; plan_digest=$digest
} | ConvertTo-Json -Compress
$tmp = Join-Path $root ("three-shot-acceptance." + [Guid]::NewGuid().ToString('N') + '.tmp')
try {
    [IO.File]::WriteAllText($tmp, $json, [Text.UTF8Encoding]::new($false))
    [IO.File]::Replace($tmp, $path, $null)
} finally {
    if ([IO.File]::Exists($tmp)) { [IO.File]::Delete($tmp) }
}
$check = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
if ($check.mode -cne 'allow' -or $check.production_job_id -cne $jobId -or
    $check.plan_digest -cne $digest) { throw 'P0_ALLOW_VERIFY_FAILED' }
"P0_ALLOW_EXACT_JOB=$jobId"
```

**仍需**人工核实 Creative prompt 来源和旧 Journal；此代码不是质量审核的替代。若原子替换遇在用句柄失败，不强杀 Worker、不删除 .armed，重新进入 HOLD 复核。Worker 调度周期 15 秒，单 Job ALLOW 不改变 Journal 优先级；未知 POST 不能人工清除后强行重投。

出现任何异常或希望暂停**新的** GPU 工作时，安全原子写回 `{"schema_version":"1.0","mode":"hold"}`。HOLD 防止**新 claim/attempt/POST**；**不会取消已经提交且正在运行的 Comfy prompt**，也不能承诺瞬间降低 GPU 或电路负载。若正在高负载渲染或出现电气危险，按现场设备与专业电气安全方案处理，不能依赖 HOLD 作为急停。保存 Core/Journal/Comfy history 原证据，不手工删除或编辑 submission 以强行重投。

## 6. 三 WebM、历史、GPU/费用与 QA/MP4 证据的**准确读取入口**

1. **Core 权威成功记录**：只读 `GET /api/v1/production/jobs/{job_id}/package`。`quality_outcome=PASS` 且 `manifest.outputs` **恰为 3**，按 `order` 1→3 逐项读取实际 `production_task_id,shot_id,workflow_id,comfy_prompt_id,output_relpath,output_sha256,output_bytes,mime_type,width,height,frame_count,fps`。这来自 `production/package.py::build_production_package_payload`，不是猜测的 JSON。核对 `package.plan_digest == job.plan_digest`，输出 `mime_type=video/webm`，三项 ID/文件/哈希真实且不同。
2. **Comfy history**：只在目标 Windows loopback 上，对 Core 返回的每一个实际 `comfy_prompt_id` 做只读 `GET http://127.0.0.1:8188/history/{prompt_id}`，检查同一键 `status.completed=true` 且无 `status.status_str=error`，在 `outputs` 的 SaveWEBM 输出里核对 `filename`、`subfolder`、`type=output`。另 `GET /queue` 核对已无该 Job 对应的在途执行；不要用空 history 猜成功，不要直接 `POST /prompt`。
3. **WebM 实体**：`ProductionLocalEnvironment.ResolveComfyDataRoot()` 按 `%APPDATA%\ComfyUI\config.json` `basePath`、固定已知目录依次选择受信 data root；`ResolveComfyOutputRoot()` 为其 `output` 子目录。唯一真实视频路径 = 该 OutputRoot + Core `manifest.outputs[i].output_relpath`，**必须检查不会越界、不是 reparse point**。现场可只读 `Get-Item -LiteralPath $path`、`(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()`、`ffprobe -v error -show_entries format=duration:stream=codec_name,width,height,avg_frame_rate -of json -- $path`。比对 Core 原始字节数、SHA、fps、帧数；三条 WebM 各留无敏感内容截图和能播放证据。
4. **每镜头耗时**：`%LOCALAPPDATA%\PicotooPetV2\Desktop\logs\media-worker.log` 中 `P0_SHOT_METRIC job=... task=... attempts_at_claim=... known_prompt=... wall_ms=... result=... visual_quality=UNVERIFIED`。**wall_ms 是执行器端到端等待/history/结果提交的墙钟时间，不等于 GPU kernel time**。若 Comfy history 给出 `execution_start` / `execution_success` 时间，作为近似 Comfy 执行区间另列；真实 GPU 功耗/能耗/美元单位成本须从实际可用的显卡遥测、计时与电价独立计算，无数据则写 `UNVERIFIED`，不能把 CI 或 wall_ms 当成本。
5. **C004 FFmpeg MP4**：`%LOCALAPPDATA%\PicotooPet\FinalVideos\final-<SHA256(UTF8(job_id)) 前 32 位小写 hex>.mp4` 和相邻 `.final-video.json`；正式路径由 `FinalVideoAssemblyService.ResolveManagedFinalRoot` 与 Core Job 字符串哈希派生，**不要直接手输假文件名**。Manifest 的 `final_sha256,final_bytes,source_output_sha256,production_package_id,digest` 与三个 WebM 输出逐项核对。C004 只是候选，尚非 GUI Open 授权。
6. **C010A/C011 最终合格交付**：`%LOCALAPPDATA%\PicotooPet\PostProduction\DeliveryReceipts\v1\<按 Job/QaInputDigest 划分的目录>\final-artifact-receipt.json`，精确目录由 `FinalArtifactReceiptStore.DirectoryFor` 派生；不要凭猜测重建目录层次，按文件名搜索该受信 root 并读取 `receipt_digest,qa_input_digest,outcome=PASS,production_job_id,production_plan_digest,artifact_sha256,artifact_bytes,verified_at` 等字段。GUI 持久索引在 `%LOCALAPPDATA%\PicotooPet\PostProduction\VerifiedGoals\v1\*.json`，只在 `PostProductionDeliveryCoordinator` 校验 C011 并记录 PASS 后生成。用实际索引中的 `Candidate.FilePath` 定位最终候选（无旁白/字幕时可能直接采用 C004 fallback；有要求则是受管 master）。**GUI 的“打开最终视频”必须经过重新核对 Core、receipt、最终路径/SHA 以及 full decode，绝不可直接把 C004 文件存在当成 C011 PASS**。
7. **视觉人工验收**：依 1→2→3 播放，记录宠物身份、产品外形、环境/光照连续性、三次不同可识别动作、画质、镜头之间切换/抖动/漂移；至少一条真 MP4 可在 Windows 原生播放器被打开；登记人工 ACCEPT/REJECT、首次成功三镜头率、每个镜头重试次数与成本口径。不要把 `quality_outcome=PASS`（生产合同）等同于人工视觉 PASS。

示例取证报告字段（**全部必须填现场真实值或 UNVERIFIED**）：

```text
candidate_sha=b6230da62eb803e9a7be840374feeb481a657c3a
preview_artifact_id=12318028230
electrical_clearance=UNVERIFIED; mac_deploy=UNVERIFIED; wan_preflight=UNVERIFIED
user_gpu_authorization=NOT_GRANTED
goal_id=UNVERIFIED; creative_job_id=UNVERIFIED
creative_package_id=UNVERIFIED; creative_package_digest=UNVERIFIED
production_job_id=UNVERIFIED; plan_digest=UNVERIFIED; gate_armed=UNVERIFIED
journal_old_pending=UNVERIFIED; worker_pid=UNVERIFIED
shot_1={task_id:UNVERIFIED,prompt_id:UNVERIFIED,history:UNVERIFIED,webm:UNVERIFIED,sha256:UNVERIFIED,bytes:UNVERIFIED,wall_ms:UNVERIFIED,gpu_time_ms:UNVERIFIED}
shot_2={task_id:UNVERIFIED,prompt_id:UNVERIFIED,history:UNVERIFIED,webm:UNVERIFIED,sha256:UNVERIFIED,bytes:UNVERIFIED,wall_ms:UNVERIFIED,gpu_time_ms:UNVERIFIED}
shot_3={task_id:UNVERIFIED,prompt_id:UNVERIFIED,history:UNVERIFIED,webm:UNVERIFIED,sha256:UNVERIFIED,bytes:UNVERIFIED,wall_ms:UNVERIFIED,gpu_time_ms:UNVERIFIED}
production_package_id=UNVERIFIED; quality_outcome=UNVERIFIED
c004_mp4_path=UNVERIFIED; c004_sha256=UNVERIFIED
c010a_receipt_path=UNVERIFIED; c010a_receipt_digest=UNVERIFIED
c011_gui_open=UNVERIFIED; visual_review=UNVERIFIED; gpu_cost_usd=UNVERIFIED
```

## 7. 停止规则与恢复（不产生未经放行的新 POST）

- `HOLD` 不允许新的 claim/attempt/POST。出现网络中断、异常、旧 Journal 不确定、Core package 不一致或模型/Comfy 错误：留存已有 `*.submission.json`、`media-worker.log`、Core 状态与对应 Comfy `history`，保持/恢复 HOLD；**不删除 Journal，不强迫新生产 Job 规避旧失败**。
- 已提交的 `prompt_id` 持续消耗 GPU：HOLD 不停止它；核对真实 history、队列和电气安全，必要时由现场授权人员按安全步骤停机。Worker 的 `ProductionPendingRecovery.ReconcileAsync` 自然完成清理后，才可重新审核是否放行同一 Job。
- 若 Mac Worker 未完成 discovery/synthesis/creative、质量 `NeedsHuman`、三镜头不完整、QA receipt 缺失：标记**阻塞点的真实 API/本地文件/错误码**，不要手工修 SQLite、改变 creative gate 或重复创建 Goal。
- 如果 GUI 没显示“打开最终视频”，先核对 `production_ready`、`GetProductionPackage`、受管 FFmpeg/QA receipt 与 `VerifiedGoals`，而不是让 WPF 再独立执行 FFmpeg。GUI 只消费持久 PASS projection。
- **本次源码只读审计结论**：在上述调用路径中尚未发现可复现且必然阻断首次受控三镜头 T2V 成片的新增生产缺陷；硬件/模型/来源/真实 output/人工质量仍未验证。严禁据此宣称实机 PASS。

## 8. 本文引用的源码入口（均对应 `b6230da6`）

- Goal/API：`src/picotoopet_core/autonomous/{goal_service,human_pipeline,local_creative,video_continuation}.py`；`src/picotoopet_core/api/routes/{autonomous_goals,creative_intelligence,production}.py`；`src/picotoopet_core/security/auth.py`；`src/picotoopet_core/production/{models,service,package}.py`。
- Windows UI/Worker：`windows/desktop/src/PicotooPet.Desktop/{App.xaml.cs,Views/Pages/GoalCenterPanel.xaml,ViewModels/GoalVideoContinuationViewModel.cs,Services/P0MediaWorkerHost.cs,Services/P0ThreeShotAcceptanceGate.cs,Services/ProductionExecutionService.cs}`。
- Comfy/Journal：`windows/desktop/src/PicotooPet.Desktop.Core/Production/{ComfyProductionClient,ComfyWorkflowTemplateValidator,ProductionSubmissionJournal,ProductionPendingRecovery}.cs`；`windows/desktop/src/PicotooPet.Desktop/Services/ProductionLocalEnvironment.cs`。
- MP4/QA/UI：`windows/desktop/src/PicotooPet.Desktop/Services/{FinalVideoAssemblyService,PostProductionDeliveryCoordinator,FinalVideoQaService,FinalArtifactReceiptStore,C011QaDeliveryAuthority,VerifiedGoalDeliveryProjectionStore}.cs`。
- 预览/HOLD：`.github/workflows/p0-three-shot-developer-preview.yml`；`windows/desktop/scripts/Prepare-P0ThreeShotHold.ps1`。

**此文件不产生新 GPU POST、CI 渲染或用户设备连接。**
