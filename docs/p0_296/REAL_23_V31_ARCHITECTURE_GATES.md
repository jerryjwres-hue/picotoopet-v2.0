# PicotooPet P0 #296 — 2.3.27.1 × V3.1 架构与兼容门禁

> 状态：**集成前契约**（不是安装验收，不是 GPU 许可，不是生产完成证明）。
> 唯一真实安装基线：`df1d2e2fe89f065ad0eed9ce5e39778b4ba424ed`，运行版本 `2.3.27.1`。
> 参照：Issue #296；V3.1 候选 `integrate/v31-owner-episode-director-install-candidate`。

## 一、不能跑偏的产品目标

PicotooPet 要交付一套**Mac 控制、Windows GPU 执行、网页/手机远程审核**的宠物动画制作系统。
首先完成《茅台》首次 3×4 秒、24fps、832×480 多镜头可追溯成片；再提高真实首发镜头良率、
跨镜头角色/服饰/道具/空间一致性、单位 GPU 成本与故事可看性。CPU-only CI 不是影片良率。

日常交互应当仅需要：**提供故事 → 审核必要的关键决策 → 确认影片**。其余的资产管理、批量候选、
QC、局部重试、拼接和收据归档尽量由确定性的本地执行器完成。导演/角色/分镜 Skill 仅用于
确实需要创作判断的阶段；可选 Blockout 3D、LTX/Wan/MiniMax H3 等不能形成第二条生产队列。

## 二、唯一权威架构

| 责任 | 正式权威 | 不允许做的替换 |
| --- | --- | --- |
| 任务、审批、数据库、版本、生产计划 | 真实 Mac Core 2.3 / SQLite schema 1–24 | 2.2 的 schema 1–4、影子 DB 或重建旧任务 |
| 视频任务冻结 / Claim / Lease / Owner-MASTER 门禁 | 2.3 Production API 与原有单一 Worker 通路 | V3.1 的旧 Executors / Episodes 直接取代生产门禁 |
| Worker 信任 | 现有 Ed25519 Challenge → Witness（preflight 必须 fail-closed） | 用另一个 HMAC 协议默默接入旧路由 |
| 本地创作 | Mac Ollama + Creative/Goal/导演 Skill | 每镜头反复调用付费模型做本地体力工作 |
| 媒体执行 | Windows RTX 5070 Ti / 同一 Worker / ComfyUI / LTX或Wan / FFmpeg | 新独立 GPU 守护进程、未经授权 POST |
| 画面质量 | 固定角色/场景资产 + QC 来源验证 + 人工 ACCEPT | 降级算法输出冒充正式 QC PASS |
| 使用者界面 | Windows Studio，手机后续私有 HTTPS 接入 | 用移动配对 Cookie 代替 Owner 授权 |

## 三、源码确认的协议差异

- Mac 2.3 `src/picotoopet_core/api/app.py` 含 `production`、`autonomous_goals`、
  `creative_intelligence`、`postproduction`、`owner_structured_reviews`、
  `workers` 和相应的调度器。
- Mac 2.3 `src/picotoopet_core/api/routes/production.py` 已有
  `POST /production/jobs/{production_job_id}/worker-challenge`、
  `POST /production/jobs/{production_job_id}/witness/preflight`、
  `POST /production/jobs/{production_job_id}/claim`。挑战并不自动授权 GPU。
- 旧 V3.1 `app.py` 仅注册自己的 `episodes`、`executors`、`studio`、
  `mobile` 等路由；不应整文件覆盖 2.3 的 `app.py`。
- Studio 的 `/studio/storypacks/preview`、手机只读配对和 Episode 候选预览，
  应当以**隔离的新路由**适配 2.3 的 `services`；其页面可用不代表已获得主人的生产授权。
- Windows Studio 客户端旧版调用的 `/api/v1/episodes`、`/episodes/import`、
  `/artifacts/{id}/decision` 等，不能在 2.3 上假定存在。必须逐项映射或显示“不可用”；
  不能把 HTTP 404 或响应体不兼容视为已集成。
- Mac Core 仅监听 `127.0.0.1:8766`；跨机须使用已验证的 SSH 本机转发
  或可信 HTTPS，不允许开放远程明文 HTTP 或在网页暴露 Bearer。

## 四、实际工作顺序与验收

1. **数据与恢复准入**：只读识别原 24 版迁移、在线备份、历史任务/审批计数复核；
   同编号异构 v4 和未知 v25 都应拒绝；原 Mac 8765 AI Server 不触动。
2. **端点和安全准入**：以 2.3 OpenAPI 为真源，逐个对照 Windows Studio 调用、StoryPack、
   OwnerPrincipal、Ed25519 Worker；不允许新队列、HMAC 降级或证据不全时放行 Claim。
3. **两端构建**：原生 Mac、Windows CI、版本清单和哈希一致；安装失败可自动恢复旧 Core，
   并检查恢复后的真实 API/数据库。不得自启动 Health Supervisor / Windows Worker。
4. **本机和双机验收**：用户一次性安装；SSH/设备身份与端口检查；HOLD 下验证
   `Lease=0 / Attempt=0 / Comfy POST=0`。
5. **GPU 试片（独立显式批准后）**：《茅台》3×4 秒→ QC / 人工审片→
   FFmpeg MP4 / manifest / receipt；保留失败尝试与真实单位 GPU 成本证据。

## 五、当前证据边界（2026-11-20）

- 用户终端已返回 Mac `health.status=ok`、`database=ok`、`version=2.3.27.1`，
  `launchctl state=running`，监听 `127.0.0.1:8766`。此前数据库与备份验证见 Issue #296。
- #297 是**测试与安装保护 Draft PR**，不是完整 V3.1 Windows+Mac 发布。
- 2.3 的 Worker Witness preflight 设计上仍有强制 409 的阻断，
  不得因为 Challenge 通过就宣称已获得 Claim/POST 能力。
- 未做：用户机器 V3.1 安装、双机跨网通信、GPU 生成、真实影片质量验收。
  除非全部通过，发布状态必须是 **BLOCKED / UNVERIFIED**。

## 六、拒绝事项

不得替换真实 2.3 Core 数据库、绕过 Owner/MASTER HOLD、复制 2.2 迁移、
增加并行执行器、自动启动 Supervisor/Worker、以模拟或 CI 结果代替实机验证，
或要求用户反复执行大量终端命令来补救版本集成问题。


## 七、2026-11-20 决策：桌宠 V2 冻结，双机视频生产架构 P0

**决策状态：用户明确要求；本节覆盖此前任何“桌宠 44 PNG 应优先补齐”的开发排序。**

### 7.1 暂停范围

- 暂停 `windows/desktop/src/PicotooPet.Desktop/Assets/Maotai/V2/` 的 44 个桌宠 Raster Skeleton PNG、`v1.png`、`motion_sheet.png` 的后续生成、分层、挑选、替换、视觉微调与相关动作验收工作。
- 先前双足圆球形、蓝耳机的拟人桌宠方案**不是**当前电影角色身份标准；现有文件仅作为历史尝试记录，不能伪称《茅台》正式形象，也不要删除原始文件。
- 桌宠的蓝色耳机、WPF 动作、10 分钟运动稳定性属于独立软件视觉附加功能；不得向**视频制作角色资产**施加其外观约束。电影角色以用户认可的真实阿拉斯加犬参考（黑白奶油色毛、荧绿色三角围巾、四足体态）为准。
- 桌宠不作为本阶段 Mac Core、Creative、Production Plan、Windows Worker、Comfy、QC、FFmpeg、手机/网页操控的依赖或准入条件；不为它新增设计、模型、日常操作、GPU 工作量或新执行器。

### 7.2 “绕过桌宠问题”的精确定义

- **允许：** 在规划、任务排期、专门的视频生产集成测试中**跳过桌宠功能和桌宠视觉验收**；保留缺口清单和独立失败证据，开发一条与桌宠完全解耦的 P0 视频生产交付/验收路径。
- **不允许：** 修改/删除 `MaotaiNaturalMotionV2AcceptanceSmokeTests` 来冒充完整正式 Windows Release PASS；创建空白或伪分层 PNG；谎报原版 Release、签名安装包、Owner/MASTER 授权、GPU 渲染或实机通过。
- **事实标记：** 现有 `Phase 2.3 Slice D Windows Prebuilt Release` 仍因 `torso_neutral.png` 等 44 张素材缺失而 **BLOCKED（desktop-pet-only）**。与其独立的 P0 film-only 开发者构建可有自己的真实构建/哈希结果，但不能将 `user_install_allowed=false` 的内部预览包宣称为正式用户安装包。
- 如果工程确需一个**可安装的、无桌宠依赖的影视工作站发行包**，单独定义清楚发行范围、功能禁用方式、签名/版本/回滚和安全验证，在真实原生 CI 全部通过后再申请用户实机安装授权；**不冒用原有完整 Release 标签**。

### 7.3 新的唯一工作顺序（架构第一）

1. **P0-A 权威架构集成：** 保留 Mac Core 2.3.27.1、SQLite schema 24 和真实历史任务；核对 V3.1 StoryPack/导演台 ↔ 原有 Creative Package / Goal / Production Job / 冻结 Plan 的合规映射。StoryPack 目前是只读预览，**不能直接当作可执行 Production Plan**。
2. **P0-B 双机通信和恢复：** 保留 Ed25519 Challenge → Witness、Owner/MASTER/HOLD、单一 Windows Same-EXE Worker、Credential Manager / Keychain、私有 SSH/HTTPS 通道；验证双端真实 API、Outbox/Journal 恢复、重启去重及 `Lease=0 / Attempt=0 / Comfy POST=0` 的 HOLD 准入。
3. **P0-C 最短用户入口：** Windows Studio 能清楚完成“提供故事→检查缺少哪些已认证宠物/场景资产→必要的主人审批→生产计划审阅”；减少反复粘贴 JSON、手动传文件或运行脚本。手机远程控制后续接同一个 Mac Core，不增加第二条队列或暴露公网 Bearer。
4. **P0-D 真实首片：** 在用户**单独明确许可 GPU**、素材来源认证以及 Plan/Owner 门禁满足后，做《茅台》`3×4s / 832×480 / 24fps / 97 帧每镜`，经真实 QC、失败局部重试、FFmpeg 拼接和人工 ACCEPT；保存 MP4、每镜原始证据及可追溯哈希。
5. **P1：** 首片完成后再迭代镜头良率、无限候选池、连续性、云端/手机便利性和日常自动化。桌宠功能仍处于冻结状态，只有用户重新明确授权才恢复。

### 7.4 Claude/其他 Windows 执行者范围

Windows 执行者应**先只读盘点当前 Mac 2.3 API/Windows 客户端契约与本地 Comfy/Wan/LTX/FFmpeg/Worker**；能安全完成的开发在独立分支+Draft PR 中实现并运行 CPU-only 原生 CI。不得为了“解决桌宠报错”改动核心门禁、让假资产通过测试，或启动 Comfy GPU POST。Windows 实机检查不等于 Mac 实机、完整影片或用户授权。

**验收报告必须分别写：** ARCHITECTURE/CPU CI、WINDOWS LOCAL READ-ONLY、MAC LIVE/NETWORK、OWNER/MASTER/GPU、RENDER/QC、FORMAL FULL RELEASE（桌宠 BLOCKED）。任何一项未知都为 UNVERIFIED，不合并为总体 PASS。
