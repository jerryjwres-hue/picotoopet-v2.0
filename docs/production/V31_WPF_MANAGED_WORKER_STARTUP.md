# PicotooPet V3.1｜Studio 管理现有 Windows Worker（默认不启动）

这一改动不是新执行器。Studio 只启动、暂停已有 `PicotooPet.Worker.exe`；任务读取、旧 Journal、文件 SHA、ComfyUI inbox、QC/剪辑均继续复用旧 Bridge。

## 用户日常操作

首次：连接 Mac Core、选择已有 Windows 视频项目目录，然后点击「一次配对并启动 Worker」。填 Worker ID 和独立配对密钥，勾选「以后打开 Studio 自动启动」。

以后：正常打开 Studio；仅在此前自愿勾选且配置完整时，Studio 自动启动同一个 Worker。连接暂时离线时，Bridge 用已有重试逻辑恢复。Core Owner/Master/冻结 Plan 仍逐条授权；Windows Worker 并不会因为自动启动就能领取 GPU。

需要暂停：点击「暂停新任务」，它只使用原有 Bridge `--pause-new` 标记，**不会终止进行中的 GPU 作业或删除 Journal**。点击「恢复新任务」只取消本地暂停，不解除 Core 的全局 HOLD。

## Mac 端独立 Worker 首次配对（补齐 #289 缺失的另一半）

现有 `INSTALL_MAC.command` 初次安装时，会在当前用户 Keychain 生成
独立 256-bit Worker HMAC（`PicotooPetV3.WorkerAttestation`）；升级先检查原项并原样保留。
不会覆盖 Mac Core 的 `PicotooPetV2.API` 设备令牌，也不导出密钥到
`.plist`、TOML、ZIP、SQLite、日志或 GitHub。

仅**首次在用户 Mac 上显式双击** `scripts/mac/SHOW_WORKER_PAIRING.command`
时，才会从 Keychain 读取并在本地 Terminal 显示：

- Worker ID 固定为 `edit-workstation`（与 Windows Studio 当前默认值一致）。
- Worker HMAC 是单独生成的 43 位 base64url 字符，仅用于复制到 Windows
  Studio 原有「一次配对并启动 Worker」窗口；不要将其发送给聊天或复制进 GitHub。

Core 启动时，在没有任一显式 Worker 环境变量的情况下读取该密钥；
如果管理员已明确同时指定 `PICOTOO_WORKER_ATTEST_ID` 和
`PICOTOO_WORKER_ATTEST_KEY`，原配置优先。只设置其中一个则拒绝混用
Keychain，保持配置错误而非悄悄降级。

**这一改动只补齐双方的 Worker HMAC 身份配置，不自动确认网络联通**：
独立 Windows Worker 仍要求可信 Mac HTTPS 或同机 loopback HTTP。
旧局域网 HTTP 地址不能直接用于带设备令牌的生产 Worker。
Mac 必须重新安装/重启到包含这次修改的 Core 才会加载新 Keychain 配对。
Owner/MASTER/来源字节/冻结 Plan 的独立审核、默认 GPU HOLD、受控租约与
真实三镜头画质验收完全不变。不要在有执行中 GPU 任务时强制重启 Mac Core。

## 安全与一次性配置前提

- Mac Core 必须有可信 HTTPS（同一台机器的 `127.0.0.1` HTTP 除外）。旧默认局域网 HTTP 不允许用于独立 Worker 的自动启动；无需为了省事降低 TLS 验证。
- Windows Studio 的原有 Mac device Bearer 继续存在 Windows Credential Manager；独立 Worker HMAC 则保存在另一 Credential Target `PicotooPetV3/WorkerAttestationKey`，不是普通 JSON 设置、TOML、日志或命令行参数。
- Mac Core 必须另行配置相同 Worker ID 和同一个随机密钥，以及 Owner 审核和独立 MASTER 审核机制。Studio 不会自行修改 Mac 配置、不能伪造 Owner 权限。
- 已配置 HMAC 的 Python Worker，如果 Core challenge 是 204 或密钥不合法，**不再调用 unsigned legacy lease**。默认情况下 GPU 始终 HOLD。
- 非敏感的 Worker ID、项目路径、是否自动启动仍写在原有 DesktopSettingsStore；操作员未勾选之前，自动启动为 false。
- 同一项目、同一 worker_id 的 `.lock` 由原有 Python Bridge 独占；再次打开 Studio 不重复启动第二个 Bridge。
- Studio 退出时不杀死可能在处理旧 Journal 的 Worker；暂停与恢复使用同一个原有 Worker 的本地命令，不清空原始回执。

## 当前验证边界

CI 只覆盖 Windows WPF 真实控件、进程启动前安全拒绝、字节锁、macOS/Python 合成负例以及打包组件。**尚未验证实际 Mac HTTPS 部署、一次性真实密钥配对、Windows 后台长时间运行、ComfyUI、GPU 或三镜头视频质量。**

发布与首次 GPU 授权仍要求人工验收。安装包尚未公开正式代码签名，不得通过陌生来源分发。