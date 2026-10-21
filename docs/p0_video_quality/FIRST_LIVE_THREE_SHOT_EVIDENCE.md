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
4. **每条合格视频 GPU 分钟成本** = 在同一封闭 cohort 中为得到这些视频实际发生的 **所有 GPU 提交**（含失败、技术重试和经批准的重新生成）所消耗的可归属 GPU active_ms 总和 / 60000 / 人工 ACCEPT 视频数。只有历史执行时间时可另报 **Comfy execution_wall_proxy_minutes / ACCEPT video**，不得混淆成真实 GPU busy minutes。若 ACCEPT 视频数为 0，成本比率 **N/A（分母为零）**，累计耗时仍单列；若任一时长缺失，成本记 UNVERIFIED / PARTIAL COVERAGE 而非 0。此次：GPU 设备证据覆盖 ____ 次 / 实际 ____ 次提交；ΣGPU active_ms ____；合格视频数 ____；GPU min / accepted video ____；代理口径 ____。
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
