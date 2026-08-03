Picotoo Pet V2 2.3 Task Center 修复版 Windows 预编译安装包

发布状态：
- 目标架构：win-x64。
- 已通过原生 Windows CI 的构建、真实 WPF 页面、完整安装、离线验证、回滚和重定向桌面夹具。
- 本包允许用于当前项目的用户验收安装。
- 本包状态为 unsigned-ci，尚未进行公开发布所需的代码签名；Windows SmartScreen 可能显示未知发布者警告。

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
1. 在桌面程序中填写 Mac 地址和令牌并保存连接。
2. 双击 VERIFY_PHASE2_WINDOWS.vbs。
3. 检查 phase2-windows-verification.json 的 status=pass。

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
- Mac Core 数据库。
- 历史 analysis 任务。
- Maotai、REAL PET 或 Protected 数据。
