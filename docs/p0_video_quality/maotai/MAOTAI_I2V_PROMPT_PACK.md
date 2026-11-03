# 茅台 I2V 高质量视频：素材与 Prompt 预备包（独立文档，纯只读分析）

**性质：** 文档与候选 Prompt。不含任何生产代码改动，不启动 GPU/Comfy，不批准任何图片，不写入或覆盖任何冻结素材。
**目标：** 提高真实视频首次良品率，降低 GPU 返工。所有“良率”判断均为方法与假设，**本管线实测良率 = UNVERIFIED**（唯一的真实证据是此前被人工 REJECT 的 3 条 T2V WebM）。

## 0. 总控最新核定：身份与首条真实单图试产（2026-11-03）

> 本节由总控根据私有云端 GOV-2.0 / MAOTAI-P0 / PROMPT-P0 和 GitHub #219 独立补充。Claude 原先在代码仓库中找不到这些私有资料是合理的，但“仓库没有”不等于“角色未知”。原照片和照片授权信息不得上传公开 GitHub。

**真实身份已经确定：** 这次是照片级、成年阿拉斯加犬 Maotai，不是 Q 版桌宠。身份锁：标志性不规则粉黑鼻、奶油色左右眉纹、黑褐色厚重毛、暖棕颈鬃毛、奶油色脸颊胸爪、棕色眼睛、深色立耳；浅色蓬松卷尾只有原图可见时才表现。私有资产已有 9 JPEG + 1 MP4 与机器可读清单。

**首镜参考图：** `IMG_3576.jpeg`，真实正面半身照片，带透明伊丽莎白圈与亮绿色三角颈巾（恢复期场景变体，非固定生理特征）。第一条镜头应该保持照片原有姿态和配饰，只做一次轻微眨眼、极小眼神变化和自然呼吸；不能凭空要求站立、尾巴摇摆、新项圈、影棚或换景。原图未在本文提交至 Core，因此尚未获得正式溯源/批准。

**执行路径已确认：** GitHub PR #219 已实现 `pilot_first_shot`，验证完整 sealed Story Bible / Keyframe 后，仅需第一张真实获批参考图即可创建**新的单镜头** 4 秒/97帧/24fps/832×480 冻结 v1.1 I2V Job/Plan。它不改变正式三镜头全覆盖要求。代码专项原生 CI PASS，不等于 Mac/Windows 已实机部署或 GPU 已授权；GPU HOLD 仍保持。首试产单次预算：**最多 1 次 Comfy POST，零自动重试**。

**推荐的单镜头动作短句（仅为待映射到 Video Bible 的草稿）：**

```text
Animate the owner-approved original IMG_3576 photograph of the same real adult Alaskan Malamute Maotai. Preserve the pink-and-black mottled nose, cream brow patches, existing front-facing half-body pose, translucent recovery cone and bright green triangular bib. Over four seconds, Maotai blinks gently once, makes only a tiny natural gaze adjustment, and breathes quietly. Keep the camera locked and preserve the original lighting, framing, fur, accessories and background with no new props or pose change.
```

**四套 T1–T4 JSON 是创意占位示例，不是已获批的产品素材或可执行 Job。** 宠物床、背带、慢食碗、项圈吊牌、灰色影棚和对应颜色/品牌均缺少用户实物来源与授权；`needs_human=false` 只代表示例文本的结构标志，不代表产品真实或图片审批完成。先从 IMG_3576 轻动作拿到实际画质证据，后续再考虑生活、户外、真实用品、复杂嘴部动作，不能把 T4 作为首次 GPU 试产。

## 0A. Claude 原研究的可见性边界

| 需求中提到的材料 | 状态 |
|---|---|
| GOV-2.0、MAOTAI-P0、PROMPT-P0 手册 | **仓库中不存在**（全库检索 `GOV-2.0 / MAOTAI-P0 / PROMPT-P0` 无命中）。本文**没有**引用或转述它们的内容，凡依赖它们的地方都标为“待对照”。 |
| 茅台私有参考图清单 | **不在仓库、我也无权访问你的设备**。因此本文不挑选具体图片，只给出选图规则与逐项勾选表；毛色、花纹、配饰一律用 `{{占位}}`，不编造。 |
| 仓库内关于“茅台”的唯一事实 | `docs/superpowers/specs/2026-08-15-maotai-natural-motion-v2-design.md`：茅台 = Q 版**阿拉斯加雪橇犬（Alaskan Malamute）**桌宠，不得标成哈士奇。 |

**总控已确认：此次视频使用真实茅台的照片级形象；Q 版桌宠是另一条产品线，不适用于当前 I2V。**

## 1. 已按源码核实的冻结事实（不要为了“试试”去改）

- 工作流：`comfy.wan22.ti2v5b.i2v.v1`（Wan2.2 TI2V-5B），`windows/production/workflows/wan22-ti2v5b-i2v-api-v1.json`。**只有 `start_image`（首帧）**，没有尾帧。KSampler 固定 steps=30、cfg=5.0、uni_pc、simple、denoise=1.0。
- 横屏档 832×480，24 fps，4 秒 = **97 帧**（4×24+1）≈ 4.04 s。源码可能允许常规镜头最多 2 次技术尝试（`MAX_COMFY_ATTEMPTS=2`），但此次 #219 单图试产只允许最多一次 POST，零自动重试。seed 由 job/shot 确定性派生，**不能自选 seed**：重跑意味着新 Job，不是“换个 seed 抽卡”。
- **负面提示词是写死在图里的固定字符串**（策略 id `wan22.safe-negative.v1`），任务计划里没有负面文本字段：

  ```
  色调艳丽，过曝，静态，细节模糊不清，字幕，最差质量，低质量，JPEG压缩残留，畸形，残缺，多余肢体，融合手指，杂乱背景
  ```
  它已经覆盖：畸形、多余肢体、字幕、杂乱背景、低质量、过曝/艳丽、**静态**（推动画面有运动）。**不能在本阶段新增负面词**（需要新策略 id + 改冻结图，超出范围）。所以“负面约束”必须靠**正面措辞**表达（见 §2）。
- 正面 Prompt 由 `production/compiler.py::_positive_prompt` 用 `；` 拼接：`subject; story continuity: …; environment; action; framing; lighting; continuity_keys; facts`。其中 action 形如 `visible_action; opens on …; ends on …`，framing 里相机运动已由 `CAMERA_PHRASE` 译成 `locked-off tripod camera, no camera movement` / `slow push-in` / `side tracking shot`。**因此你要写的是 Video Bible 字段，而不是整段 Prompt。**
- 故事门禁（`evaluate_story_storyboard`）按**英文**判断颜色漂移、多主体（`another/second/two … dog`）、“floating”等。**Bible 文本必须用英文**；中文只用于注释。
- 参考图合同：PNG/JPEG/WebP，≤32 MiB，受管相对路径 `PicotooPet/references/<sha256>/<shot_id>.<ext>`，必须有真实 Core 审批与权利声明；批准前不得送 GPU。

## 2. 首条 4 秒茅台视频：最稳 Prompt（候选，未实测）

**设计原则（为什么这样写）**
1. **外观交给参考图，Prompt 只写运动。** I2V 的首帧决定身份；Prompt 里只用一句短的身份短语，不重复描述首帧里已经有的细节。
2. **一个主体、一个主动作、一个相机。** 4 秒只放 1–2 个极小动作：转头、眨眼、耳朵微动、呼吸、尾巴轻摆。
3. **选“静中带微动”的动作。** 走路、跑、跳、转圈、爪子碰小物件，是畸形/多余肢体/换脸的高发区，首发一律不用。
4. **相机用 `locked-off tripod camera`。** 管线已用此措辞，避免出现 `static` 一词（固定负面里有“静态”，语义相冲）。
5. **不要新物体入画，不要出现文字/Logo。** 用正面措辞表达：`a single dog`、`plain surface`、`no text or logo`。

**直接可用的整段版本（单镜头验证用）**

```text
Animate the approved IMG_3576 owner photo of the real Maotai, with his distinctive pink-and-black mottled nose, cream brows, translucent recovery cone and bright green triangular bib. Keep his existing front-facing half-body pose. Over four seconds he blinks gently once and breathes naturally with a tiny gaze adjustment. Locked camera, original lighting, framing, dog anatomy, accessories and background, with no new objects.
```

中文意思：首镜从真实 IMG_3576 正面半身照片出发，保持恢复圈、绿巾、粉黑鼻和全部可见外观。茅台只轻眨一次眼、微微调整眼神并自然呼吸；固定摄像机，不凭空移动尾巴或换姿势。

**映射到 Video Bible（实际仍由现有 Core 生成/审核）：** 首条不能直接从 T1 宠物床或 T4 项圈/影棚示例复制，因为真实 IMG_3576 不含那些产品场景。应使用 `featured=[SUBJECT]`、`opening_state`=IMG_3576 经批准首帧的真实姿态、`visible_action`=一次自然眨眼与微呼吸、`camera_framing`=保持原半身构图、`camera_movement=STATIC`。若原三镜头 sealed Bible 不能合法表达这一首帧，则先修改未冻结的候选 Bible 并重新通过原 Story Gate，不得改已冻结生产 Plan。

**首镜入口已核定；剩余实际准入在实机部署、源图授权和 GPU 预算：**
- “首条 4 秒视频”已由 #219 的 `pilot_first_shot` 路径实现：验证完整 sealed Story Bible/Keyframe，仅给第一张经正式批准的图创建新的单镜头 I2V Job/Plan。正式三镜头全覆盖仍保留。上面的 Prompt 对两种路径都适用（它就是三镜头链里的第 1 镜）。
- 首镜 IMG_3576 不使用这套抽象 `{{SURFACE}}`/`{{COAT}}` 占位，因为已有受控私有照片清单。其他 T1–T4 候选在输入真实产品前仍保留占位。

## 3. 茅台身份锁与参考图选用

**后续 T1–T4 模板使用的身份短语（≤240 字符，门禁要求每个 distinguishing mark 都已出现在短语里；仍须参考真实茅台花鼻/奶油眉纹）：**

```text
Maotai, a large fluffy {{COAT}} Alaskan Malamute with erect triangular ears, dark almond eyes and a plumed tail curled over its back
```
`{{COAT}}` 应填写已核实的真实黑褐毛色与奶油色眉纹、粉黑斑驳鼻，不能用泛泛灰白狗替代；现有 JSON 仅为未填充的结构示例，尚不符合茅台最终身份锁。如果茅台有固定配饰（项圈/围巾/背带），把“颜色+品类”加进短语并在三镜头里**每次同一个颜色词**；没有固定配饰就不要加（越少属性，越少漂移）。

**选图规则（逐项勾选，全部为“是”才进入候选）：**

| # | 检查项 | 不合格示例 |
|---|---|---|
| 1 | 画面里**只有茅台一只狗**，无人手、无其他动物 | 合影、人手牵绳 |
| 2 | 全身或 3/4 身，脸部清晰、对焦在眼睛，分辨率明显高于 832×480（建议长边 ≥1280） | 糊、远、逆光剪影 |
| 3 | 姿态为**平静的站/坐/卧**，不在跑跳转身的瞬间 | 动作模糊、张嘴大喘 |
| 4 | 光线均匀、无强滤镜、无严重广角畸变 | 重美颜、鱼眼 |
| 5 | 背景简洁，无文字/Logo/商标，无会入画的小物件 | 招牌、包装字 |
| 6 | 构图接近 16:9（或能无损裁成 16:9），主体不贴边 | 竖图硬拉伸 |
| 7 | 三张图是**同一天、同一光线、同一场景**（三镜头链要求） | 不同房间/不同时段 |
| 8 | 权利明确（你自己拍摄/有授权），能在审批里勾选权利声明 | 来源不明网图 |

**三张图的“状态链”（本文最重要的一条建议）：** 当前工作流只有首帧。所以三张图应按故事顺序拍/选成 A→B→C：第 k 个镜头从第 k 张图出发，目标状态≈第 k+1 张图。**相邻两张图之间的差别要小**（一个站姿到坐姿，而不是跨场景）。镜头的 `closing_state` 必须逐字等于下一镜 `opening_state`（门禁要求），且应描述成“下一张图里能看到的样子”。这样每个 4 秒片段只需要完成一个很小的变化，首次良率最高。

**选图后的流程（不绕过任何门）：** 先按 `picotoopet-story-keyframe-review` 人工看三张实图 → Core 登记审批 → 才谈 I2V。我**不批准**也不会替你批准任何图片。

## 4. 三镜头故事模板（生活 / 出行 / 饮食 / 宠物用品）

四个模板都是 **HOOK → DEMO → CTA，3×4.0 s，单场景、单主角、产品全程在场**，满足现有故事门禁。候选 Bible 草案在 `candidates/*.json`，带占位符 `{{COAT}} / {{PRODUCT_COLOUR}} / {{PRODUCT_NAME}}`。

| 模板 | 场景 | 产品 | HOOK（镜头 1） | DEMO（镜头 2） | CTA（镜头 3） | 难度 |
|---|---|---|---|---|---|---|
| T1 生活 `T1_living_pet_bed.json` | 客厅，窗在画左、床在画右 | 宠物床（静止产品） | 站在床边眨眼、尾巴轻摆 | 踏上床并坐下（中近景，缓推） | 坐在床上平静呼吸、眨眼（全景） | 中 |
| T2 出行 `T2_travel_harness.json` | 玄关，门在画右 | 背带（**穿戴**，全程在身上） | 坐在门边，歪头看门，耳朵转动 | 站起（特写背带，缓推） | 朝门慢走两步（侧向跟拍） | 中高（走路） |
| T3 饮食 `T3_dining_slow_feeder.json` | 厨房一角，碗在垫子上画右 | 慢食碗（静止产品） | 坐在垫子上看碗 | 低头吃（特写，缓推） | 抬头平静看镜头 | 中高（进食嘴部） |
| T4 宠物用品 `T4_product_collar_tag.json` | 浅灰影棚背景，矮木台 | 项圈吊牌（**穿戴**） | 站在台上缓慢转头看镜头 | 胸口呼吸起伏，吊牌轻晃（特写，缓推） | 眨眼、尾巴轻摆（全景） | **低（首选）** |

**设计取舍（都来自“降低 GPU 返工”）：**
- **产品要么穿戴、要么静止，绝不让产品被“施加”。** 不出现人手，不出现爪子摆弄小物件，避开 `HAND_OBJECT` 与产品形变风险。
- **单场景。** 门禁强制一个 `scene_id`；“出行/饮食”因此被收敛成“玄关/厨房一角”，不做跨场景转场。
- **`claims` 留空。** 不写任何产品功效宣称，避免证据绑定与合规风险。
- **真实首试产优先级：IMG_3576 原场景轻动作 → 简化生活 → 户外轻动作 → 用户提供真实产品时的用品 → 复杂饮食。** T4 的假定吊牌和影棚当前不能用于第一条。

**已做的只读校验（本地 CPU，未联网未渲染）：** 用样例值替换占位符后，四个模板均通过 `evaluate_video_bible(story_gate=True)`（0 条 finding）、`evaluate_story_storyboard`，并能 `build_keyframe_kit` 生成 3 张待审关键帧。**这只证明文本合规，不证明画面。**

使用方法（不是新框架，只是查找替换）：复制对应 JSON → 把三个 `{{…}}` 换成参考图清单里的真实描述 → 交给现有 `picotoopet-story-director` 流程作为 `VideoBibleDraft`。

## 5. 人工视觉 ACCEPT / REJECT 标准（纸面清单，对应现有证据单 S03–S07）

**分三道门，越早拒绝越省 GPU：**

### 门 A：三张参考图（GPU 之前）— 用 `picotoopet-story-keyframe-review`
任何一项为“否”→ **REJECT 整套**，不要用 Prompt 修补：同一只狗（脸型、耳形、毛色分布、眼色）；配饰/产品颜色形状位置一致；同一场景布局与光线；每个物体都有可见支撑；三张图状态链顺序正确、相邻差别小。

### 门 B：每条 4 秒 WebM（逐条，绑定精确 SHA256）
观看方式：先全屏、原速完整看 1 遍；再在 0 / 1 / 2 / 3 / 4 秒各暂停一帧与对应参考图对照。

**硬 REJECT（任意一条即 REJECT，不打分）：**

| 代码 | 现象 | 对应证据单项 |
|---|---|---|
| H1 | 身份漂移：耳形、面部花纹、毛色、眼色、配饰/产品颜色在任一帧改变 | S03/S07 |
| H2 | 肢体异常：腿/爪数量不对、融合、扭曲，面部融化 | S03 |
| H3 | 出现第二只动物或人，或画面外物体闯入 | S07 |
| H4 | 物体漂浮、瞬移、凭空出现/消失；产品形状或颜色改变 | S07 |
| H5 | 出现文字、Logo、水印 | S07 |
| H6 | 明显闪烁（整体亮度/色调抽动）、果冻/抖动 | S05 |
| H7 | 黑帧、冻结 >1.5 s、循环重复帧 | S06 |
| H8 | 镜头内切镜头、背景家具位置跳变 | S04/S07 |
| H9 | 首帧与批准参考图明显不符（构图/身份） | S07 |

**软项（全部硬项通过后，各项“是/否/复核”）：** 动作自然（起势与落点平滑，无机械感）；耳朵/毛发/尾巴运动合理；节奏与提示词一致（做了且只做了该做的动作）；末帧状态是否接近下一张参考图（用于镜头衔接）。

**判定：** `ACCEPT` = 0 条硬 REJECT 且软项无“否”；有“复核”则 `REVIEW`（由人决定，不自动通过）；未看满则 `UNREVIEWED`。**数值分只作备注，不决定 ACCEPT**（沿用 `FIRST_LIVE_THREE_SHOT_EVIDENCE.md` 的规则）。

### 门 C：三段拼接后
三段之间：同一只狗、同一场景布局与光线、相邻段衔接无跳变。任一段 REJECT → 整体不 ACCEPT，只重做那一段所在 Job（不要扩大到全部三段）。

## 6. 降低 GPU 返工成本：执行顺序与“缺陷→修法”

**执行顺序（每一步都不花 GPU，除最后一步）：** ① 文本门禁（已有，CPU）→ ② 门 A 参考图实图审查 → ③ Core 审批 → ④ **只渲染第 1 镜**，过门 B 后才渲染其余（`STAGE1_WINDOWS_ONLY_SINGLE_SHOT.md` 的思路）→ ⑤ 其余镜头。

| 观察到的缺陷 | 最可能的原因（假设，未在本管线验证） | 先改什么（按成本从低到高） |
|---|---|---|
| H1 身份漂移 | 首帧不够清晰/脸太小；动作幅度大 | 换更清晰更近的参考图；把动作降到“眨眼+呼吸” |
| H2 肢体异常 | 动作涉及走/转身/多肢体协同 | 改成坐/站静态姿势，去掉走路 |
| H6 闪烁 | 光线复杂、背景细节多 | 换简洁背景的参考图；简化 `lighting_phrase` |
| H7 近乎静止 | 动作描述太弱 | 多一个明确的小动作（转头/呼吸），不要加 `static` 字样 |
| H4 产品变形 | 产品是被“操作”的 | 改为穿戴或静止产品，镜头里不做产品动作 |
| H9 首帧不符 | 参考图被裁切/拉伸 | 预先裁成 16:9 再登记，不要靠管线缩放 |

重跑总会产生新 Job 与新 seed，**不要指望换 seed**；每个镜头最多 2 次技术尝试，所以“改参考图/改动作”比“多试几次”更划算。

## 7. 复用现有 Skill / 文档的具体位置（不新开发框架）

| 用途 | 位置 |
|---|---|
| 起草三镜头 `video_bible.v1`（规则 1–8） | `.agents/skills/picotoopet-story-director/SKILL.md` |
| GPU 前人工审三张关键帧 | `.agents/skills/picotoopet-story-keyframe-review/SKILL.md` |
| 门禁行为、关键帧提案、Core 必须执行的 6 项 | `docs/p0_video_quality/story/README.md` |
| Bible 范例（可对照字段写法） | `tests/creative_quality_2026/story_fixture_2026.py` |
| 参考图权限/审批合同 | `docs/p0_video_acceptance/REFERENCE_I2V_AUTHORITY_CONTRACT_V1.md` |
| 单镜头阶段与 GPU 前置条件 | `docs/p0_video_acceptance/STAGE1_WINDOWS_ONLY_SINGLE_SHOT.md`、`docs/p0_wan_preflight/FIRST_3X4S_GPU_BEFORE_AUTHORIZATION.md` |
| 验片记录表（S03–S07） | `docs/p0_video_quality/FIRST_LIVE_THREE_SHOT_EVIDENCE.md` |
| 只读视觉证据工具 | `docs/p0_video_quality/visual_review/` |

注意：`story/README.md` 明确写明这两个 Skill “**仓库内未安装到任何运行环境**”，只是指令文本；本文不声称它们已部署。

## 8. 未验证 / 阻塞清单

- **UNVERIFIED：** 真实茅台出片质量及良率、T1–T4 产品事实与审批、IMG_3576 在实机 Core 中的可信登记与授权、单镜头 GPU 渲染结果。茅台身份和首镜代码路径已由总控核实。
- **BLOCKED（不在本任务范围）：** #219 代码可供受控私有试产，但实际双端部署、带外配对、IMG_3576 人工/核心审批和 GPU 授权尚未完成；正式 Windows 发布另外受 `torso_neutral.png` 真实美术资源缺失阻塞。
- **本文没有做：** 没有改任何生产代码，没有启动 GPU/Comfy，没有下载模型，没有访问你的设备，没有批准或登记任何图片。
