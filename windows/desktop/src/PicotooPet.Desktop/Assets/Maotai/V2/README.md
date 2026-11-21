# 茅台 v2 Raster Skeleton 正式资产目录

此目录只接受真正独立绘制/导出的透明 PNG 部件，发布时映射到 `ui-assets/maotai/v2`。

资产硬约束：

- 角色是阿拉斯加犬「茅台」，保持现有高质量 Q 版 / 3D CG 视觉方向和蓝色耳机识别元素。
- 禁止从完整角色 PNG 裁切头、爪、尾；禁止同一完整 PNG 的 Clip 变体；禁止整图状态帧硬切。
- 所有文件必须是带真实 alpha 通道的 PNG（RGBA 或 grayscale+alpha），透明背景。
- 同一 canonical pose、perspective、lighting 下导出，关节 Pivot 与 `MaotaiAssetManifest` 对齐。
- 每个连接关节必须保留至少 12 px 隐藏毛发 overlap；主要肢体建议 18–24 px，避免旋转时露白缝。
- 不允许在本目录加入额外完整角色状态 PNG；Smoke Gate 会拒绝 manifest 之外的 PNG。
- 正式资产缺失或损坏时运行时 fail closed；Shell/Core/Worker/Task/Approval 不得受影响。

当前 Smoke Gate 同时验证：文件齐全、PNG 签名、IHDR、像素尺寸、alpha 通道、manifest Pivot/overlap，以及 installer publish 映射。

## 桌宠扩展位最终策略（2026-11-21）

桌宠 V2 **只是保留的理论空位**：默认关闭、不读取 v2 角色图片、不生成动画、不执行其素材/像素/运动测试。44 张 PNG、耳机与双足形象等均不在本期开发/安装/影视验收范围。

旧完整桌宠 Release 已改为**仅手动触发**，它的历史失败不再影响常规 GitHub PR/影视生产构建。今后不得因缺少 `torso_neutral.png` 等桌宠资产反复请求用户或 Claude 操作。当前仅维护 Mac Core → 本地 Creative → Production Plan → Windows Worker → Comfy/QC/MP4 主线；原有安全/审批/HOLD 不可绕过。

如未来用户明确启用桌宠，另开隔离任务评估素材、行为及独立发布；不要自动恢复此功能。
