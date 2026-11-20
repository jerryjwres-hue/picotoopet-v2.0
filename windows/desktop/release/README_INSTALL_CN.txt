PicotooPet｜Windows 安装（Phase 2 内部预编译版）

首次使用只需要三步：
1. Mac 上先双击该版本的 scripts/mac/INSTALL_MAC.command，完成后台 Core 安装。
2. Windows 完整解压本 ZIP，双击 INSTALL_PHASE2_WINDOWS.vbs。
   安装器会校验 SHA-256、安装、创建桌面入口并自动启动 Studio。
   正常成功不再弹出 JSON 报告，无需打开 PowerShell、安装 .NET SDK 或编译源码。
3. 使用安全的 Mac 连接（首次需 Mac 已开启 Remote Login、Windows 已完成 SSH 公钥和主机身份信任）：
   双击本 ZIP 的 CONNECT_MAC_SECURE.vbs，输入 Mac 主机、系统用户名和 Core 端口。
   看到 SECURE_MAC_TUNNEL=READY 后，Studio 的 Mac Core 地址填 http://127.0.0.1:18766；
   再填原设备令牌，保存连接。设备令牌保存在 Windows Credential Manager，不写入 ZIP 或日志。
   如果 Mac 已有可信 HTTPS 地址，可直接使用 HTTPS，不需要开 SSH。

以后：
- Windows 打开“Picotoo Pet AI”即可进入 Studio；Mac Core 有后台 LaunchAgent。
- 安装包已包括真正的 Windows GPU Bridge 运行时及 QC/剪辑/批次审片组件。
  Windows Studio 的本地批次导入不再要求额外安装 Python 3.11 或 py 启动器。
- SSH 隧道仅在 Windows 本机开放端口 18766，系统验证 known_hosts/SSH 公钥。
  初次 SSH 配置不是无操作；若未提前建立 SSH 公钥信任，脚本会安全失败，不自动降级 HTTP。
  Windows 重启、网络断开后需重新双击 CONNECT_MAC_SECURE.vbs；这不是无人值守隧道。
- 原先保存的 http://192.168.x.x:8766 地址将被 Studio 明确拒绝，因为设备令牌不能走明文局域网。
- Worker 不会在安装时自动启动；还需首次安全配置 Worker、受控授权与现有 ComfyUI/模型。
  安装包自检只验证本地代码和文件 SHA，不等于视频生产或视觉良品率验收。
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
