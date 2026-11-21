# Picotoo Pet V2

V2.2 Phase 0/1 独立仓库：Mac Core、SQLite 耐久队列、权限门、审计、Result Store、MCP、REST/WebSocket、Ollama 常驻管理，以及 Windows ComfyUI 检测和固定模型安装器。

## 直接入口

- Mac：双击 `scripts/mac/INSTALL_MAC.command`，随后双击 `scripts/mac/VERIFY_MAC.command`。
- Windows 安装/修复：双击 `windows/bootstrap/RUN_WINDOWS_SETUP.vbs`。
- Windows 只读检测：双击 `windows/bootstrap/VERIFY_WINDOWS_SETUP.vbs`。
- 源码验证：双击 `VERIFY_RELEASE.command`，或运行 `PYTHONPATH=src pytest -q`。

## 冻结边界

- V1 只备份，不作为 V2 运行依赖。
- Protected 原始数据不写、不移动、不删除、不覆盖、不直接上传。
- Mac 只把 `gpt-oss:20b` 设为永久常驻默认模型。
- Windows 不安装第二份 20B LLM，也不安装通用 8B LLM。
- 云端上传必须人工批准。

详细状态和未完成的实机验收见：

- `docs/phase0/PHASE_0_VERIFICATION_REPORT.md`
- `docs/phase1/IMPLEMENTATION_STATUS.md`
- `docs/phase1/INSTALLATION_GUIDE_CN.md`

## 当前 P0 任务调整（2026-11-20）

以 [Mac 2.3 + Windows V3.1 权威架构与门禁手册](docs/p0_296/REAL_23_V31_ARCHITECTURE_GATES.md) 为准。**桌宠 V2 的 44 张独立 PNG 素材与动作验收已暂停**，不应再排入视频生产主线；桌宠导致的完整正式 Windows Release 失败应如实单独保留，不能通过伪造素材或关闭安全门禁掩盖。项目优先完成 Mac Creative → 冻结 Production Plan → Windows Same-EXE Worker → Wan/LTX → QC → MP4 的真实双机闭环。
