# 《茅台晚餐》E01 交接手册（给 Codex / 任何接手的 AI）

更新时间：2026-11-18 00:30（America/New_York）。上一位执行者：Claude。

> 这个目录是**代码、提示词和规则的备份**。图片、视频、模型、真实照片、扫描文件都只在主人的 Windows 电脑上（隐私原因，不进公开仓库）。
> 本地项目根目录：`D:\opc in D\LTX\电影项目\茅台晚餐_连续性V2\`（下文简称 `ROOT`）。本目录的子文件夹名与 ROOT 一一对应。

---

## 0. 先读这三份
1. `23_流程模板/MAOTAI_IDENTITY_LOCK_v2.md` — 茅台长什么样（身份锁、英文描述、比例锁、提示词陷阱）。**每个出图提示词都必须带它的英文描述。**
2. `23_流程模板/LOCAL_LTX_PROFILE.md` — 本地 LTX 视频生成的 10 条执行规则。
3. `23_流程模板/NEXT_STEPS_交接_2026-11-17.md` — 进度与下一步（末尾的“更新 2026-11-18”是最新）。

完整工作流说明（10 阶段 + 关卡）：Claude Doc《茅台短片 · 完整制作工作流 V3》https://claude.ai/artifact/Y4ZTXnXcu3jgTBH2cQufu4 （主人可打开；要点已抄在第 2 节）。

---

## 1. 主人的硬性要求（不可违反）
- 本地优先、尽量不花钱；质量第一：画面稳定、有故事感、色调统一。
- **不要乱加工具/组件。** 新工具必须：替代现有某一步，或解决一个已记录的真实问题；一台机器、一个输入文件夹、一个输出文件夹；先在一集上试。
- **不要在错误的图上接力修补。** 每次生成只从“锁定资产”出发（见第 3 节）；一次只改一个变量；两轮修不好就退回上一阶段。
- 不确定、会出 bug 的事先确认；发图前先按第 4 节自检。
- 主人用中文沟通；交付要简洁。
- 安全/隐私：主人授权“确认无病毒、有用的软件可直接安装部署”；有病毒或隐私高风险的必须先问。真实照片/扫描/户型不要放到公开位置。

## 2. 工作流（V3，按顺序，每步主人确认后才进下一步）
| 阶段 | 产出 | 状态 |
|---|---|---|
| 0 故事 | 节拍 + 7 句英文旁白（`22_声音/vo/lines.json`） | ✅ 已有 |
| 1 视觉开发 | 风格测试、色彩脚本（一楼暖→地下室冷白→吃到时转暖）、光线说明 | ⏳ 未做 |
| 2 角色包 | 母版 C8B_v1、身份锁、LoRA v2 | ✅ 基本完成；缺比例尺图 |
| 3 场景包 | 真实照片风格化背景板、Polycam 扫描平面图、主人标注栏杆/水盆 | ⏳ 进行中（下一步 Blender） |
| 4 道具包 | 碗：口径 16cm/底径 12cm，不锈钢黑骨头印花+黑橡胶底圈，装熟鸡肉；手=藏蓝针织袖 | ⏳ 尺寸已定，参考图待做 |
| 5 分镜/镜头表 | 7 镜方案（见第 6 节）；05b 六模块导演母稿需把“干粮”改“鸡肉” | ⏳ |
| 6 动态分镜 | 草图+临时配音按时长剪 | ⏳ |
| 7 关键帧 | FLUX + LoRA v2，每镜 3 张 | ⛔ 等 1–6 |
| 8 视频 | LTX Desktop，每镜 4 条 + QC v1 | ⛔ |
| 9 后期 | 剪辑、配音、拟音、授权音乐、调色、字幕 | ⛔ |

## 3. 锁定资产（只能从这些出发）
| 资产 | 本地路径（ROOT 下） |
|---|---|
| 角色母版（主人 2026-11-17 确认） | `17_静态首帧板V2/refs_real/MASTER_body_C8B_v1.png` |
| 茅台真实照片（身份依据） | `17_静态首帧板V2/refs_real/face3576.jpg`、`nose3576.jpg`、`real_01–09.jpg` |
| LoRA v2（触发词 `mtai_dog`，强度 0.9） | `21_LoRA训练/output/maotai_lora_v2/maotai_lora_v2.safetensors`（已复制到 ComfyUI `models/loras/`） |
| 地下室背景板 | `24_场景包/PICKS_B1/*.png` |
| 扫描模型 / 平面图 / 主人标注 | `24_场景包/scan/scan_B1_1F_2026-11-17.glb`、`24_场景包/B1_plan_scan_v1.png`、`24_场景包/B1_plan_owner_markup.png` |
| 场景文字记录 | `24_场景包/SCENE_NOTES_v1.md`（只在本地） |

**作废（不要再用作参考）：** `17_静态首帧板V2/keyframes_v3_out … keyframes_v8_out`（比例错误示例）；`24_场景包/flux_out/CUT_*`（AI 想象的剖面图，比例错）；LoRA v1（旧形象）。

## 4. 发给主人前的自检表（一项不过就不发）
- 茅台坐着头顶约到水吧台面（地下室台面 0.95m），远低于吊柜和天花板（2.52m）。
- 碗宽 ≈ 手掌 1.5 倍、16cm；比茅台头窄，远低于胸口。
- 一只狗、一个碗、一只手（双手捧碗镜头除外）；手五指正常、不露脸。
- 身份：花鼻（粉色竖带+黑鼻孔两侧）、两块奶油眉斑、金黄脸颊、额头无白线、小耳、绿三角围巾+白布标。
- 地板是**浅暖橡木色**（不能变冷白/灰）。
- 机位与镜头表一致；地下室镜头狗在画左、碗/楼梯在画右，不越轴。
- 有狗镜头默认全景/中全景（机位 3–4m、离地约 1m、35mm），不要每张都怼近。

## 5. 机器与工具
- **Windows（RTX 5070 Ti 16GB）**：生成机。
  - FLUX.2 Klein 4B（独立 ComfyUI，端口 8190）：`python run_flux_board.py <jobs.json>`，Python=`D:\opc in D\AI\ComfyUI\standalone-env\python.exe`。jobs 格式见 `17_静态首帧板V2/jobs_*.json`（refs=参考图相对路径，可加 `"lora":{"name":"maotai_lora_v2.safetensors","strength":0.9}`）。**跑之前必须关 LTX Desktop**（占 9.6GB 显存，脚本 >5GB 显存会拒绝启动）。
  - LTX Desktop 1.3.2：图生视频，关 Auto-enhance，720p、9:16、4s。
  - ai-toolkit（`D:\opc in D\AI\ai-toolkit`）：LoRA 训练，配置 `21_LoRA训练/*.yaml`，约 1.6s/步，1500 步≈50 分钟。
  - Blender 5.3：2026-11-18 用 winget 安装成功（未开始使用）。
  - .bat 文件必须 **GBK 编码 + CRLF 换行**，否则中文路径和命令会坏。
- **Mac mini M4 Pro 64GB**：编排、QC、TTS、剪辑（也可在 Windows 跑）。
- **QC v1**：`19_自动检查QC/qc_v1.py`（DINOv2 身份相似度 + OWLv2 计数 + 镜头抖动），只能初筛，故事好坏要人看。
- **配音**：Kokoro-82M（`19_自动检查QC/tts_vo.py`），已有 af_heart / am_michael 两版。
- 提示词禁用词：cap / saddle / goggles（会画成帽子、马鞍、眼镜）；写“fur”。

## 6. E01 故事与镜头（主人授权 Claude 安排，2026-11-17）
一楼暖光备饭 → 地下室冷白等待 → 吃到时转暖。
| 镜 | 场景 | 内容 | 景别 |
|---|---|---|---|
| S1 | 一楼厨房岛台 | 主人把煮好的鸡肉放进钢碗 | 特写插入 |
| S2 | 地下室栏杆内 | 茅台趴着，耳朵一动，抬头看楼梯方向 | 中景 |
| S3 | 楼梯 | 主人端碗下楼（只拍腿和手） | 低机位中景 |
| S4 | 地下室栏杆内 | 碗放地上，茅台坐起看 | 全景 |
| S5 | 地下室栏杆内 | 茅台走向碗 | 全景 |
| S6 | 地下室栏杆内 | 低头吃鸡肉（侧前方，防长嘴） | 中近景 |
| S7 | 地下室栏杆内 | 吃完抬头，满足 | 近景 |

## 7. Blender layout（2026-11-18 进度）
- ✅ 已完成：`24_场景包/blender/build_b1_layout.py`（本目录有备份）导入扫描、只留地下室、补栏杆/水盆/16cm 碗/肩高 0.7m 茅台占位/1.70m 人，渲染 `B1_cutaway_realscale.png`、`B1_topdown_realscale.png`，存 `B1_layout_v1.blend`。运行：`17_静态首帧板V2/RUN_keyframes_v4.bat`（当前内容=调用 Blender 5.3 后台跑该脚本，日志 `24_场景包/blender/build_log.txt`）。
- ✅ v2（2026-11-18）：主人指出 v1 多墙/栏杆不到头/马桶前白线 → 改为**手写程序化场景** `24_场景包/blender/build_b1_set_v2.py`（不再导入扫描，只借扫描尺寸；约 1200 sqft；办公区与主厅之间无墙、乒乓球桌后无墙、卫生间为门、栏杆 x=2.4 墙到墙）。输出 `24_场景包/blender/v2/`：A 俯视、B/B2 两角度剖面、C–G 五个 9:16 机位，`B1_set_v2.blend`。运行同一个 `RUN_keyframes_v4.bat`（GBK+CRLF；仓库里是 .txt 的 UTF-8 副本）。
- ✅ 主人确认 v2 比例/布局（2026-11-18）。**CG 场景图 v3**：Blender 每个机位另出一张无占位块的 `v2/clean/*.png` → FLUX.2 Klein **只用这一张白模做参考**（1ref）+ 每个机位单独写"画面里有什么/没有什么"的提示词 → `24_场景包/flux_out_v3/`，选片在 `24_场景包/PICKS_B1_v3/`。
  - 教训：加第二张风格参考图（2ref）会把旧图的构图带进来；通用提示词里列了全屋家具，茅台栏杆区就会被塞进沙发/麻将桌——每个机位的提示词只写该画面应有的东西，并写明 NO xxx。
  - G（高机位越栏杆）走廊尽头多出门，待修。
- ⏳ 下一步，再做下面第 4 步（每个镜头 S2–S7 的相机 + 深度图 → FLUX+LoRA v2 关键帧）。

### 原计划步骤
1. Blender 导入 `scan_B1_1F_2026-11-17.glb`。注意：扫描把一楼家具也叠进来了，且抬高 0.67m —— **只保留 y_min < 0.3m 的物体**（地下室）。坐标：x 西→东、z 北→南、单位米。
2. 按主人标注补：栏杆（约 x≈2.4m，从 z≈-0.3 到 z≈3.9，中段 z≈1.5–2.6 有门）；长方形水盆约 (2.9, 1.1)，圆形水盆约 (2.9, 3.2)；碗（16cm）放两水盆之间；茅台占位体（肩高 0.70m）；水吧台面 0.95m；层高 2.52m。
3. 渲染真实比例 3/4 剖面图 → 发主人确认。
4. 为 S2–S7 架虚拟相机（35/50mm），导出构图图 + 深度图；用深度图约束 FLUX（ComfyUI ControlNet/深度条件，选型时遵守第 1 节“不乱加组件”）→ 再走第 4 节自检。
5. 一楼（S1、S3）照片在本地 `24_场景包/real_photos/IMG_3788–3799`，同样先做场景包再出首帧。

## 8. 已知坑
- 远程操作 Windows 资源管理器只能点击；computer-use 授权 30 分钟无操作会过期。
- Hugging Face 在云端容器被墙，模型下载都通过 Windows 本地 bat 完成。
- LTX Ingredients 模式不吃首帧，不适合；Keyframes 是实验功能。
- 4B 小模型画手弱：手部镜头只拍袖口+局部手，或用订阅的 ChatGPT/Gemini 出图。

## 8. 场景改走"实景照片 → AI 直接转换"（2026-11-18 下午）
- 主人反馈：白模重绘仍太粗糙，要求直接用 AI 把实景照片渲染成写实/精美动画。
- 新装 **Qwen-Image-Edit-2511**（Apache-2.0）到本地 ComfyUI（0.29.0）：`setup_qwen_edit.py` 从官方 HF 源下载
  - diffusion_models: `qwen_image_edit_2511_fp8mixed`（20.5GB）
  - text_encoders: `qwen_2.5_vl_7b_fp8_scaled`
  - vae: `qwen_image_vae`
  - loras: `Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16`、`qwen-image-edit-2511-multiple-angles-lora`
- 跑图：`run_qwen_edit.py jobs_xxx.json`（格式同 run_flux_board；自动加 Lightning LoRA、AuraFlow shift 3.1、CFGNorm、index_timestep_zero）。16GB 卡约 14–30 秒/张。启动器仍是 `RUN_keyframes_v4.bat`（每次改内容）。
- 结果 `24_场景包/qwen_out_v1/`：
  - 写实/清理杂物效果很好，比例细节全保留（例外：IMG_3780 写实版乱编了墙窗，作废）；
  - 纯提示词做不出强卡通化，Qwen 偏保真；
  - 加 C8B 做图2风格参考 → 背景变柔和 3D 风，且 IMG_3784 意外把茅台放进实景、比例合理 → **关键帧可走"实景照片 + C8B 参考"直接合成**。
- 待主人选背景风格（写实 / C8B 柔和 3D / 更强卡通）。
- **2026-11-18 13:45 决定**：背景风格 = C8B 柔和 3D（实景照片 + C8B 图2 风格参考）。
- **茅台比例新标准**：站立头顶 ≈ 球桌面 0.76 m + 2–3 cm ≈ 0.79 m（见 MAOTAI_IDENTITY_LOCK_v2.md 第 4 次修订）。
- **茅台进场景的做法**：C8B 抠图按已知尺寸物体换算像素大小贴入 → `run_qwen_edit.py` 的 `mask` + `denoise 0.5–0.65`、`steps 8` 只在遮罩内融合。整图重绘/把 C8B 当图2 → 会多出第二只狗或球拍，禁止。样例 `jobs_qwen_dog_3784b.json`。

## 9. 剧本 + 本地视频生成链（2026-11-18 下午）
- 主人决定：回到"实景照片 + C8B 参考让 Qwen 直接出带茅台的画面"，不再抠图贴图。
- **剧本 V1**（Claude Doc）：https://claude.ai/artifact/5fj9kFaMzW6xB7A4BX8zm6 —《茅台以为主人忘了开饭》，10 镜 34 秒，TikTok/IG 美国观众，可爱→可怜（假希望再落空）→反转→happy end，结尾与开头同表情可循环。每镜含首帧做法、LTX 英文提示词、难度。
- **ComfyUI 升级** v0.29.0 → **v0.45.6**（`setup_ltx25.py`；torch 2.10.0+cu130 保持不变；回退：`git -C ComfyUI checkout v0.29.0`）。注意 `.venv\Scripts\python.exe` 是坏的，依赖用 `uv pip install --python ..\standalone-env\python.exe --target .venv\Lib\site-packages`。
- **LTX-2.5 本地**：`extra_model_paths.yaml` 直接引用 LTX Desktop 的模型目录 `D:\opc in D\AI\LTX25\models`（bf16 distilled 22B + gemma4-12b，加载时转 fp8），不重复下载。`run_ltx_flf.py`（照官方 video_ltx2_5_flf2v 模板，关闭提示词增强，自写负面词）：有 `last` = 首尾帧，否则 I2V。实测 576×768、3 秒约 80 秒，含同步音频。
- 升级后 Qwen-Image-Edit 回归测试通过（34 秒/张）。
- 生成规则已写成 skill 提案 `maotai-shot-generation`（主人确认保存后 Claude 可用；Codex 请直接读本节 + 剧本文档）。
- 下一步：主人确认剧本 → 10 镜首帧（Qwen）→ 每镜 4 条视频（LTX）→ 剪辑配乐字幕。

## 10. 粗剪 v3 完成（2026-11-18 15:17）
- 首帧：`24_场景包/plates916/`（实景照片裁成 9:16）→ Qwen（实景 + C8B）→ 选片 `24_场景包/PICKS_KF_v1/S01_first … S10_last`。jobs：`jobs_kf_v1…v5.json`。
  - 教训：写 "lonely / desaturated / cool" 会把地下室画成脏地窖、凭空加木栅栏 → 改成"同一个干净的家，只是夜间冷色调"，并写明不加管道/水泥/栅栏。
  - 尾帧（S6 趴下、S10 回到大眼）用"只改姿势/表情"编辑首帧得到，背景一致；要写"画面里只有一个碗"，否则会多一个碗。
- 视频：`jobs_video_v1.json`（544×960，每镜 2 条）。选用：S01v1 S02v1 S03v1 S04v2 S05v2 S06v1 S07v1 S09v1 S10v2；S8 原版会画出人脸 → 改成无手版首帧（碗已在地上）`jobs_video_v2.json`，选 V2_S08_k2_v1。
  - 教训：提示词里出现"手放下碗"，LTX 会把整个人画出来（含脸）。手只放在首帧里、并且动作极小，或者干脆不出现。
- 剪辑：`25_粗剪/cut.py`（容器里 ffmpeg：放大到 1080×1920、Poppins Bold 英文字幕、音频淡入淡出、-14 LUFS）。成片 `25_粗剪/Maotai_Dinner_E01_roughcut_v3.mp4`，34.3 秒。
- 声音全部是 LTX 同步生成的，尚未人工听审；音乐建议上传时用 TikTok/IG 站内热门音乐。
- 下一步候选：选定镜头用同 seed 出 720×1280 高清版；声音精修；主人反馈。

## 11. 系统化改造（2026-11-18 16:30）—— 先读这一节
- **设计文档**：《PicotooPet 自动化生产系统 v1》https://claude.ai/artifact/AUQw7RCw1yE8mgMBC4fxq1 。原则：LLM 只写 `episode.yaml` + 复盘失败镜头；生成/质检/合成都由本地程序执行；主人在关卡确认。
- **E01 V2 剧本方案**在剧本文档顶部（球→无聊→开门声→假希望（主人抱洗衣篮路过）→失落→香气→主人摸头喂食→球滚回循环），待主人确认 + 主人照片。
- **队列 Worker（不要再用鼠标双击 .bat）**：`17_静态首帧板V2/studio_worker.py`（v2，薄循环）+ `worker_tasks.py`（每个任务前热加载，改它不用重启）。启动：`RUN_studio_worker.bat`。
  - 投任务：往 `_queue/inbox/` 放 JSON：`{"runner":"run_ltx_flf.py","jobs":"jobs_xxx.json","note":"..."}`（runner = 本文件夹里任意 .py；可加 `"args":[...]`）。
  - 结果：`_queue/done|failed/<task>.result.json`（ok、秒数、失败行、输出列表）+ `<task>.sheet.jpg` 联系表。心跳：`_queue/worker_heartbeat.txt`（v2 会写 " v2"）。停止：放一个 `_queue/STOP` 文件。
  - ⚠️ 当前机器上跑的还是 v1（只支持 qwen/ltx 两个 runner）。主人关掉标题为 "PicotooPet Studio Worker" 的窗口后重新双击 `RUN_studio_worker.bat` 即升级为 v2。
- **音效**：HunyuanVideo-Foley 已部署（phazei 节点 @afd2960，已做代码审查；权重 fp8 safetensors 在 `ComfyUI/models/foley/`；SigLIP2/CLAP 首次自动下载到 HF 缓存）。`run_foley.py jobs.json`：视频进 → 同步音效出（mp4 + flac），约 25–35 秒/条。测试：`24_场景包/foley_test/`。许可：Tencent Hunyuan Community License（美国可用）。
- 下一步（P1 剩余）：episode.yaml 格式 + 校验器；自动质检 v2（人脸/人体、狗/碗计数、相邻镜头亮度色温跳变）。P2：配乐模型、剪辑程序支持 J/L 切/形状匹配/甩镜/变速。P4：Studio 网页（建议 Codex 用 Gradio 开发，局域网手机可用）。
