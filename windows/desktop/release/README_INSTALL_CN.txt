Picotoo Pet V2 — Phase 2.3 Slice D Windows 预编译安装包

发布状态：
- 目标架构：win-x64。
- 候选包只有在原生 Windows CI 的编译、真实 STA WPF、发布 EXE 自检、完整安装、离线验证、回滚和重定向桌面夹具全部通过后才上传。
- 本包用于当前 PicotooPet 项目的用户验收安装。
- 本包状态为 unsigned-ci，尚未进行公开发布所需的代码签名；Windows SmartScreen 可能显示未知发布者警告。

本版新增：
- 在任务中心创建固定类型 system.diagnostic_snapshot。
- 使用一次用户动作对应的稳定 Idempotency-Key；网络重试最多一次并复用同一键。
- 实时观察 Queued、Running、Completed、Failed 或 Cancelled。
- 事件流中断时使用有界 REST 恢复：1、2、4、8、10 秒退避，总窗口最多 2 分钟，不阻塞界面线程。
- 支持安全取消和创建新的重试子任务，不重新打开原终态任务。
- 已完成诊断任务可显示固定 Core、Worker、Queue、Checks 和 Warnings 卡片。
- 只渲染固定结果合同，不渲染服务端未知字段；结果读取失败时显示安全错误卡片，不让页面崩溃。

隐私与稳定边界：
- 不读取或显示 Token、IP、日志正文、文件清单、项目内容或用户文档。
- 不调用 Provider，不访问外部网络，不产生费用。
- Windows 不执行诊断处理；任务由 Mac Worker 单任务执行。
- Mac Worker 的诊断硬超时为 30 秒，取消或超时后清理子进程。
- 历史 analysis 任务保持原状态，Windows 不把它们当作 Slice D 可执行任务。

重要：
- 用户电脑不执行源码编译，也不需要安装 .NET SDK。
- ZIP 只包含一个顶层目录；必须完整解压该目录后再运行脚本。
- 安装前后会校验每个预编译文件的路径、SHA-256 和文件大小。
- 安装、验证和回滚共同校验桌面、开始菜单和开机启动三处快捷方式。
- 桌面路径使用 Windows DesktopDirectory，兼容 OneDrive 或其他重定向桌面。

安装：
1. 完整解压 ZIP，并打开唯一的 PicotooPet-Phase2-Windows-Prebuilt-* 顶层目录。
2. 双击 INSTALL_PHASE2_WINDOWS.vbs。
3. 等待进度达到 100%。
4. 检查自动打开的 phase2-prebuilt-install-*.json，确认 status=pass、shortcuts_verified=true。

验证：
1. 确认同批次 Mac Core 与 Mac Worker Slice D 已安装并通过 VERIFY。
2. 启动 Picotoo Pet AI，确认连接在线且任务中心正文正常显示。
3. 双击 VERIFY_PHASE2_WINDOWS.vbs。
4. 检查 phase2-windows-verification.json 的 status=pass。
5. 在任务中心点击“创建系统诊断”，等待任务进入 Completed，再点击“查看诊断结果”。

回滚：
1. 双击 ROLLBACK_PHASE2_WINDOWS.vbs。
2. 检查 phase2-rollback-*.json 的 status=pass、shortcuts_verified=true。
3. 回滚会恢复 current/previous 版本指针以及桌面、开始菜单和开机启动快捷方式，不删除用户数据。

安装产生的系统修改：
- 写入 %LOCALAPPDATA%\PicotooPetV2\DesktopApp。
- 创建或更新当前用户桌面快捷方式。
- 创建或更新当前用户开始菜单快捷方式。
- 创建或更新当前用户开机启动快捷方式。

本包不会修改：
- Comfy Desktop。
- E:\PicotooPet\Models。
- Mac Core 数据库和结果存储。
- 历史 analysis 任务。
- Maotai、REAL PET 或 Protected 数据。
