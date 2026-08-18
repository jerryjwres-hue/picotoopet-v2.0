Picotoo Pet V2 — Windows 2.3.26.1 / Research 2.3.27.1 预编译安装包

发布状态：
- 目标架构：win-x64。
- 正式桌面程序仍是原生 WPF「Picotoo Pet AI.exe」，不新增浏览器 UI 或本地网页壳。
- 候选包只有在原生 Windows CI 的编译、真实 STA WPF、发布 EXE 自检、目标完整性、完整安装、离线验证、恢复和回滚全部通过后才可上传。
- 本包用于当前 PicotooPet 项目的用户验收安装。
- 本包状态为 unsigned-ci，尚未进行公开发布所需的代码签名；Windows SmartScreen 可能显示未知发布者警告。

本版能力：
- 任务中心继续支持固定类型 system.diagnostic_snapshot，并显示固定 Core、Worker、Queue、Checks、Warnings 安全卡片。
- 新增固定只读网络调研任务 research.search：Windows 只提交经过约束的查询；Mac Worker 通过独立 Research Gateway 执行固定 Research 能力。
- Windows 不直接调用外部研究工具，也不接收任意命令、脚本、文件路径或任意 URL 作为执行入口。
- Research Gateway 只承担搜索/读取型网络调研；不执行点赞、关注、评论、发帖或其他账号写操作。
- 已完成的 Research 任务可从任务列表/结果中心进入统一任务详情，并通过“查看详情 / 结果”读取 Mac Core 保存的固定 Research 结果。
- Research 结果读取不会重新发起网络调研；未知结果类型不会回退为任意文件、日志或原始内容浏览。
- 继续使用一次用户动作对应的稳定 Idempotency-Key；网络重试复用同一键，避免重复创建同一任务。
- 实时观察 Queued、Running、Completed、Failed 或 Cancelled；事件流中断时使用有界 REST 恢复，不阻塞界面线程。
- 支持安全取消和创建新的重试子任务，不重新打开原终态任务。

Research 执行边界：
- Mac Core 是任务与结果的唯一事实源；Windows 只是 Control Center。
- Mac Worker 只在声明支持 research.search 时才接收该任务。
- Research Gateway 与 Mac Worker/Core 分进程，调用固定 capability 与结构化参数，不开放任意 shell。
- Research 默认只读；不会修改 Chrome 登录状态，不会安装或升级用户已有的外部研究工具。
- 账号写操作不属于 research.search；本安装包没有点赞、关注、评论、发帖、删除等社交账号写能力。
- Windows 读取 Research 结果时只访问 Mac Core 的固定 task_id Research result API，并保持结果大小、类型和完整性校验。

隐私与稳定边界：
- 不显示 Token、原始认证头、日志正文或任意本地文件内容。
- Windows 不直接执行 Research/诊断处理；任务由 Mac Worker 按固定注册能力执行。
- Research 的外部网络访问发生在 Mac Worker → Research Gateway 的只读执行链，不是 Windows 直接访问。
- 历史 analysis 任务保持原状态，不会被自动改写为 Research 或诊断任务。
- 安装器不修改 Mac Core 数据库、Research 结果存储、Comfy Desktop、模型目录或用户文档。

重要：
- 用户 Windows 电脑不执行源码编译，也不需要安装 .NET SDK。
- ZIP 只包含一个顶层目录；必须完整解压该目录后再运行脚本。
- 安装前后会校验每个预编译文件的路径、SHA-256 和文件大小。
- 安装、验证和回滚共同校验桌面、开始菜单和开机启动三处快捷方式。
- 桌面路径使用 Windows DesktopDirectory，兼容 OneDrive 或其他重定向桌面。

安装：
1. 完整解压 ZIP，并打开唯一的 PicotooPet-Phase2-Windows-Prebuilt-* 顶层目录。
2. 双击 INSTALL_PHASE2_WINDOWS.vbs。
3. 等待进度达到 100%。
4. 检查自动打开的 phase2-prebuilt-install-*.json，确认 status=pass、shortcuts_verified=true。

完整验证：
1. 先确认同批次 Mac Core、Mac Worker、Research Gateway 均已安装并通过各自 VERIFY。
2. 启动 Picotoo Pet AI，确认 Mac Core 在线、Mac Worker 正常，并且 Research 能力在 Worker 支持列表中可用。
3. 双击 VERIFY_PHASE2_WINDOWS.vbs，检查 phase2-windows-verification.json 的 status=pass。
4. 在任务中心创建 system.diagnostic_snapshot，等待 Completed，并打开固定诊断安全卡片。
5. 创建一个 research.search 只读调研任务，等待 Completed。
6. 在“已完成”/任务中心/结果中心打开该任务，点击“查看详情 / 结果”，确认能看到查询和固定 Research 输出；打开结果本身不得再次触发网络任务。
7. 对不支持的未知结果类型，界面应明确提示不支持安全预览，不得退化为任意内容浏览。

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
- Chrome 登录状态。
- 历史 analysis 任务。
- Maotai、REAL PET 或 Protected 数据。
