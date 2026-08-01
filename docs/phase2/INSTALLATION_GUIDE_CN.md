# Picotoo Pet V2 Phase 2 Windows Desktop 安装指南

## 本阶段安装什么

Phase 2 第一纵向切片安装 Windows 全局桌面控制面板的基础版本，并连接已经运行在 Mac 上的 Mac Core。它验证以下完整链路：

```text
Windows 点击创建任务
→ REST 请求到 Mac Core
→ Mac SQLite 耐久入队
→ 同事务写入 Outbox
→ WebSocket 顺序推送
→ Windows 增量更新任务状态
```

该安装不会修改 ComfyUI、Wan 模型、Maotai 数据库、REAL PET 原始素材或任何 Protected 路径。模型安装问题可以与本阶段独立处理。

## 前置条件

1. Windows 11 x64。
2. Mac Core 已在 Mac 上运行，当前确认地址为 `http://192.168.1.161:8766`。
3. Windows 与 Mac 位于同一局域网。
4. Windows 可使用 WinGet。若没有 .NET 10 SDK，安装器会使用 Microsoft 官方包 `Microsoft.DotNet.SDK.10` 安装。
5. 第一次安装和第一次自动安装 SDK 时可能弹出 Windows UAC；这是一次性部署行为，日常使用不需要 Terminal、CMD 或 PowerShell。

## 安装步骤

1. 将 Phase 2 交付包完整解压到简单路径，例如：

   ```text
   D:\PicotooPetV2_Phase2
   ```

2. 进入：

   ```text
   windows\desktop\scripts
   ```

3. 双击：

   ```text
   INSTALL_PHASE2_WINDOWS.vbs
   ```

4. 安装窗口在后台运行，不要连续重复点击。安装器会依次：

   - 检测 .NET 10 SDK；
   - 缺失时通过 WinGet 安装 Microsoft 官方 SDK；
   - 运行无第三方依赖 Smoke Test；
   - 以 `win-x64`、Self-contained、Single-file、ReadyToRun 方式发布 WPF 程序；
   - 发布独立实机诊断工具；
   - 计算主程序和诊断程序 SHA-256；
   - 安装到版本化目录；
   - 原子更新当前版本指针；
   - 保留上一版本回滚指针；
   - 创建开始菜单和开机启动快捷方式；
   - 启动 `Picotoo Pet AI.exe`；
   - 打开 JSON 安装报告。

## 安装目录

程序版本：

```text
%LOCALAPPDATA%\PicotooPetV2\DesktopApp\versions\<版本号>
```

当前版本指针：

```text
%LOCALAPPDATA%\PicotooPetV2\DesktopApp\current_version.json
```

上一版本指针：

```text
%LOCALAPPDATA%\PicotooPetV2\DesktopApp\previous_version.json
```

日志与报告：

```text
%LOCALAPPDATA%\PicotooPetV2\DesktopApp\logs
%LOCALAPPDATA%\PicotooPetV2\DesktopApp\reports
```

非敏感桌面设置：

```text
%LOCALAPPDATA%\PicotooPetV2\Desktop\settings.json
```

设备令牌不会写入上述文件，而是保存到 Windows Credential Manager 的 `PicotooPetV2/MacCoreApiToken`。

## 第一次连接

打开 Picotoo Pet AI 后：

1. 进入“连接设置”。
2. Mac 地址保持：

   ```text
   http://192.168.1.161:8766
   ```

3. 输入 Mac Core 设备令牌。
4. 点击“保存并连接”。
5. 连接状态应依次显示“连接中”与“在线”。
6. 总览页应显示 Mac Core 健康状态和 REST、WebSocket p95 延迟。

当前切片先使用一次性手工录入令牌；后续配对阶段会增加局域网发现和短码配对，不会取消 Credential Manager 安全存储。

## 验证

完成配对后，双击：

```text
VERIFY_PHASE2_WINDOWS.vbs
```

验证器会使用真实程序组件执行：

- 当前版本指针检查；
- 主程序和诊断程序 SHA-256 校验；
- Credential Manager 令牌读取；
- 500 次 Mac Health REST 请求；
- WebSocket 自动连接、Ping/Pong 和事件续传；
- 创建 500 条隔离标记为 `phase2-diagnostic` 的 `phase2.link.acceptance` 本地测试任务；
- 逐条等待对应任务通过 Outbox 和 WebSocket 回传，并采集端到端时延；
- 输出 p50、p95、p99、最大值和 SLO 判定。

报告位置：

```text
%LOCALAPPDATA%\PicotooPetV2\DesktopApp\reports\phase2-windows-verification.json
```

验证程序不会读取业务原始文件，不会上传云端，也不会写 Maotai 正式数据库。

## 回滚

新版本出现问题时，双击：

```text
ROLLBACK_PHASE2_WINDOWS.vbs
```

回滚只会：

- 验证上一版本主程序和诊断程序 SHA-256；
- 停止当前桌面进程；
- 交换当前和上一版本指针；
- 更新开始菜单与开机启动快捷方式；
- 启动上一版本；若启动失败则自动恢复回滚前版本；
- 生成回滚报告。

回滚不会删除设置、日志、Credential Manager Token、任务、模型或任何业务数据。

## 当前交付边界

本包已经提供完整源码、安装器、验证器和回滚逻辑，但生成环境没有 Windows/.NET SDK，因此这里不能宣称 WPF 已在本环境编译。最终可执行文件必须由你的 Windows 11 机器通过安装入口构建，并以实机验证 JSON 为最终证据。只有报告达到 `status: pass`，Phase 2 第一纵向切片才算通过实机验收。
