# P0-Q：多镜头视频质量验收与良品率基线

范围：只读盘点 + 评价标准 + 判定流程 + 可统计指标 + 给 G006 的改进清单。**不含任何真实画面评分，不含运行数据。**
基线源码：`19cd6859`（`integration/win-only-real-video-p0-v1`）。机器可读版本：`quality_rubric.v1.json`；
指标 SQL：`yield_metrics.sql`；守护测试：`tests/video_quality/`。

> 状态声明：没有任何一项**画质**判断被自动化。下面 C011 的 PASS 只表示"技术上完整"，
> 任何 HUMAN_PERCEPTUAL 条目都不能由机器得出 ACCEPT。所有阈值 `UNCALIBRATED`，本文不定义数值。

## 1. 现有 QA 实际证明了什么

| 层 | 源码 | 证明 | 不证明 |
|---|---|---|---|
| Creative 四阶段 Gate | `creative/quality.py::CreativeQualityGate` | JSON schema；禁止载荷；`source_finding_ref`/`evidence_id` 都属于来源集合；shot 覆盖全部 script beat | 故事好不好；跨镜头主体是否一致；镜头能否被渲染器做出来；语气/节奏 |
| Production 编译 | `production/compiler.py` | beat 集合相等；总时长与脚本差 ≤ `TIMELINE_TOLERANCE_SECONDS`；时长量化到 4n+1 帧；不可渲染的镜头标 `NeedsHuman`，不截断 | 提示词质量；跨镜头一致性 |
| Production 提交 | `production/quality.py::validate_task_commit` | 执行器**自报**的宽/高/fps/帧数/mime 与计划一致；`prompt_id` 非空 | 没有打开文件；没有任何画面信息 |
| Windows 执行器 | `ProductionExecutionService.cs` | 模型哈希固定、workflow 白名单、输出在受信目录且非空、记录 sha256 | 内容 |
| C004 拼接 | `FinalVideoAssemblyService.cs` | 重新读取每个分镜文件：受信目录内、字节数与 sha256 等于 Core 已提交的证据，且各镜头宽/高/fps/帧数一致；随后单次 ffmpeg `concat` 硬切并重编码 | 没有单独的镜头 probe/解码（不可解码的镜头只会在最终 concat 内失败）；衔接、色调、运动是否连贯（没有转场/匹配） |
| C009A/B 母版 | `PostProductionMaster*`、`FixedFfmpegMasterVideoComposer.cs` | 旁白 WAV 受限读取与严格头校验、时间窗口、视频流 copy、AAC 规格 | 语音是否清晰、读音是否正确 |
| C010A/C011 | `FinalVideoQaContracts.cs::FinalQaIdentity.Checks`（11 项） | 受管文件、sha/字节、mp4 探测、**全量解码**、视频流/输出档位/时长、音频契约、无意外流、叠加层来源 | **任何画质**：形变、闪烁、抖动、主体漂移、字幕是否遮挡 |

结论：Creative Gate 是**结构**质量；Production 是**来源与时间**质量；C011 是**技术完整性**。三者都不看画面。

## 2. 评价标准（13 项）

`机` = MACHINE_OBJECTIVE（可自动判定通过）；`警` = MACHINE_ADVISORY（只能触发 REVIEW，未校准）；`人` = HUMAN_PERCEPTUAL（只能由对精确 `output_sha256` 的人工判定满足）。

| ID | 范围 | 标准 | 类 | 现有覆盖 | 失败后 |
|---|---|---|---|---|---|
| S01_technical_decode_and_profile | 镜头 | 镜头文件就是执行器提交的那个文件，档位与计划一致 | 机 | 提交校验（自报）+ C004 重读 sha/字节（无单独解码） | BLOCKED |
| S02_subject_identity_across_shots | 视频 | 主体/人物/宠物跨镜头一致 | 人 | 无（计划层前置条件见 §6-1） | REGENERATE |
| S03_anatomy_and_deformation | 镜头 | 无肢体/面部/手爪/产品几何畸形 | 人 | 无（固定 negative prompt 仅降低风险，不验证） | REGENERATE |
| S04_motion_naturalness | 镜头 | 动作自然、不抖 | 人 | 无 | REGENERATE |
| S05_flicker_and_instability | 镜头 | 无闪烁/纹理沸腾/构图漂移 | 人 | 无（可选警示信号：帧间亮度变化，未实现） | REGENERATE |
| S06_frozen_black_or_duplicate_frames | 镜头 | 无冻结/黑场/重复段 | 警 | 无（可选：freezedetect/blackdetect，未实现） | REVIEW |
| S07_prompt_adherence | 镜头 | 画面符合计划的主体、动作、构图、必需事实 | 人 | 无 | REGENERATE |
| V01_cut_continuity | 视频 | 镜头衔接的光线/比例/方向/场景连贯 | 人 | 无（C004 为硬切） | REGENERATE |
| V02_story_coherence | 视频 | 钩子、节奏、CTA 构成连贯故事 | 人 | Creative Gate 仅结构 | REVIEW |
| V03_claims_and_provenance | 视频 | 事实主张可追溯；无禁止载荷 | 机 | Creative Gate + `lineage.v1` | BLOCKED |
| V04_final_file_integrity | 视频 | 成片是受管文件、可全量解码、档位/时长正确 | 机 | C011 8 项 | BLOCKED |
| V05_narration_audio_quality | 视频 | 旁白清晰、读音正确、符合时间窗口 | 人 | `audio-contract.v1`（仅规格） | REGENERATE |
| V06_caption_overlay_quality | 视频 | 字幕/叠加层可读、位置合理、不遮主体 | 人 | `overlay-provenance.v1`（仅来源） | REGENERATE |

`V03` 只证明引用可解析，**不证明主张为真**。

## 3. 判定流程：ACCEPT / REVIEW / REGENERATE / BLOCKED

不可变身份（每个判定与每条指标都必须绑定）：`goal_id / creative_package_digest / production_job_id / plan_digest / shot_id / prompt_id / output_sha256`。
这 7 个字段在当前契约里都存在（`quality_rubric.v1.json` 的 `identity` 映射由测试逐项核对）。**判定绑定精确 `output_sha256`；重新生成后旧判定作废。**

### 逐镜头
1. 计划任务为 `NeedsHuman`、身份不符、技术校验失败（如 sha/字节与已提交证据不符）、或已用完既有 GPU 尝试上限 → **BLOCKED**。
2. 否则若任一 `人` 条目对该 `output_sha256` 没有记录 → **REVIEW**；若某 `警` 信号触发 → **REVIEW**。
3. 人工判定某条 `on_fail=REGENERATE` 的条目不合格，**且**存在已批准的新有界谱系 → **REGENERATE**（见 §4）。
4. 所有条目通过，且每个 `人` 条目都有对该 `output_sha256` 的人工 ACCEPT → **ACCEPT**。

### 整片
1. 任一镜头 BLOCKED，或任一机器客观条目失败 → **BLOCKED**。
2. 失败可归因到具体镜头 → **REGENERATE（局部）**：只重生成这些镜头，之后重新走 C004→C009→C011，旧成片与旧回执**不复用**。
3. 任一镜头或视频级人工条目未评 → **REVIEW**。**仅有 C011 PASS 回执 = REVIEW，不是 ACCEPT。**
4. 所有镜头 ACCEPT 且视频级人工条目均有对精确成片 sha256 的 ACCEPT → **ACCEPT**。

Core 目前**没有**存放这些判定的表，也没有 `REGENERATE` 的执行路径：上面是目标判定表，不是已实现的行为。

## 4. 重生成边界（不得绕过）

- `MAX_ATTEMPTS_PER_TASK = 2`（`production/repository.py`）与 `MAX_COMFY_ATTEMPTS = 2` 是**技术重试**预算，不是质量重生成预算；未知 `POST /prompt` 必须 fail-closed，二者都不得放宽。
- 技术重试复用同一冻结任务计划，**种子与提示词相同**；对质量问题重试同样的输入没有意义。
- `_seed(production_job_id, shot_id, version)` 含 `production_job_id`；`UNIQUE(production_job_id, shot_id)` 禁止同一 job 内同一镜头出现第二代。因此质量重生成必须是**新的、有界、需批准的谱系**（见 §6-3），不是更多的重试。

## 5. 良品率 / GPU / 重生成成本指标

只列**现在能从 Core 事实算出**的；`yield_metrics.sql` 已在真实 schema 上由测试执行（固定的合成行，只验证算术，不是实测）。

| 指标 | 定义 | 来源 | 现在可得 | 注意 |
|---|---|---|---|---|
| 技术首次通过率 | `tasks_first_pass / tasks_succeeded` | `production_tasks.attempt_count` | 是 | 技术通过 ≠ 画面可用 |
| 每成功镜头渲染次数 | `attempts_on_succeeded_tasks / tasks_succeeded` | 同上 | 是 | |
| 尝试墙钟秒数 | Σ(`finished_at − started_at`) | `production_attempts` | 是 | **上界**：含 ComfyUI 排队；真实 GPU 分钟需要 ComfyUI history 时间戳，目前不持久化 |
| 未完成尝试数 | `finished_at IS NULL` 计数 | 同上 | 是 | 崩溃/进行中 |
| 首个预览耗时 | 首个 Succeeded 镜头 `finished_at − job.created_at` | tasks/jobs | 是 | 是技术预览 |
| 成片耗时 | `production_packages.created_at − job.created_at` | packages/jobs | 是 | 不含后期 |
| 失败码分布 | `failure_code` 计数 | `production_attempts` | 是 | |
| 不可执行任务数 | `execution_disposition <> 'Executable'` | tasks | 是 | 编译期就注定无法渲染的创意浪费 |
| 首次可用镜头率 | 人工 ACCEPT 的首代镜头 / 全部镜头 | **无** | 否 | 需要 §3 的人工判定记录 |
| 完整可用视频率 | 整片 ACCEPT / 整片 | **无** | 否 | 同上 |
| 每可用镜头渲染次数、GPU 分钟/可用视频 | | **无** | 否 | 需要判定 + Comfy 时间戳 |
| 后期拒绝原因分布 | C011 失败码 | **无（仅内存）** | 否 | `FinalVideoQaException` 码只存在于协调器内存/UI，未持久化 |

**不提供任何目标值或阈值。** 先累积真实数据，再讨论目标。

## 6. 给 G006 的改进（最多 3 项，按收益/风险排序）

### 1. 简报级连续性锚点进入每个镜头提示词
- 触点：`production/compiler.py::compile_production_plan` 与 `_positive_prompt`。`CreativeBriefResult.continuity_notes`（`creative/models.py`）被 Creative 阶段产出，但编译器只读 `brief.output_profile_id`，**从不使用**；每个镜头只带自己的 `continuity_keys`。
- 预期收益：同一主体描述出现在所有镜头的提示词里，降低 S02/V01 的漂移风险。**收益未经度量**，要等人工判定数据才能量化。
- 注意：改变 `positive_prompt` 会改变 `plan_digest`，并影响现有断言（`tests/production/test_production_compiler.py`）；需评估文本编码器的提示词长度上限。目标是一个共享锚点，不是逐镜头反复调提示词。
- 验收：`tests/video_quality/test_multishot_plan_invariants.py::test_brief_continuity_notes_reach_every_shot_prompt`（当前为 strict xfail；实现后变为 XPASS，需删除标记）。

### 2. Creative 阶段就拒绝渲染器做不出的镜头
- 触点：`creative/quality.py::CreativeQualityGate.evaluate` 的 `SHOT_PLAN` 分支；复用 `production/profile.py::frame_count_for_duration` 与编译器的判定（`IMAGE_TO_VIDEO` 无受信素材也不可执行）。检查 import 方向不成环。
- 现状：超过渲染器上限的镜头在 Creative 通过，到 Production 编译才变成 `NeedsHuman`，整条作业无法 `RunAsync`（`PRODUCTION_PLAN_CONTAINS_NEEDS_HUMAN_TASK`），此时本地 LLM 与排队都已花掉。
- 预期收益：把"无法渲染"变成同阶段 `RETRY`（带"拆分该 beat"的纠正指令），直接减少 `tasks_not_executable` 与整条作业报废。
- 验收：`test_creative_gate_rejects_a_shot_the_renderer_cannot_produce`（strict xfail）。

### 3. 有界、需批准的局部重生成谱系（设计项，体量最大）
- 触点：`production/models.py::ProductionJobCreateRequest`、`production/service.py::create_job`、`production/compiler.py`（只编译指定镜头子集）、`production/repository.py`（父子 job 关联）、拼接侧只取"父 job 已 ACCEPT 镜头 + 子 job 新镜头"。
- 依据：`_seed` 含 `production_job_id`，子 job 自然得到新种子与新 `production_task_id`，不需要放宽任何重试上限。
- 约束：每次重生成必须绑定被拒的 `output_sha256`、有总代数上限、需要批准；不得修改技术重试预算，不得绕过未知 POST fail-closed。
- 预期收益：只为不合格镜头付 GPU 成本，而不是整片重跑。
- 验收（尚无测试，需 G006 先定设计）：子 job 的种子/任务 ID 与父不同；超过代数上限被拒；未批准不能创建；父 job 的 2 次尝试上限与 fail-closed 行为不变；重新拼接后 C011 回执为新回执。

## 7. 明确未验证

- 没有对任何真实画面做过评估，没有 GPU 运行、没有人工评审、没有运行数据。
- `S05/S06` 的候选机器信号**未实现、未校准**；即使实现，也只能触发 REVIEW。
- Wan2.2 固定模板（30 步、cfg 5.0、`uni_pc`、固定 negative prompt）的出片质量**本文不作任何判断**。
- 上述盘点基于 `19cd6859` 的源码阅读与测试；未覆盖之后的提交。
