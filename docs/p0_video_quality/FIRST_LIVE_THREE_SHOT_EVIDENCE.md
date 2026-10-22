# P0 #91 — 首条真实三镜头视频：QA / 良率 / GPU 成本证据单（填写模板）

**性质：** 一份针对首次实机产出的只读、人工填写记录；不是 Core schema、数据库、机器评分器或新的 QA receipt。首次创建时所有实测值均留空，不准填 0 冒充观测。
**证据基线：** 联合候选 SHA b6230da62eb803e9a7be840374feeb481a657c3a；#105 Draft PR 源 SHA 43f083e46a9045550276e1229eccf9b72fa9e8cb 的 [QUALITY_ACCEPTANCE.md](https://github.com/jerryjwres-hue/picotoopet-v2.0/blob/43f083e46a9045550276e1229eccf9b72fa9e8cb/docs/p0_video_quality/QUALITY_ACCEPTANCE.md) 和 [13 项 quality_rubric.v1.json](https://github.com/jerryjwres-hue/picotoopet-v2.0/blob/43f083e46a9045550276e1229eccf9b72fa9e8cb/docs/p0_video_quality/quality_rubric.v1.json)。#105 尚是独立 Draft，不声称已并入此候选。

## A. 一次冻结、一条身份链

| 字段 | 填写（未验证填 UNVERIFIED） | 权威来源 |
|---|---|---|
| review_run_id / UTC 记录时间 / 操作者 | ______ / ______ / ______ | 本记录人工建立 |
| Windows EXE 实际来源 SHA / 预览 ZIP SHA256 | ______ / ______ | 已验证的 developer preview manifest；不可凭分支名称推断 |
| Mac Core/Worker 实际来源 SHA | ______ | 部署或运行证据；不可凭 PR PASS 推断 |
| goal_id / continuation_mode | ______ / ______ | GoalVideoContinuationRecord |
| handoff_sha256 / return_sha256 | ______ / ______ | GoalVideoContinuationRecord；local mode 为 discovery / synthesis 来源证明 |
| creative_job_id / creative_package_id / creative_package_digest | ______ / ______ / ______ | GoalVideoContinuationRecord / Creative Package |
| production_job_id / plan_digest | ______ / ______ | ProductionJobRecord |
| 冻结 Production Plan 的来源、读取 UTC 时间和只读副本 SHA256 | ______ / ______ / ______ | Core 返回的 plan 原文；与 job.plan_digest 的正式规范校验结果须 PASS |
| frozen task count / order / profile / total target_runtime_ms | ______ / ______ / ______ / ______ | ProductionPlan；必须恰好 3 个可执行 T2V，不能预填数值 |
| HOLD before GUI 证据 / 只读 Plan 核对 / exact Job ALLOW 授权 | ______ / ______ / ______ | 现有三镜头准入文件与操作审计；只记录已实际执行项 |
| production_package_id / production_package_digest / package_relpath | ______ / ______ / ______ | Core ProductionPackageRecord；只有完成后可填 |

**必须一致：** Goal 的 creative_package_digest = Job 的 creative_package_digest = Plan 的 creative_package_digest；Job.plan_digest 与所读冻结 Plan 的规范 digest 一致；C011 receipt.production_plan_digest = Job.plan_digest。未一致则 BLOCKED，不产生任何良率 ACCEPT。

## B. 三条冻结 Task 与实际 WebM（固定恰好 3 行）

| 顺序 | shot_id | production_task_id | workflow_id / seed | 帧数 / fps / 目标毫秒 | Core status / attempt_count | Comfy prompt_id | output_relpath / SHA256 / bytes |
|---|---|---|---|---|---|---|---|
| 1 | ____ | ____ | ____ / ____ | ____ / ____ / ____ | ____ / ____ | ____ | ____ / ____ / ____ |
| 2 | ____ | ____ | ____ / ____ | ____ / ____ / ____ | ____ / ____ / ____ | ____ | ____ / ____ / ____ |
| 3 | ____ | ____ | ____ / ____ | ____ / ____ / ____ | ____ / ____ / ____ | ____ | ____ / ____ / ____ |

来源：Core ProductionPlan.tasks、ProductionTaskRecord；成功后以 ProductionPackage.manifest.outputs[] 的 task/shot、seed、comfy_prompt_id、output_sha256、bytes 复核；在 Windows 受信任 output root 上重算 WebM SHA256，记录是否匹配：**____**。文件路径只能是该根下的受控文件。三行不可省略、不可拿 C011 的单一 MP4 hash 代替 WebM hash。

## C. 每一次真实 GPU 提交的事件账（含失败、重试，不得只记录成功镜头）

| shot_id / attempt # | prompt_id（是否重连复用） | Comfy history 原始副本路径 / SHA256 / 采集 UTC | history.status / execution_start / success-or-error 时间（UTC） | 计算出的 execution_wall_proxy_ms | Worker wall_ms / result |
|---|---|---|---|---|---|
| ____ / ____ | ____ / ____ | ____ / ____ / ____ | ____ / ____ / ____ | ____ | ____ / ____ |
| ____ / ____ | ____ / ____ | ____ / ____ / ____ | ____ / ____ / ____ | ____ | ____ / ____ |
| ____ / ____ | ____ / ____ | ____ / ____ / ____ | ____ / ____ / ____ | ____ | ____ / ____ |
| 有额外提交则逐条追加 | | | | | |

- 只读来源为 Comfy GET /history/{prompt_id} 返回原文（尤其 status.messages 有记录时的 execution_start、execution_success、execution_error）、Core production_attempts 的 attempt_number / started_at / finished_at / status / failure_code，以及现有 P0_SHOT_METRIC 日志。**status.messages 事件不保证各 Comfy 版本都有；没有就填 UNVERIFIED，不倒填推测时间。**
- execution_wall_proxy_ms = history 中同一 prompt 的结束事件毫秒时间戳 − execution_start 毫秒时间戳；只在时间戳完整、顺序有效且能对应同一 prompt 时填写。它是 **Comfy 执行阶段墙钟代理值，不是经硬件测得的 GPU active time**。若 history 明示缓存/部分缓存，注明：____。
- Core 的 (finished_at − started_at) 与 P0_SHOT_METRIC.wall_ms **均不是 GPU 繁忙时间**，可能包含排队、网络、恢复、上传/验证，亦可能在异常终止时漏计仍在执行的 GPU 工作；只作端到端时长旁证。**实际 GPU active_ms** 须用同一 prompt 可归属的设备侧 GPU 采样/性能追踪证明；来源/采样覆盖范围/误差：____；无此证据填 UNVERIFIED。
- 未知 POST 或未决 prompt 不得记作失败后重新发送，不得通过本证据单修改原有至多 2 次技术尝试或 HOLD/ALLOW 行为。

## D. C004 → C009/C010A/C011 技术链（填写真实产物，不另造 receipt）

| 字段 | 填写 | 已存证来源 |
|---|---|---|
| C004 拼接 MP4 路径 / SHA256 / bytes / manifest SHA256 | ____ / ____ / ____ / ____ | FinalVideoArtifact + C004 manifest |
| 是否启用字幕 / 叠加层 / 旁白 | ____ / ____ / ____ | 冻结 narration / overlay plan；不适用写 N/A |
| C009 master（若有）路径 / SHA256 / bytes / master manifest SHA256 | ____ / ____ / ____ / ____ | MasterVideoArtifact；没有 master 写 N/A |
| C011 最终被选择的 MP4 路径 / SHA256 / bytes | ____ / ____ / ____ | 受管文件实算 + final-artifact-receipt.json 的 artifact_sha256 / artifact_bytes / artifact_file_name |
| C010A/C011 receipt 完整路径 / receipt_digest / qa_input_digest / outcome / verified_at | ____ / ____ / ____ / ____ / ____ | **既有** FinalArtifactReceiptStore 的 final-artifact-receipt.json |
| receipt.production_job_id / production_plan_digest / production_package_digest | ____ / ____ / ____ | 与 A、B 节和 Core 原值严格一致 |
| receipt.c004_source_sha256 / selected_visual_sha256 / artifact_sha256 | ____ / ____ / ____ | 验证拼接→后期→最终选择的哈希关系，三者不必相同 |
| passed_check_ids 是否等于 11 个规定的 C011 check IDs、MP4 是否全解码、Windows 实际播放 | ____ / ____ / ____ | receipt.passed_check_ids、C011 原有机制、人工播放证据 |

**注意：** 此处只有现有技术 QA 的 PASS receipt；它不含画质人工 ACCEPT 字段。C011 FAIL 一般不产生持久 PASS receipt，失败码需从当前日志/界面另行留存；不得自行伪造 PASS receipt。

## E. 逐镜头人工审片（每个 WebM 必须绑定 B 节的精确 SHA256）

审片人 ____；UTC 时间 ____；审片设备/软件 ____；逐镜头 **完整观看** 状态 ____；评分规则：可选 1–5 主观备注（1=明显不可用、3=需复核、5=表现良好），**未校准且绝不直接决定 ACCEPT**。每项另填人工 ACCEPT / REJECT / UNREVIEWED，留下可复核的具体时间码/缺陷说明。

| shot 顺序 / 精确 WebM SHA256 | S03 畸形（分/判定） | S04 动作自然（分/判定） | S05 闪烁稳定（分/判定） | S06 黑/冻/重复（人工复查） | S07 符合提示词（分/判定） | 综合判定/缺陷时间码 |
|---|---|---|---|---|---|---|
| 1 / ____ | ____ | ____ | ____ | ____ | ____ | ____ / ____ |
| 2 / ____ | ____ | ____ | ____ | ____ | ____ | ____ / ____ |
| 3 / ____ | ____ | ____ | ____ | ____ | ____ | ____ / ____ |

- S01：Core commit + C004 对 sha/bytes/profile 的机器证据：____；**当前并未单独逐条 WebM decode**，所以不要谎称进行了独立镜头全量解码。
- S02（跨镜头主体一致）：人工评分 ____ / verdict ____ / 具体镜头及时间码 ____。
- 技术失败或缺少 hash → BLOCKED；有人类感知标准未经审片 → REVIEW；明确缺陷必须人工 REJECT，是否可以 REGENERATE 还受 #105 新谱系审批规则制约，**本候选无已部署的质量重生成执行入口**。

## F. 整片人工审片及最终决定（绑定 D 节最终 MP4 SHA256）

| 标准 | 人工评分（可选 1–5） / 判定 / 具体证据 |
|---|---|
| V01 镜头剪辑、光线/尺度/方向连续性 | ____ / ____ / ____ |
| V02 叙事节奏、hook 和 CTA 连贯 | ____ / ____ / ____ |
| V03 来源/事实安全（机器证据；主张真实性仍须人工核） | ____ / ____ / ____ |
| V04 最终 MP4 技术完整性（C011） | ____ / ____ / ____ |
| V05 旁白清晰/发音（无旁白则 N/A） | ____ / ____ / ____ |
| V06 字幕/叠加层可读（均无则 N/A） | ____ / ____ / ____ |
| 整片全程 Windows 播放、审片人、UTC 时间 | ____ / ____ / ____ |
| **最终 decision：ACCEPT / REVIEW / REGENERATE / BLOCKED（如内部二选一报表，则 ACCEPT / REJECT）** | ____ |
| 最终 decision 绑定的 MP4 SHA256 / reviewer / UTC / 理由 | ____ / ____ / ____ / ____ |

**ACCEPT 门槛：** 三个镜头都有人审 ACCEPT、所有适用视频级人工项已审 ACCEPT、身份/hash 一致且 C011 outcome=PASS。否则未审完为 REVIEW、技术/身份不符为 BLOCKED、画质不合格为 REJECT（仅在具备新批准谱系时才标记 REGENERATE）。**C011 PASS 单独只能进入 REVIEW。** 不得把 1–5 备注变成未经标定的自动阈值。

## G. 统计口径（样本先写分子/分母，绝不先给百分比）

1. **首发镜头良率 FGY-shot** = 首次已启动验收 cohort 中，首次真实 Comfy POST 对应的**首份生成 WebM**同时通过所需技术证据与人工 ACCEPT 的目标镜头槽位数 / 该 cohort 冻结的 3 个目标槽位。重连恢复相同 prompt_id 不算第二次 POST；attempt 2 才通过不算首发通过；没有开始 GPU 验收则为 UNVERIFIED，不记 0/3。此次填：____ / 3 = ____；是否确已发起首个 POST ____。
2. **首发整片良率 FGY-video** = 首次产出集合直接使用各镜头首个 POST 的首份 WebM，且首次完整拼接/QA/人工整片均 ACCEPT 的初始视频数 / 已启动首次 GPU 验收的初始视频 Job 数。任何镜头重渲染/替换或失败后补片都不计作首发合格，但可成为后续合格成片。首个 Job 的样本只有 0/1 或 1/1（未经验收为 UNVERIFIED）。此次填：____ / 1 = ____。
3. **单镜头 GPU 耗时**：优先报告可与 prompt_id 对应的真实 GPU active_ms；缺失时只报告第 C 节各 Comfy history execution_wall_proxy_ms，明确加后缀 **proxy**，不冒称 GPU 秒。任何缺失项保持 UNVERIFIED。另列 Core/Worker wall_ms 以辨识排队和恢复，但不得作为 GPU 成本值。
4. **每条合格视频 GPU 分钟成本** = 在同一封闭 cohort 中为得到这些视频实际发生的 **所有 GPU 提交**（含失败、技术重试和经批准的重新生成）所消耗的可归属 GPU active_ms 总和 / 60000 / 人工 ACCEPT 视频数。只有历史执行时间时可另报 **Comfy execution_wall_proxy_minutes / ACCEPT video**，不得混淆成真实 GPU busy minutes。若 ACCEPT 视频数为 0，成本比率 **UNVERIFIED（N/A，分母为零）**，累计耗时仍单列；若任一时长缺失，成本记 UNVERIFIED / PARTIAL COVERAGE 而非 0。此次：GPU 设备证据覆盖 ____ 次 / 实际 ____ 次提交；ΣGPU active_ms ____；合格视频数 ____；GPU min / accepted video ____；代理口径 ____。
5. **可选美元成本**：只有经核实的 GPU 租用/计费单价及收费时段才单列 $/accepted video；家用 GPU 的分钟数不自动等于美元成本。若纳入电费、机器折旧、后期 CPU 时间，必须单独列明、不得与 GPU min 混写。

**辅助指标（不要混称视觉良率）**：#105 的 yield_metrics.sql 可按 production_job_id 只读计算技术首次通过、成功任务的 attempt_count、未完成 attempt、排队/执行混合 wall seconds、首技术预览时间和技术失败码。SQL 使用合成数据通过测试并不等于本次有实测记录。

## H. 收件、真实性与状态

| 阶段 | LIVE evidence 状态（PASS / FAIL / BLOCKED / UNVERIFIED） | 核验者 / UTC / 证据文件 |
|---|---|---|
| Mac Goal→Creative/冻结 Job/Plan | UNVERIFIED | ____ |
| Comfy history + 3 条真实 WebM/hash | UNVERIFIED | ____ |
| C004→C010A/C011 最终 MP4 + receipt | UNVERIFIED | ____ |
| 三镜头 + 最终 MP4 人工 ACCEPT | UNVERIFIED | ____ |
| 全量 GPU active time / 每合格视频分钟 | UNVERIFIED | ____ |

交接时保存 **原始只读证据**：Core Job/Plan/Task/Package 响应、Comfy 每个 prompt history 的原始 JSON 与 SHA256、受管 WebM/MP4 的 hash、已有 C004 manifest 和原有 C010A/C011 receipt、P0_SHOT_METRIC 行、人工签名/UTC/时间码。只写路径/哈希到本模板；绝不在仓库提交本机密钥、私有素材或巨量 GPU 视频。它不修改既有 receipt，也不能改变生产准入/模型/Worker 的行为。

**本模板提交时全部设备、视频、画质及 GPU 指标：UNVERIFIED。** 不运行用户设备/GPU，不触发 Release，不 merge / rebase / tag。


## I. G-QA-metrics 指定 SHA d4c27883 证据字段溯源审计（A–H 原表的补充，不是第二份 QA 模板）

**判定术语：** SOURCE_DEFINED＝源码存在确切字段和生产者，须待实机数据才能填写；NEEDS_CAPTURE＝当前既有 API/日志不足，需要额外只读提取或人审；NOT_PERSISTED＝现有持久化不保证保存；UNVERIFIED＝本轮未触及设备，没有实际观测。下表的源码审计通过不等于 GPU/视频 PASS。源 SHA：d4c27883d8988dbb7ab1670c598d5a3b8c8ed384。路径里的 job_id、task_id、digest 均必须由真实记录给出。

### I-1. A 节：Goal/Creative/Job/Plan/运行版本

| 模板字段 / 数据类型 | 原始生产者 / 具体源码位置 | 读取入口 / 原始记录路径 | 何时不可填 |
|---|---|---|---|
| review_run_id, reviewer, reviewed_at_utc / string、string、ISO8601 UTC | 人工取证人；本模板 A 节 | 人工完成的本记录、签名和 UTC | 无真实审查人时 NEEDS_CAPTURE |
| Windows EXE SHA、预览 ZIP SHA256 / Git SHA、hex64 | Windows developer preview 构建器 / 预览 manifest、Actions artifact | 经下载字节复核的 preview-manifest.json、ZIP 原件、实际部署 EXE 版本来源 | PR HEAD/CI 成功不能证明正在运行该 EXE；NEEDS_CAPTURE |
| Mac Core/Worker 实际 SHA / Git SHA | 已部署的 Mac Core/Worker 二进制与部署记录 | Mac 进程和构建工件来源的可信对应，不是远端 PR SHA | 无部署实证 NEEDS_CAPTURE |
| goal_id, continuation_mode / string | GoalVideoContinuationRecord；src/picotoopet_core/autonomous/video_continuation.py:28–42,123–174 | 已鉴权 GET /api/v1/autonomous/goals/{goal_id}/handoff/video-return | 尚未建立 continuation 时 UNVERIFIED |
| handoff_sha256, return_sha256 / hex64 | 同一 GoalVideoContinuationRecord；local 状态取 research-evidence、evidence-synthesis 的 object_hash | 同一 GET 和 Core 结果包 provenance | local 值不是人工 Web GPT 文件 SHA；不能混淆，来源任务缺失时 UNVERIFIED |
| creative_job_id, creative_package_id, creative_package_digest / UUID、UUID、hex64 | Core Creative Package + continuation；video_continuation.py 和 creative service | continuation GET + Mac SQLite creative_jobs / creative_packages 的真实行 | Creative 尚未 PASS 时不完整 |
| production_job_id, plan_digest / UUID、hex64 或 null | ProductionRepository.save_plan；src/picotoopet_core/production/repository.py:113–167 | GET /api/v1/production/jobs/{job_id}；SQLite production_jobs | plan 未冻结时 plan_digest=null |
| plan 原文字节快照 SHA、读取 UTC / hex64、UTC | 只读取证客户端，非 Core 持久字段；Core production/service.py::_digest 负责规范 hash | GET /api/v1/production/jobs/{job_id}/plan 的原始 JSON bytes 单独取 SHA；plan_digest 用排序、压缩、model_dump 的正式规范复核 | HTTP 原始响应 SHA 不必等于 Core 规范 plan_digest；不能简单按字符串比较 |
| task 数量、order、output_profile、target_runtime_ms / int、int[]、string、int | production/compiler.py 与 ProductionPlan | 同一 GET /plan.tasks；要求恰好三个 Executable T2V | 未冻结、包含 NeedsHuman、非三镜头 = BLOCKED |
| HOLD 先于 GUI、只读审核、精准 Job ALLOW / 有序证据、job_id、plan_digest | Windows P0ThreeShotAcceptanceGate.cs；操作员 | 本机 %LOCALAPPDATA%\PicotooPetV2\MediaWorker\v1\three-shot-acceptance.json 及 .armed、操作时间记录 | 单独最终 ALLOW 文件只说明当前准入状态，不能倒推启动前 HOLD 或零历史 POST；NEEDS_CAPTURE |
| production_package_id, package_digest, package_relpath / UUID、hex64、相对路径 | production/service.py::_finalize_if_complete、production/package.py | GET /api/v1/production/jobs/{job_id}/package；Core SQLite production_packages、已有 package archive | 三镜头未全部成功时无 Package；UNVERIFIED |

### I-2. B/C 节：Task、Core attempt、Journal、Comfy、WebM

| 字段 / 类型 | 生产者与源码位置 | 原始证据路径 | 可靠性、缺失与状态 |
|---|---|---|---|
| shot_id、production_task_id、workflow_id、order、seed、fps、frame_count、target_duration_ms / string、UUID、string、int | frozen ProductionTaskPlan；src/picotoopet_core/production/models.py、compiler.py | 已鉴权 GET /production/jobs/{job_id}/plan.tasks[0..2] | SOURCE_DEFINED；这是计划值，不等于对 WebM 独立探测 |
| Task status、attempt_count、当前 comfy_prompt_id、output_relpath、output_sha256、bytes / enum、int、nullable string/hex64/int | Core ProductionRepository 和 ProductionTaskRecord | Mac SQLite production_tasks；成功时可用 GET /package.manifest.outputs 交叉对最终值 | 当前生产 REST **没有 GET tasks/attempts**；不能为只读查看而调用 POST claim。仅 GET plan 不能取得 task 的实际 attempt_count；NEEDS_CAPTURE |
| attempt_number、production_attempt_id、status、started_at、finished_at、failure_code、comfy_prompt_id / int、UUID、enum、ISO8601/null、string/null | src/picotoopet_core/production/repository.py:273–413、production/attempts.py、failures.py | Mac SQLite production_attempts，按 production_job_id + production_task_id + attempt_number 枚举全部真实行 | Core 先预留 Running，再可能 POST；attempt_number 是**技术 reservation 顺序，不等于真实 GPU POST 数**。finished_at 可 null；NEEDS_CAPTURE |
| Journal JobId、TaskId、PlanDigest、GraphDigest、Phase、PromptId / strings + null | ProductionSubmissionJournal.cs::ProductionSubmission | %LOCALAPPDATA%\PicotooPetV2\MediaWorker\v1\SHA256(job_id + 换行 + task_id).submission.json | 只保存当前任务提交/恢复状态，状态可覆盖；Settled 超过 128 条可剪枝。**不构成完整历史事件账** |
| P0_SHOT_METRIC 的 job/task/attempts_at_claim/known_prompt/wall_ms/result / string、int、bool、int、string | P0MediaWorkerHost.cs 与 ProductionExecutionService.cs::ObserveShot | %LOCALAPPDATA%\PicotooPetV2\Desktop\logs\media-worker.log | 日志可丢失；不含 prompt_id；attempts_at_claim 是领取时观测，不是新增 POST 次数；wall_ms 不是 GPU active time |
| prompt_id、Comfy graph、status、status.messages、outputs / string、JSON | ComfyUI 原生 /history 和 /queue；ComfyProductionClient.cs、ComfyPromptReconciler.cs | Windows loopback GET /queue、GET /history/{真实 Core/Journal prompt_id}；保留响应**原始字节**、SHA256、采集 UTC | 历史可能清理；不存在不等于没 POST；status.messages 起止事件可能缺失；NEEDS_CAPTURE |
| first actual POST、recovery、attempt 2 的区分 / evidence classification | Worker ProductionExecutionService.cs:448–470 + Core attempts.py + Comfy history | Core attempt 行 → Journal GraphDigest/PromptId → Comfy 当前 queue/history graph 与 prompt_id。相同 prompt_id 的恢复不是新 POST；新 ID 且证据充分才是新 GPU 提交 | attempt_count=2 只能证明两次 Core reservation；无法确认 attempt1 实际 POST 就不能声称第二次 GPU 运行，记 UNVERIFIED |
| execution_start、execution_success/error、execution_wall_proxy_ms / timestamp 或 null、number 或 null | Comfy history.status.messages（仅版本实际提供时） | 每个 prompt 的原始 GET /history/{id}，同 ID 合法有序事件作差 | 这只表示 **Comfy 事件墙钟代理值**。事件不成对/没有时间戳即 UNVERIFIED；不能当 GPU active |
| gpu_active_ms、VRAM peak、能耗 / number 或 null | 需要额外设备侧 per-prompt 性能追踪，不是 Core/Worker/history 中的完整持久字段 | 实机经批准的设备 telemetry，明确 prompt 对应、起止时钟同步和采样覆盖/误差；粗粒度 nvidia-smi 仅估计代理 | 本 SHA 不能还原严格 GPU active_ms，NOT_PERSISTED / UNVERIFIED；不得由 Core wall 或 Comfy wall 倒填 |
| WebM 的 output_relpath/sha256/bytes、codec/duration / string、hex64、int、ffprobe JSON | ProductionExecutionService.cs:478–499 从 history filename/subfolder 查找并算真实 SHA；production/package.py:138–175 封存最终结果 | 受信 Comfy output root 的原始 WebM、Core production_tasks、GET /package.manifest.outputs[]、ffprobe | 需重新校验 file hash/bytes、Comfy prompt output 与 Core 行；Core 自报 frame_count/fps 不证明真实码流；无文件不填 |
| shot_id + prompt_id + WebM sha256 的绑定 / (string,string,hex64) | Core production/package.py::outputs 与 Windows result commit | 每条 outputs[i] 的 task_id、shot_id、prompt_id、WebM SHA、bytes，再对冻结 Plan、Comfy history、真实文件相互核对 | 对**最终成功镜头**有完整的设计级身份链；失败的早期 POST 可能无最终文件，不能伪造 WebM |

### I-3. D/E/F 节：C004/母版/C010A-C011/人工画质

| 字段 / 类型 | 生产者 / 源码位置 | 原始路径与查证 | 不可填写的情况 |
|---|---|---|---|
| C004 MP4 path/sha/bytes、manifest.source_output_sha256[] / path、hex64、int、hex64[] | FinalVideoAssemblyService.cs::AssembleAsync / LocalFinalVideoManifest | %LOCALAPPDATA%\PicotooPet\FinalVideos 下 final-{job_id的SHA256前32位}.mp4 和同名前缀 .final-video.json，source_output_sha256 与三个 WebM SHA 顺序对应 | C004 未成功/manifest 缺失/不匹配：UNVERIFIED 或 BLOCKED |
| 旁白/字幕/叠加层 flag、plan digests / bool、hex64 | Core Narration/CaptionOverlay 计划 + C009 source | 已鉴权 GET 对应冻结 Plan、C009 artifact manifest、C010A receipt 的 narration_required、captions_required、overlays_required | 没有使用的功能写 N/A；不要伪造产物 |
| C009 master path/sha/bytes、master manifest / path、hex64、int、JSON | PostProductionMasterCompositorService、FixedFfmpegMasterVideoComposer | %LOCALAPPDATA%\PicotooPet\PostProduction\Master\v1 受管文件（从真实 artifact 指定路径读取） | 未选择 master 时 N/A，不等于最终 MP4 |
| selected final MP4 artifact_sha256、bytes、candidate_kind、selected_visual_sha256、c004_source_sha256 / hex64、int、string | FinalVideoQaLineageValidator、FinalArtifactReceiptV1 | %LOCALAPPDATA%\PicotooPet\PostProduction\DeliveryReceipts\v1 下既有 final-artifact-receipt.json；实际重算被选用 MP4 SHA | 这三个 SHA 证明不同处理阶段，不要求相同；没有 receipt 或选中文件则 UNVERIFIED |
| receipt path/qa_input_digest/receipt_digest/outcome/verified_at/passed_check_ids / path、hex64、hex64、string、UTC、string[11] | FinalArtifactReceiptStore.cs、FinalVideoQaContracts.cs（SnakeCaseLower）、C011QaDeliveryAuthority.cs | 既有 Root(PostProduction,DeliveryReceipts,v1) 下 Job/QaInputDigest 定位的 final-artifact-receipt.json；仅真正 PASS 存储 | FAIL 没有对等永久 PASS receipt，且没有自动首轮失败历史；缺失败日志不能证明“首次 C011 通过” |
| S02–S07、V01–V06 人工分数、判定、reviewer、UTC、timecode / 可选整数、enum、字符串 | #105 quality_rubric.v1.json **定义了审核规则**；并无 Core/QA 人工分数字段 | 人工在本模板 E/F 逐项填写并保存签署原件，逐 shot 绑定 WebM SHA，整片绑定最终 MP4 SHA | 缺人工审阅 = REVIEW/UNVERIFIED；C011 技术 PASS 永远不能替代人工 ACCEPT |
| C011 full-decode / GUI 真实播放 / bool+外部证据 | FinalVideoQaService/MediaProbe、真实 Windows 操作者 | receipt 的 full-decode.v1，以及用户实际 Windows GUI 播放记录（独立） | ffmpeg 全量解码不等于 GUI 实际播放，不得互相替代 |

### I-4. 首发与成本必须采用的严格计算门禁

1. **首发镜头固定三槽位 cohort**：只在每槽位首个**已证实实际提交到 Comfy**的 prompt 之最终去向均有证据（或明确未提交而失败并有最终归因），全部 3 个 slot 均完成审计，且人工判定已完成时，才报告 first-generation ACCEPT slots / 3。只做 1/3、剩余待渲染时报告 UNVERIFIED (coverage=1/3)，不写 0/3 或假设失败。预留 Attempt 但 POST 不明时保持 UNVERIFIED。
2. **首发整片初代 cohort**：只有初代三 WebM、**首次真实 C004/C011 尝试**及首次人工整片审阅的结论齐全，才报告 first-generation accepted videos / adjudicated initial jobs。只有最新 C011 PASS receipt 不能证明不存在此前 C011 FAIL 或重试。尚未完成首轮审阅分母=0，报告 UNVERIFIED（绝不 0%）。
3. **attempt #1 与真正 GPU run**：Core reserve/Running 不是 GPU 运行证据；第一次可证 Comfy prompt 才是首次 GPU 提交；history-first 恢复同 prompt 不增加提交次数；Core attempt2 不等于实际第二次 GPU POST。Core attempt 计数与已证实 GPU submit 计数分别填，无法对应则不报首发/成本。
4. **GPU 时间三分法**：Comfy execution_wall_proxy_ms 仅在成对历史事件存在时按末时刻减首时刻；Worker wall_ms 与 Core attempt (finished-started) 都含非 GPU 过程；严格 GPU active_ms 要设备侧 trace 才能填写。nvidia-smi 粗采样、Comfy 墙钟不可悄悄替代硬件时长。
5. **每 ACCEPT 视频 GPU 分钟**：同 cohort 实际可证所有 GPU 提交（含失败/技术重试）active_ms 总和 ÷ 60000 ÷ 人工 ACCEPT 视频数；任一 GPU 时长缺失＝UNVERIFIED / PARTIAL COVERAGE，已审 ACCEPT 分母为 0 时＝UNVERIFIED (N/A: zero denominator)。Comfy event 墙钟成本只能作单独 proxy，标明覆盖率。
6. **缺失取证而非新增系统**：Mac SQLite production_attempts 只读查询、原 Windows Journal/日志、Comfy 已知 prompt 的 GET history/queue **原始字节**、WebM/MP4 复核 SHA/ffprobe、C004/C009 原 manifest、C010A PASS receipt、首次 C011 FAIL 既存日志/界面记录、#105 审阅人的同 hash 签署，均仅保存在受限私有证据目录。不能新增 DB/服务/QA、改 Worker 或放宽 GPU 两次尝试上限。

**首次三镜头完整收件次序（不进行设备操作）：** ①实际部署 SHA/产物摘要与安全准入 → ②Goal/Creative/冻结 Job/Plan/Digest 与 HOLD-first+ALLOW 审核证据 → ③Core 三 Task + 每条所有 attempts 原始只读快照 → ④Windows Journal 和 P0_SHOT_METRIC 原文 → ⑤每次可证实 GPU POST 的 Comfy history 原始 JSON / SHA / 时戳 → ⑥三份 WebM 与 Core package.outputs、文件 SHA、码流实测对应 → ⑦C004 三 source_output_sha256 + MP4/manifest → ⑧如有 C009 master/overlay/voice 来源 → ⑨C010A/C011 原 PASS receipt + 最终 MP4 hash + 首次技术失败记录（若有） → ⑩#105 三 shot 与 final human verdict、审阅人/UTC/timecode、Windows 播放 → ⑪GPU active 设备取证覆盖率、重试次数、分子/分母/UNVERIFIED 状态。

**本次静态审计结论：** 上述数据形状与生产者可定位，但首次真实 Comfy/WebM/QA/人工/GPU 数值仍全部 UNVERIFIED；不得把源码具备字段写作本机实测 PASS。
