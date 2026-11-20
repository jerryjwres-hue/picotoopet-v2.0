PicotooPet｜Windows 安装（Phase 2 内部预编译版）

首次使用只需要三步：
1. Mac 上先双击该版本的 scripts/mac/INSTALL_MAC.command，完成后台 Core 安装。
2. Windows 完整解压本 ZIP，双击 INSTALL_PHASE2_WINDOWS.vbs。
   安装器会校验 SHA-256、安装、创建桌面入口并自动启动 Studio。
   正常成功不再弹出 JSON 报告，无需打开 PowerShell、安装 .NET SDK 或编译源码。
3. 在 Studio 中填入 Mac 地址和设备令牌，保存连接；仅首次配对需要。
   Mac 令牌保存在该用户的系统 Keychain，不放进本 ZIP 或安装日志。

以后：
- Windows 打开“Picotoo Pet AI”即可使用；Mac Core 有后台 LaunchAgent。
- 要检查连通性：可选双击 VERIFY_PHASE2_WINDOWS.vbs。
- 要回退版本：双击 ROLLBACK_PHASE2_WINDOWS.vbs。
- 安装失败才会自动打开诊断 JSON；报告也保留在
  %LOCALAPPDATA%\PicotooPetV2\DesktopApp\reports

重要边界：
- 这是 Phase 2 内部测试安装包，并非已验收的 V3.1 一键生产正式版。
- 手机 Studio 当前为独立 HTTPS 只读入口；不应当作 GPU/Owner 审批授权。
- 不触发新 GPU 任务、不自动解除 GPU HOLD、不修改生产 MASTER 使用权。
- 发布包仍未正式代码签名；仅从受信任的 GitHub CI 构建结果获取，并核验 SHA-256。
- 保留现有 Comfy Desktop、模型路径、Mac SQLite 和宠物原始素材，不把模型打进安装包。
