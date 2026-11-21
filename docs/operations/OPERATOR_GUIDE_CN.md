# 日常操作指南

安装完成后，普通任务不要求打开 Terminal、CMD 或 PowerShell。

- Mac Core 和健康监督由 launchd 自动启动。
- `gpt-oss:20b` 被卸载出内存时，健康监督器会重新执行常驻加载。
- 本地任务自动进入 SQLite 队列并恢复。
- 云端上传任务必须停在 `WaitingForApproval`，只有一次性批准令牌可恢复任务。
- Windows 模型检查或修复使用 VBS 双击入口。
- 原始 Maotai 数据、Raw Evidence 和原始媒体不被移动、覆盖或直接上传。

常用入口：

| 目的 | 入口 |
|---|---|
| Mac 安装/升级 | `scripts/mac/INSTALL_MAC.command` |
| Mac 验证 | `scripts/mac/VERIFY_MAC.command` |
| Mac 备份 | `scripts/mac/BACKUP_MAC.command` |
| Mac 修复 | `scripts/mac/REPAIR_MAC.command` |
| Mac 回滚 | `scripts/mac/ROLLBACK_MAC.command` |
| Windows 检测并安装模型 | `windows\bootstrap\RUN_WINDOWS_SETUP.vbs` |
| Windows 仅验证 | `windows\bootstrap\VERIFY_WINDOWS_SETUP.vbs` |

任何报告出现 `hash-mismatch`、`PROTECTED_MUTATION_DENIED`、`MODEL_MISSING` 或 `SERVICE_UNAVAILABLE` 时，先保留报告和日志，不要手工移动原始数据。


## 2026-11-20 临时执行优先级：桌宠暂停

**最高优先级是 PicotooPet 的 Mac↔Windows 视频生产架构，不是 Windows Q 版桌宠。** 详细不可绕过的协议与实施边界见 [P0 #296 架构与门禁](../p0_296/REAL_23_V31_ARCHITECTURE_GATES.md#七2026-11-20-决策桌宠-v2-冻结双机视频生产架构-p0)。

- 暂停生成/验收 44 张 `Assets/Maotai/V2` 桌宠 PNG，不再沿用双足圆球角色图；不删除已有尝试和证据。桌宠异常只记录为可选功能阻塞，不要求用户解决后才能开展三镜头视频工作。
- **不要为了忽略桌宠而隐藏正式 Release 失败。** 旧完整 Windows Release 继续标记 `BLOCKED (desktop pet assets)`，视频生产专用独立构建/检查必须如实标注身份、SHA、HOLD 和安装限制。
- Windows 实机操作先做只读检查、CPU-only 联调和安全回滚；不得擅自运行 GPU、Comfy POST、升级运行中的 Mac Core 或解除 Owner/MASTER/HOLD。
- 日常产品目标保持：一个导演台输入故事，Mac 权威计划，Windows 同一 Worker 执行，视觉 QC 与 MP4 归档，手机远程审核使用同一后台。

## 桌宠扩展位最终策略（2026-11-21）

桌宠 V2 **只是保留的理论空位**：默认关闭、不读取 v2 角色图片、不生成动画、不执行其素材/像素/运动测试。44 张 PNG、耳机与双足形象等均不在本期开发/安装/影视验收范围。

旧完整桌宠 Release 已改为**仅手动触发**，它的历史失败不再影响常规 GitHub PR/影视生产构建。今后不得因缺少 `torso_neutral.png` 等桌宠资产反复请求用户或 Claude 操作。当前仅维护 Mac Core → 本地 Creative → Production Plan → Windows Worker → Comfy/QC/MP4 主线；原有安全/审批/HOLD 不可绕过。

如未来用户明确启用桌宠，另开隔离任务评估素材、行为及独立发布；不要自动恢复此功能。
