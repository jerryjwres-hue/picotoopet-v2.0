# P0 #91 首片 3×4 秒纯 T2V — HOLD 阶段只读准入核查

冻结源码：`19dcf396ba44828641c91c08dc65aa881a41435a`。**仅给操作员核对指定已存在 Job，不产生任何新的 Goal/Job/claim/attempt/Comfy POST。** 本文是现有 [#121 完整双机规程](https://github.com/jerryjwres-hue/picotoopet-v2.0/blob/ba20113123233a449328ba895fbb12226174d6f9/docs/p0_video_acceptance/FIRST_THREE_SHOT_CONTROLLED_FILM_B6230DA_CN.md) 的**19dc 准入补页**，不可沿用 #121 中旧 b623 安装包 SHA/工件号。所有现场设备/模型/Job 数据仍 UNVERIFIED。

## 0. 前置 HOLD；检查对象不能凭空猜

- 在**同一个 Windows 账户**、在**任何** GUI / `Picotoo Pet AI.exe --p0-media-worker` 首次启动前，按总控批准的 **19dc 构建工件内** `Prepare-P0ThreeShotHold.ps1` 原子创建 `%LOCALAPPDATA%\PicotooPetV2\MediaWorker\v1\three-shot-acceptance.json`，严格只包含 `{"schema_version":"1.0","mode":"hold"}`。之后同 EXE Worker 读取门禁时才会创建旁边的 `.armed`。**文件缺失且从未 armed = 原有 unattended 模式 = 立即 STOP，不先打开 GUI。**
- 现场只读确认门禁 JSON 正好两键、`mode=hold`、`.armed` 存在且无 reparse point；此后**不得删除** `.armed` 或清理 Journal。旧版本/遗留进程可能绕过新门禁，未核实所有运行中 EXE 的构建来源 = **STOP**。
- 使用已配对的 Mac Core 客户端；所有下面的端点都有 `Authorization: Bearer <existing device token>`，**不从 Windows Credential Manager 导出 token、不在报告贴出 token/完整 prompts**。只读 GET:
  1. `/api/v1/autonomous/goals/{goal_id}` → `goal`
  2. `/api/v1/autonomous/goals/{goal_id}/handoff/video-return` → `continuation`
  3. `/api/v1/creative/jobs/{continuation.creative_job_id}` → `creative_job`
  4. `/api/v1/creative/jobs/{continuation.creative_job_id}/package` → `creative_package`
  5. `/api/v1/production/jobs/{continuation.production_job_id}` → `job`
  6. `/api/v1/production/jobs/{continuation.production_job_id}/plan` → `plan`
  
  `creative_package` 或 continuation 404/null 表示工作尚未完成，**HOLD + UNVERIFIED**；不得借此手动创建第二 Job。所有 ID 从真实 GET 获取，禁止挑选“最新一个”冒充目标 Job。

## 1. 必须全部满足的 JSON 字段（任何不符即 STOP）

| 关联 | 现场核查（字段拼写严格按当前 Python / C# 契约） |
|---|---|
| Goal | `goal.goal_id == continuation.goal_id == <operator-selected-goal-id>`；`goal.intent_type == "video.creative"`（或明确选定的 `product.research_to_video`）；`goal.constraints.local_video_preferred == true` |
| Goal → Creative | `continuation.continuation_mode == "local"`，`continuation.creative_status == creative_job.status == "creative_ready"`，`continuation.creative_job_id == creative_job.creative_job_id == creative_package.creative_job_id` |
| Creative 来源 | `creative_package.quality_outcome == "PASS"`，`creative_job.creative_package_id == continuation.creative_package_id == creative_package.creative_package_id`，`creative_job.source_set_digest == creative_package.source_set_digest == creative_package.manifest.source_set_digest`，`creative_package.package_digest == continuation.creative_package_digest` |
| Creative → Production | `job.production_job_id == continuation.production_job_id == plan.production_job_id`（规范小写 UUID D）；`job.creative_package_id == plan.creative_package_id == creative_package.creative_package_id`；`job.creative_package_digest == plan.creative_package_digest == creative_package.package_digest`；`job.project_key == plan.project_key == creative_job.project_key == creative_package.manifest.project_key == "goal-"+goal.goal_id`；自动 Goal 创建的 `job.idempotency_key == "goal-video:"+goal.goal_id` |
| 首次未领 GPU lease | `job.status == continuation.production_status == "Ready"`；`job.lease_executor_id == null` 且 `job.lease_expires_at == null`。如为旧 `Claimed/Rendering`，属恢复专案，**不作为首次全新 Job 直接 ALLOW** |
| 冻结 Plan | `plan.schema_version == "1.0"`、`job.production_profile == plan.production_profile == "production.comfyui.v1"`、`plan.target_runtime_ms == 12000`、`plan.tasks.length == 3`、`job.plan_digest` 是**64 位小写 hex**且匹配 Core 对同一完整 Plan 的规范化 SHA256 |
| 每条 Task | 按数组次序严格 `order == 1,2,3`；`shot_id` 非空且互异；`production_task_id` 为规范 UUID D 且互异；`target_duration_ms == 4000`、`fps == 24`、`frame_count == 97`；`render_intent == "GENERATIVE_VIDEO"`，`execution_disposition == "Executable"`，`workflow_id == "comfy.wan22.ti2v5b.t2v.v1"`，`negative_prompt_policy_id == "wan22.safe-negative.v1"`，`trusted_input_asset_ref == null`、`reference_asset == null/不存在` |
| 输出 Profile | `video.landscape.v1`→832×480、`video.vertical.v1`→480×832、`video.square.v1`→640×640；三条任务的 `width,height` 必须与 `plan.output_profile_id` 对应 |
| Seed + Prompt | 每个 `seed` 是整数区间 `[0,2^63)`，且按 `SHA256(UTF8(production_job_id + "|" + shot_id + "|1.0"))` **取前 8 字节 big-endian、清除最高位**得到；三条 Seed 互异。每个 `positive_prompt` 非空，人工审查同宠物/产品/场景锚点和三次不同且单一清晰动作 |
| Creative 原始镜头 | `creative_package.manifest.stage_results["shot_plan.v1"].shots[]` 原始三镜头 `shot_id/order` 与 Plan 一一对应，`duration_seconds == 4.0`；`creative_package.manifest.quality_outcome == "PASS"` |

**重要时长说明：** `duration_ms(4.0)=4000`，同时 Wan 约束 `4n+1` 经 `frame_count_for_duration(4.0,24)=97`；`97/24 ≈ 4.0417s` **并不要求** `target_duration_ms=4042`。不要把目标时长与实际帧取样时长混成同一个字段。

**Digest 计算的唯一合法语义：** `src/picotoopet_core/production/service.py::ProductionService._digest` 对**完整的** `ProductionPlan.model_dump(mode="json")` 使用 `json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"),default=str).encode("utf-8")` 做 SHA256。Plan 响应内**没有**独立 `plan_digest` 字段；它属于 **Job**。如使用可信的 Python 3（不下载任何工具）在内存中处理 *GET /plan 的原始、未裁剪 JSON*，才可复算后与 `job.plan_digest` 比较；不得把 PowerShell 默认 `ConvertTo-Json` 的哈希当成 canonical。运行时门禁 `P0ThreeShotAcceptanceGate.AllowsJobAsync` 也会在 **ALLOW 之后、claim 之前**独立重新核对 Core Job、Plan 与 canonical SHA；但这**不能代替 HOLD 阶段人工阅读和准入记录**。未完成独立 digest 核对 => 该项 UNVERIFIED，继续 HOLD。

## 2. 无 GPU 领取与旧 Journal 优先级

- 精确源码次序：`P0MediaWorkerHost.cs::RunAsync` 调用 `pendingRecovery.ReconcileAsync` → 若 `HasPending` 则**禁止枚举新的 Goals**；旧 Job 若要重入 `RunAsync` 同样受 `AllowsJobAsync` 控制；在 HOLD 下不会为它领取新 lease/发新 Comfy POST。旧 prompt 的 Comfy **GET /history** 及 Journal 对账仍可进行（其中可能只修改本地 Journal 状态）。
- 本地只读检查 `%LOCALAPPDATA%\PicotooPetV2\MediaWorker\v1\*.submission.json`；每份现有文件的真实属性是 `JobId,TaskId,PlanDigest,GraphDigest,Phase,PromptId,FailureCode`。若任意 `Phase != "Settled"`、无法读取、发现未知 POST、旧 Worker 仍活跃，标记 **STOP: JOURNAL_PENDING_OR_UNKNOWN**；不能删除/覆盖、人工“补 attempt”或重 POST。
- 在 HOLDER 的既有原生 [28-case independent gate](https://github.com/jerryjwres-hue/picotoopet-v2.0/blob/19dcf396ba44828641c91c08dc65aa881a41435a/windows/desktop/tests/PicotooPet.MediaWorker.SmokeTests/IndependentThreeShotGateTests.cs)，HOLD 拒绝新 `claim/attempt/Comfy POST`，未知历史 POST 先对账。19dc 同 SHA原生 [Same EXE Run 39708483852](https://github.com/jerryjwres-hue/picotoopet-v2.0/actions/runs/39708483852) SUCCESS，**不是用户机器的零 POST 实测**；其它外部 Comfy 客户端也不受本 Worker 门禁管辖。对真实 Windows，HOLD 前有在途 Comfy prompt 或旧版本 EXE，一律 **UNVERIFIED/STOP**。
- 切换精确 Job 的 `allow` 文件**本身**不调用 Core，但运行中的 Worker 接下来可能调用 `ProductionExecutionService.PreflightAsync`（**可能建目录/哈希大模型，并非只读**）、`POST /production/jobs/{job_id}/claim`（分配 GPU lease）、`POST /tasks/{task_id}/attempt`、Comfy `POST /prompt`。本准入阶段**绝不**运行这四项，也不写 ALLOW。

## 3. 最短操作员记录与 STOP

请仅记录**不含 token、完整提示词、敏感日志**的字段：

```text
source_sha=19dcf396ba44828641c91c08dc65aa881a41435a
device_deployment_sha=UNVERIFIED
hold_file_schema_mode=UNVERIFIED; armed_marker=UNVERIFIED; older_worker_exe_absent=UNVERIFIED
goal_id=UNVERIFIED; creative_job_id=UNVERIFIED; creative_package_id=UNVERIFIED
production_job_id=UNVERIFIED; job_status=UNVERIFIED; plan_digest=UNVERIFIED
creative_pass=UNVERIFIED; immutable_plan_digest_independent_match=UNVERIFIED
shot1=[id,task_id,order=1,4000ms,24fps,97frames,seed,workflow,PromptReview=UNVERIFIED]
shot2=[id,task_id,order=2,4000ms,24fps,97frames,seed,workflow,PromptReview=UNVERIFIED]
shot3=[id,task_id,order=3,4000ms,24fps,97frames,seed,workflow,PromptReview=UNVERIFIED]
journal_pending=UNVERIFIED; last_known_comfy_queue/history=UNVERIFIED
production_claim_since_hold=UNVERIFIED; new_comfy_post_since_hold=UNVERIFIED
electrical_clearance=UNVERIFIED; explicit_gpu_authorization=NOT_GRANTED
admission=HOLD / UNVERIFIED (never imply GPU permission)
```

**任何身份冲突、Creative 非 PASS、任务 4000/97/24 不匹配、重复 Seed、Job 已 Claim、Digest 不能确证、Journal 未决、HOLD/.armed 缺失、非同 SHA 已装 EXE、认证不可信、供电负载安全未批准 ⇒ STOP/HOLD。** 只有全部准入证据和物理安全/用户授权独立齐备时，才进入 #121 的 exact-Job ALLOW 操作；本文不是 ALLOW 脚本、没有实际发布或 GPU 许可。

静态证明来源（同一 19dc SHA）：`api/routes/{autonomous_goals,creative_intelligence,production}.py`、`autonomous/video_continuation.py`、`production/{models,compiler,profile,service}.py`、`windows/desktop/src/PicotooPet.Desktop/Services/{P0MediaWorkerHost,P0ThreeShotAcceptanceGate,ProductionExecutionService}.cs`、`windows/desktop/src/PicotooPet.Desktop.Core/Production/{ProductionPendingRecovery,ProductionSubmissionJournal}.cs`，及 `tests/creative/test_three_shot_reliability.py`。**所有实机 Goal、Plan、GPU、WebM、receipt 和人工画质结果均 UNVERIFIED。**
