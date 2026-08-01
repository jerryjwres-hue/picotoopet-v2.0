Picotoo Pet V2 Phase 2 Windows 预编译安装包

重要：
- 本安装包不得包含源码构建步骤。
- 用户电脑不需要 .NET SDK。
- 安装器会显示 0%–100% 进度并持续写入 install-state.json。
- 所有预编译文件在安装前后都进行 SHA-256 校验。

安装：
1. 完整解压 ZIP。
2. 双击 INSTALL_PHASE2_WINDOWS.vbs。
3. 等待进度达到 100%，并检查自动打开的 JSON 报告 status=pass。

验证：
1. 在桌面程序中填写 Mac 地址和令牌并保存连接。
2. 双击 VERIFY_PHASE2_WINDOWS.vbs。
3. 检查 phase2-windows-verification.json 的 status=pass。

回滚：
- 双击 ROLLBACK_PHASE2_WINDOWS.vbs。

运行数据：
%LOCALAPPDATA%\PicotooPetV2\DesktopApp

本包不会修改：
- Comfy Desktop
- E:\PicotooPet\Models
- Mac Core 数据库
- Maotai、REAL PET 或 Protected 数据
