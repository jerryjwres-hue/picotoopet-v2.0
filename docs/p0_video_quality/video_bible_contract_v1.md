# Video Bible 合同 v1(`video_bible.v1`)— Issue #108 / P0-T

状态:**规格 + 可执行参考实现(测试侧)**,不是生产代码。生产代码、Creative 阶段与 Mac Core 权威归 G006(#91/#106)。
本文件**不重做** PR #105 的评分表/SQL/测试;质量判定沿用 #105(`docs/p0_video_quality/quality_rubric.v1.json`,SHA `43f083e46a9045550276e1229eccf9b72fa9e8cb`,在 PR #105 分支上,本分支不含该文件)。

> **本合同的 OK ≠ 画质合格。** 它只保证"进入 GPU 之前,故事、主体、产品、场景、运镜在文字层面前后一致且可渲染"。
> 没有真实帧时,所有报告的 `visual_qa` 恒为 `UNVERIFIED`,不存在 ACCEPT。

可执行参考:`tests/video_quality_skill_contract/video_bible_reference.py`(Pydantic 模型、`lint_bible`、`expand_shot_fields`、`prompt_review`、`normalize_instruction`);黄金样例:`tests/video_quality_skill_contract/golden/*.json`。

## 1. 为什么需要它(来自对 Core 的实际阅读)

Core 现在能传到 GPU 的"一致性信息"只有三处,全部是自由文本:

| 现有字段 | 位置 | 现状 |
|---|---|---|
| `ShotPlanItem.subject / environment / action / framing / lighting_style` | `creative/models.py` | 每个镜头由 LLM 独立写,同一只宠物在不同镜头可被写成不同样子 |
| `ShotPlanItem.continuity_keys` | 同上 | 每镜头独立填写,没有任何机制要求"所有镜头都带同一组锚点" |
| `CreativeBriefResult.continuity_notes` | 同上 | G006 `73be16f3` 起由 `compiler._positive_prompt`(`wan22-shot-prompt-v1.1.0`)写入每个镜头 prompt |

`ProductionTaskPlan.positive_prompt`(≤5000)、`seed`、`negative_prompt_policy_id`、`frame_count`、`workflow_id` 全部由 compiler 拥有,`ProductionPlan` 是 `extra="forbid"`。
所以 Video Bible **只能通过上面这些既有文本字段影响渲染**,不得新增 Production 字段,更不得携带 workflow/seed/负向提示词。

## 2. 在流水线中的位置与存储

```
idea_ranking.v1 → creative_brief.v1 → script.v1 → video_bible.v1(新增,sidecar) → shot_plan.v1
                                                         │ lint_bible()  ← 同时是 shot_plan 的门
                                                         ▼
                              CreativePackage.stage_results["video_bible.v1"]   (随包摘要冻结)
```

- 存储位置选择 `stage_results["video_bible.v1"]`:`compile_production_plan` 只读 `creative_brief.v1/script.v1/shot_plan.v1` 三个键,**多出的键不影响旧包与现有编译**;`CreativePackageFinalizer` 直接把 `stage_results` 写进 payload 并算 `package_digest`,所以 Bible 自动被不可变包摘要冻结,不需要新表、不需要改 `ProductionPlan`。
- 旧包没有 Bible:视为 legacy,行为不变。
- Bible 必须绑定:`source_set_digest`(与包一致)、`selected_idea_id`(与 brief 一致)、`arc` 的 beat 序列(与 script 完全一致)、`bible_digest`(内容 SHA-256,构造时校验)。

## 3. 类型化合同(字段与约束)

全部 `extra="forbid", frozen=True`。字符串字段不得含 URL、路径、媒体文件名、workflow/shell 文本(§5)。

| 区块 | 字段 | 约束 / 含义 |
|---|---|---|
| 顶层 | `schema_version="video_bible.v1"`, `bible_id`, `goal_id`, `source_set_digest`(64 hex), `selected_idea_id`, `bible_digest`(可空,非空则必须等于内容摘要) | `sealed()` 写入摘要;任何内容改动使旧摘要失效 |
| `subject` | `subject_id`, `kind: PET/PERSON`, `species`, `breed_or_type`, `coat_or_appearance`, `distinguishing_marks[≤8]`, **`identity_phrase`(≤240)** | `identity_phrase` 必须**逐字**出现在每个 featured 镜头的 `ShotPlanItem.subject` |
| `product` | `product_id`, `name`, `category`, `shape_color_material`, **`identity_phrase`**, `logo_policy`, `claims[≤12]` | `logo_policy` 默认 `NO_TEXT_OR_LOGO_IN_FRAME`:文字/Logo 走叠加层,不让视频模型画 |
| `product.claims[]` | `claim_id`, `text`, `evidence_ids`, `verified` | `verified=true` 必须带 ≥1 个证据 id;`verified=false` 的 claim **不得**出现在旁白 |
| `scenes[]` | `scene_id`, `environment_phrase`, `lighting_phrase`, `palette[≤6]` | 镜头 `environment` / `lighting_style` 必须包含对应短语 |
| `camera_rules` | `screen_direction`, `allowed_movements[]` | 运镜是**封闭枚举**:`STATIC / SLOW_PUSH_IN / SLOW_PULL_OUT / PAN_LEFT / PAN_RIGHT / TRACK_SIDE`;不允许快速变焦/手持/环绕 |
| `continuity_anchors[1..8]` | 短词组 | 必须出现在**每个**镜头的 `continuity_keys` |
| `global_continuity_notes[≤8]` | 句子 | 必须逐字出现在 `CreativeBriefResult.continuity_notes`(Core 只编译这一处) |
| `reference` | `reference_id`, `sha256`, `rights_source`, `verified: true` 或 **null** | 只存摘要与权利来源,**永不存路径**;未验证就必须是 null,并把 `"reference"` 记入 `unverified_fields` |
| `arc[]` | `beat_id`, `role: HOOK/DEMO/PAYOFF/CTA/BRIDGE` | 与 script beat 序列逐项相等;恰有一个 CTA 且等于 `cta_beat_id` |
| `shots[]` | `shot_id`, `beat_id`, `order`, `scene_id`, `duration_seconds`, `featured[SUBJECT/PRODUCT]`, `opening_state`, `visible_action`, `closing_state`, `camera_framing`, `camera_movement`, `handoff_to_next`, `risk_flags[]`, `uses_reference` | 与 shot_plan 的 `(shot_id, beat_id, order, duration_seconds)` 逐项相等 |
| `negative_concepts[]` | 枚举 `EXTRA_LIMBS / MORPHING / DUPLICATED_OBJECTS / TEXT_LOGO_WARP / FLICKER` | **仅建议**。实际负向提示词是 compiler 的 `wan22.safe-negative.v1`,Bible 不能改 |
| `unverified_fields[]` | 字段名 | 缺失的身份/参考信息必须显式标注,不得编造 |

`handoff_to_next` 取值:`CONTINUOUS`(下一镜 opening 必须与本镜 closing 逐字相等)、`CUT_ON_ACTION`(在动作中切,不要求状态相等)、`SCENE_CHANGE`(换场景/时间,不要求相等)。

`risk_flags`(`COMPLEX_ANATOMY / TEXT_IN_FRAME / FAST_MOTION / PRODUCT_CLOSEUP / LIQUID / HAND_OBJECT`)不触发失败,只生成 `human_review_focus`(§7),告诉评审者先看哪里。

## 4. 映射:Bible → 既有 Core 字段(最小安全映射,不新增任何字段)

`expand_shot_fields(bible, shot)` 是确定性展开,G006 可直接采用;LLM 生成的 shot plan 则用 `lint_bible` 校验"是否包含这些短语"。

| `ShotPlanItem` 字段 | 来源 |
|---|---|
| `subject` | featured 的 `subject.identity_phrase` 与/或 `product.identity_phrase`,以 `", "` 连接 |
| `environment` | `scene.environment_phrase` |
| `action` | `"{visible_action}; opens on {opening_state}; ends on {closing_state}"` |
| `framing` | `"{camera_framing}, {运镜短语}"`(如 `close-up, slow push-in`) |
| `lighting_style` | `scene.lighting_phrase` |
| `continuity_keys` | `continuity_anchors`(全部镜头相同) |
| `CreativeBriefResult.continuity_notes` | `global_continuity_notes` |
| `render_intent` | `uses_reference` → `IMAGE_TO_VIDEO`,否则 `GENERATIVE_VIDEO`(不能升级,见 §6) |
| `duration_seconds` | `shots[].duration_seconds`;推荐 3–5 秒 |

渲染时长事实(来自 `production/profile.py`,24 fps):帧数取最近的 `4n+1`,上限 121 帧,且误差 ≤ 2/fps;因此**实际可渲染上限约 5.0–5.04 秒**,3.0/4.0/5.0 秒分别是 73/97/121 帧(黄金样例已钉死)。超出者 Core 不截断,标 `NeedsHuman`。

## 5. Lint:代码、严重度与 Core 动作

`lint_bible()` 的判定只有四档,**没有 ACCEPT**:

| verdict | 含义 | Core 侧动作 |
|---|---|---|
| `OK` | 文字层一致、可渲染;`visual_qa` 仍为 `UNVERIFIED` | 允许进入 Production 编译 |
| `REVIEW` | 建议人工看一眼(咨询级,不阻断) | 进入人工队列 |
| `RETRY_CREATIVE` | Creative 阶段可自行修复(GPU 之前) | 作为 `correction_instruction` 重试该阶段;**不消耗 GPU attempt** |
| `BLOCKED` | 证据/身份/参考不可信或缺失 | `NeedsHuman`,不得继续 |

| 代码 | 严重度 | 触发 |
|---|---|---|
| `CREATIVE_STAGE_SCHEMA_INVALID` | BLOCKED | brief/script/shot_plan 不通过 Core 模型 |
| `BIBLE_FORBIDDEN_PAYLOAD` | BLOCKED | 命中 `CreativeQualityGate.contains_forbidden_output`(URL、`comfyworkflow`、shell 等) |
| `BIBLE_PATH_LIKE` | BLOCKED | Bible 或 shot_plan 含路径/媒体文件名(**防止编造图片路径**) |
| `BIBLE_SOURCE_BINDING_MISMATCH` | BLOCKED | `source_set_digest` 与包不一致 |
| `BIBLE_IDEA_MISMATCH` | BLOCKED | `selected_idea_id` 与 brief 不一致 |
| `ARC_MISMATCH` / `ARC_CTA_MISMATCH` | BLOCKED | arc 与 script beat 序列 / CTA 不一致 |
| `CLAIM_UNKNOWN_EVIDENCE` | BLOCKED | claim 引用的证据 id 不在来源集 |
| `CLAIM_UNVERIFIED_IN_VOICEOVER` | BLOCKED | 未验证 claim 出现在旁白 |
| `SHOT_SET_MISMATCH` | BLOCKED | Bible 与 shot_plan 的镜头集合/顺序/时长不一致 |
| `SCENE_UNKNOWN` | BLOCKED | 镜头引用了不存在的场景 |
| `REFERENCE_UNAVAILABLE` | BLOCKED | 镜头要参考图,但 Bible 无已验证 `reference`,**或** Core 没有该镜头的可信资产(两者缺一不可) |
| `BRIEF_CONTINUITY_NOTES_MISSING` | RETRY_CREATIVE | 全局连续性备注没进 brief |
| `HANDOFF_BROKEN` | RETRY_CREATIVE | `CONTINUOUS` 交接的 closing ≠ 下一镜 opening |
| `SHOT_FIELD_DRIFT` | RETRY_CREATIVE | 镜头的 subject/environment/action/framing/lighting 缺少 Bible 短语 |
| `CONTINUITY_ANCHOR_MISSING` | RETRY_CREATIVE | 镜头 `continuity_keys` 缺锚点 |
| `CAMERA_RULE_VIOLATION` | RETRY_CREATIVE | 运镜不在 `allowed_movements` |
| `TEXT_IN_FRAME_CONTRADICTION` | RETRY_CREATIVE | `logo_policy` 禁止画面文字却标了 `TEXT_IN_FRAME` |
| `SHOT_DURATION_UNRENDERABLE` | RETRY_CREATIVE | 不可渲染时长;修复指令:按同一 beat/证据拆成更短镜头 |
| `SHOT_DURATION_OFF_BAND` | REVIEW | 可渲染但不在 3–5 秒推荐带 |
| `ACTION_MULTI_STEP` | REVIEW | 单镜头动作含 `then`、分号等多步结构(启发式,咨询级) |
| `VOICEOVER_UNCITED` | REVIEW | 有旁白但无证据 id |

> 发现(已写成 strict xfail,见 §10):`CreativeQualityGate.contains_forbidden_output` 对 `json.dumps` 后的文本匹配 `c:\users\`,而 JSON 中反斜杠被转义为双反斜杠,该标记**永远不会命中**。Bible lint 用自己的路径规则兜底。

## 6. 参考图 / I2V 边界

- Bible 只能记录"已验证参考的摘要 + 权利来源";**路径、URL、文件名一律拒绝**。
- Bible 里有 `reference` **不等于**授权。Core 必须另外持有该镜头的 `trusted_local_assets`(现状:`compiler._trusted_asset_ref`);两者缺一,镜头为 `NeedsHuman`,**绝不降级为 T2V**。
- 黄金样例 `g4-ripplesip-reference-missing` 钉死此行为:shot-002 为 `IMAGE_TO_VIDEO`,Bible 无参考 → `REFERENCE_UNAVAILABLE`,Core 编译为 `NeedsHuman`,`workflow_id=None`。
- Windows 侧参考字节校验由 Codex 提供,Mac 权威/来源登记归 G006;本合同不替代它们。

## 7. 人工画面/视频评审(针对精确 `output_sha256`)

沿用 #105 评分表的准则 ID(S01–S07 镜头级、V01–V06 整片级)与判定集合 `ACCEPT / REVIEW / REGENERATE / BLOCKED`。本节只补"怎么评、记什么"。

**硬门槛:** 评审记录必须绑定 `goal_id / creative_package_digest / production_job_id / shot_id / prompt_id / output_sha256`,且评审者看到的是该 SHA 对应文件解码出的真实帧/视频。技术探针(ffprobe)通过、合成 CI、文本模型的"看图说话"均不算观察 → 一律 `VISUAL_QA=UNVERIFIED`。

**每镜头最小检查帧:** 首帧、中帧、末帧;相邻镜头交接处取"前镜末帧 + 后镜首帧"一对。`human_review_focus`(来自 `risk_flags`)指出先看什么:

| `risk_flag` | 评审重点 |
|---|---|
| `COMPLEX_ANATOMY` | 肢体数量、关节方向、抖动后的形变 |
| `FAST_MOTION` | 拖影、形变、闪烁、主体丢失 |
| `PRODUCT_CLOSEUP` | 产品形状/颜色/材质与 `identity_phrase` 一致,无重复产品 |
| `LIQUID` | 水体连续性、是否"穿模" |
| `TEXT_IN_FRAME` | 文字是否扭曲(应已改为叠加层) |
| `HAND_OBJECT` | 手指数量与抓握 |

**评审记录(提案,`visual_review.v0`):** `goal_id, production_job_id, shot_id, prompt_id, media_sha256, bible_digest, outcome(四选一), defects[{timecode,category,severity,evidence}], continuity_issues, reviewer_kind(HUMAN), review_status`。不得在公开 Issue 存原始私有 prompt、凭据或截图。

**重生成边界(不削弱现有上限):**
- 技术恢复仍受 `MAX_COMFY_ATTEMPTS = 2` / `MAX_ATTEMPTS_PER_TASK = 2` 约束,且同 seed、同 prompt。
- `REGENERATE` 只是**提案**:不得自动入队、不得消耗 Core attempt。若要对被拒绝的镜头换 prompt/seed 重做,需要未来、显式批准、带血缘的版本化机制(#105 §4:子 production job);本合同不提供也不暗示自动重渲。
- 已 ACCEPT 的镜头与不可变包保持不动,只替换被明确拒绝的那个镜头。

## 8. 黄金样例(合成,非真实调研、非实测)

| 样例 | 场景 | 画幅 | 镜头(秒) / 帧 | 测试目的 | 期望 |
|---|---|---|---|---|---|
| `g1-pawtrack-park` | 门廊→公园,GPS 项圈标签(虚构品牌) | landscape | 3.0/4.0/5.0/3.0 → 73/97/121/73 | 跨镜头同一只狗+同一产品;5 秒边界 | OK |
| `g2-autobowl-kitchen` | 厨房,自动喂食器 | vertical | 3.0/4.0/4.0/3.0 → 73/97/97/73 | "醒来→走过去→进食"拆成多个单动作镜头,CONTINUOUS 交接 | OK |
| `g3-drytrail-rain` | 雨天街道,宠物雨衣 | square | 4.0/4.0/5.0/3.0 → 97/97/121/73 | 液体风险、快速运动、"抖水"拆镜 | OK |
| `g4-ripplesip-reference-missing` | 客厅,饮水机 | landscape | 3.0/4.0/4.0 | 无已验证参考的 I2V 镜头 | `BLOCKED` / shot-002 `NeedsHuman` |

所有样例:`fixture_kind=SYNTHETIC`;虚构品牌/宠物;旁白只用带证据 id 的合成"证据句";不含 URL/路径/媒体名;`required_facts` 为空(不把不可视觉化的卖点塞进画面 prompt);prompt 无 "8K / masterpiece / cinematic" 之类堆词(测试扫描)。期望的 `positive_prompt` 取自**真实** `compile_production_plan` 输出并冻结。

## 9. 确定性规范化

`normalize_instruction`:NFKC → 移除控制/格式字符(含零宽)→ 折叠所有空白 → 空串拒绝。幂等、与输入换行/全角差异无关;`prompt_review` 的输出经此规范化,且对 Wan2.2 T2V **逐字等于** compiler 的 `positive_prompt`(测试对每个样例比对)。

## 10. 测试覆盖(`tests/video_quality_skill_contract/`)

- `test_golden_fixtures.py`:4 个样例 × 对真实 Core 模型校验、Creative 门 PASS、Bible 封存/冻结/绑定、lint 结论钉死且 `visual_qa=UNVERIFIED`、`shot_plan` 文本等于确定性展开、compiler 输出(处置/workflow/帧数/时长/prompt)等于冻结期望、身份短语与锚点进入每个相关镜头 prompt、旁白 claim 只引用已知证据、不可渲染时长被标出。
- `test_bible_fail_closed.py`:变异测试 —— 摘要绑定与顺序无关、执行器权威字段(seed/workflow/negative_prompt)被 `extra=forbid` 拒绝、参考图(未验证/路径/未知权利来源)被拒、编造证据/未验证 claim/URL/路径/workflow 文本被 BLOCKED、7 秒镜头端到端被标出(lint + Creative 门 RETRY + Core `NeedsHuman` 且不截断)、各类漂移被 `RETRY_CREATIVE` 精确定位到镜头。
- `test_adapters_and_normalization.py`:适配器封闭、评测型模型不可产生可执行 review、T2V review 等于 Core prompt、I2V 需已验证参考且恒需批准、规范化幂等、`ALLOWED_WORKFLOW_IDS` 未被放宽。
- 1 个 strict xfail:`test_core_gate_flags_a_windows_user_path`(上述 Windows 路径标记失效)。

**这些测试都不渲染、不解码、不看画面,因此不构成任何视觉质量结论。**

## 11. 给 G006 的接线建议(≤3 项,按收益排序)

**R1 — 新增 `video_bible.v1` Creative 阶段并用 `lint_bible` 做门(预期收益最大)。**
位置:`CreativeStageKind`(`creative/models.py`)+ `creative/profiles.py` 的阶段元组(script 之后、shot_plan 之前)+ `creative/quality.py`。结果存 `stage_results["video_bible.v1"]`(无需改 `ProductionPlan`/`CreativePackageFinalizer`)。把 `video_bible_reference.py` 的模型原样搬入 `creative/models.py`。旧包无该键 → legacy 路径不变。注意:profile id `creative.content_plan.v1` 被多处 `Literal` 固定,加阶段会影响 `stage_template_versions` 与已存作业——请评估"仅新作业启用"的开关。

**R2 — shot_plan 阶段"先校验、再修复":** LLM 产出后调用 `lint_bible`;`RETRY_CREATIVE` 的 `code/shot_id/detail` 直接作为 `correction_instruction`(现有 RETRY 机制,零 GPU 成本);仍失败时,对 `subject/environment/lighting_style/continuity_keys/framing` 五个字段用 `expand_shot_fields` 确定性覆盖(这五项恰是跨镜头漂移的主要来源),`action` 保留 LLM 内容但必须包含 `visible_action`。

**R3 — 先建"按 `output_sha256` 绑定的人工评审记录",否则第一轮良品率无法度量:** 把 `visual_review.v0`(§7)落库,键含 `bible_digest` 与 `prompt_id`;缺记录时 Goal 展示 `VISUAL_QA=UNVERIFIED`。这是 #105 的 YIELD 指标(人工判定类)目前"不可得"的直接原因。

**明确不建议(超出范围或缺证据):** 不改 `ProductionPlan`、不新增 workflow、不在 Bible 里放负向提示词、不让 `REGENERATE` 自动入队、不依据合成测试调整 prompt 措辞(见 A/B 协议:需要真实数据)。
