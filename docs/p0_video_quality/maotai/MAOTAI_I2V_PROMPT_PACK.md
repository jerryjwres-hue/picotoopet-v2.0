# 茅台 I2V 高质量视频：素材与 Prompt 预备包（独立文档，纯只读分析）

**性质：** 文档与候选 Prompt。不含任何生产代码改动，不启动 GPU/Comfy，不批准任何图片，不写入或覆盖任何冻结素材。
**目标：** 提高真实视频首次良品率，降低 GPU 返工。所有“良率”判断均为方法与假设，**本管线实测良率 = UNVERIFIED**（唯一的真实证据是此前被人工 REJECT 的 3 条 T2V WebM）。

## 0. 先说清楚：我读到了什么、没读到什么

| 需求中提到的材料 | 状态 |
|---|---|
| GOV-2.0、MAOTAI-P0、PROMPT-P0 手册 | **仓库中不存在**（全库检索 `GOV-2.0 / MAOTAI-P0 / PROMPT-P0` 无命中）。本文**没有**引用或转述它们的内容，凡依赖它们的地方都标为“待对照”。 |
| 茅台私有参考图清单 | **不在仓库、我也无权访问你的设备**。因此本文不挑选具体图片，只给出选图规则与逐项勾选表；毛色、花纹、配饰一律用 `{{占位}}`，不编造。 |
| 仓库内关于“茅台”的唯一事实 | `docs/superpowers/specs/2026-08-15-maotai-natural-motion-v2-design.md`：茅台 = Q 版**阿拉斯加雪橇犬（Alaskan Malamute）**桌宠，不得标成哈士奇。 |

**需你确认（会改变 Prompt 的风格词）：** 视频主角是 (A) 真实茅台的照片级形象，还是 (B) Q 版插画桌宠？本文默认 **(A) 照片级**；若是 (B)，把 Prompt 里的 `realistic` 换成 `stylized 3D cartoon, Q-version`，并按 B 重新做参考图。

## 1. 已按源码核实的冻结事实（不要为了“试试”去改）

- 工作流：`comfy.wan22.ti2v5b.i2v.v1`（Wan2.2 TI2V-5B），`windows/production/workflows/wan22-ti2v5b-i2v-api-v1.json`。**只有 `start_image`（首帧）**，没有尾帧。KSampler 固定 steps=30、cfg=5.0、uni_pc、simple、denoise=1.0。
- 横屏档 832×480，24 fps，4 秒 = **97 帧**（4×24+1）≈ 4.04 s。每镜头最多 2 次技术尝试（`MAX_COMFY_ATTEMPTS=2`）。seed 由 job/shot 确定性派生，**不能自选 seed**：重跑意味着新 Job，不是“换个 seed 抽卡”。
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
Maotai, a large fluffy {{COAT}} Alaskan Malamute with erect triangular ears, dark almond eyes and a plumed tail curled over its back, stands calmly on {{SURFACE}}. He slowly turns his head toward the camera and blinks once; his ears twitch slightly, his chest rises with a gentle breath, and the fur and tail sway softly. Medium shot, locked-off tripod camera, no camera movement, soft natural daylight, realistic, smooth natural motion, consistent appearance, a single dog, no text or logo.
```

中文意思：茅台自然站立，缓慢转头看镜头并眨眼一次，耳朵轻动、呼吸起伏、毛发和尾巴轻摆；固定机位，柔和日光，写实，只有一只狗，无文字无 Logo。

**映射到 Video Bible（这才是实际要填的）：** 就是 `candidates/T1_living_pet_bed.json` 的第 1 镜或 `T4_product_collar_tag.json` 的第 1 镜：`featured=[SUBJECT]`（或带产品）、`opening_state` = 首帧参考图的真实状态、`visible_action` = 上面那一个动作、`camera_framing = medium shot`、`camera_movement = STATIC`。

**两个必须先回答的开放问题（不要猜）：**
- “首条 4 秒视频”走哪条路径？当前 v1.1 桥接（#204）要求**三镜头全覆盖审批**；单镜头路径需要原始包里该镜头本来就是 `IMAGE_TO_VIDEO`。我没有读到 Codex #219 的执行入口，**未验证**，请总控确认。上面的 Prompt 对两种路径都适用（它就是三镜头链里的第 1 镜）。
- `{{SURFACE}}` 与 `{{COAT}}` 必须来自你的私有参考图清单（见 §3）。

## 3. 茅台身份锁与参考图选用

**身份短语（≤240 字符，门禁要求每个 distinguishing mark 都已出现在短语里）：**

```text
Maotai, a large fluffy {{COAT}} Alaskan Malamute with erect triangular ears, dark almond eyes and a plumed tail curled over its back
```
`{{COAT}}` 填**你的参考图里能一眼看出的毛色/面部花纹**（例如“grey-and-white with a darker face mask”这类描述必须以参考图为准，本文不替你编）。如果茅台有固定配饰（项圈/围巾/背带），把“颜色+品类”加进短语并在三镜头里**每次同一个颜色词**；没有固定配饰就不要加（越少属性，越少漂移）。

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
- **首次建议顺序：T4 → T1 → T2 → T3。** T4 动作最小；T2/T3 含走路/进食，只在 T4/T1 良品后再上。

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

- **UNVERIFIED：** 任何一条 Prompt 的真实出片效果；本管线首次良率；茅台具体毛色/配饰；产品是什么；风格是照片级还是 Q 版；单镜头路径入口；权利与来源。
- **BLOCKED（不在本任务范围）：** v1.1 I2V 出货仍被设计性阻塞（`claim()` 拒绝、Windows 证明未验证）；GPU 与电气前置条件未解除；Windows 正式发布 gate 被 Maotai 美术资产缺失阻塞。
- **本文没有做：** 没有改任何生产代码，没有启动 GPU/Comfy，没有下载模型，没有访问你的设备，没有批准或登记任何图片。
